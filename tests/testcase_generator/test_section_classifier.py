from __future__ import annotations

from uuid import UUID

import pytest

from src.testcase_generator.schemas.parsed_context import SectionExtract, SourceItem
from src.testcase_generator.stages.parse import section_classifier


def _sources() -> list[SourceItem]:
    return [
        SourceItem(
            doc_id=UUID("11111111-1111-1111-1111-111111111111"),
            doc_type="prd",
            trust_level=1,
            title="需求",
            sections=[
                SectionExtract(
                    heading="商品同步",
                    content="商品库每日同步上游数据。",
                    source_ref="prd:需求 §商品同步",
                )
            ],
        )
    ]


class _FailingClient:
    async def generate_structured(self, *args, **kwargs):
        raise TimeoutError


class _PartialClient:
    async def generate_structured(self, *args, **kwargs):
        return section_classifier._ClassifyOutput(
            classifications=[
                section_classifier._SectionKindOut(
                    section_ref="prd:需求 §商品同步",
                    kind="spec",
                    is_global=False,
                )
            ]
        )


async def test_production_section_classification_keeps_legacy_fail_open(monkeypatch) -> None:
    sources = _sources()
    monkeypatch.setattr(section_classifier, "get_llm_client", lambda: _FailingClient())

    await section_classifier.classify_sections(sources)

    assert sources[0].sections[0].section_kind == "spec"


async def test_pilot_section_classification_can_fail_closed(monkeypatch) -> None:
    sources = _sources()
    monkeypatch.setattr(section_classifier, "get_llm_client", lambda: _FailingClient())

    with pytest.raises(section_classifier.SectionClassificationError, match="section_classification_failed"):
        await section_classifier.classify_sections(sources, strict=True)


async def test_pilot_rejects_partial_section_classification(monkeypatch) -> None:
    sources = _sources()
    sources[0].sections.append(
        SectionExtract(
            heading="商品筛选",
            content="商品列表支持按状态筛选。",
            source_ref="prd:需求 §商品筛选",
        )
    )
    monkeypatch.setattr(section_classifier, "get_llm_client", lambda: _PartialClient())

    with pytest.raises(section_classifier.SectionClassificationError, match="InvalidClassificationCoverage"):
        await section_classifier.classify_sections(sources, strict=True)
