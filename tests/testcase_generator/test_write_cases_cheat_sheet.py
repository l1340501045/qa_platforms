"""write_cases 接入 cheat sheet 的开关回归测试。"""

import json
from uuid import uuid4

import pytest

from src.knowledge_base.schemas.cheat_sheet import CheatSheetInjectionItem
from src.platform_api.models.enums import CheatSheetType
from src.testcase_generator.schemas.parsed_context import FeatureItem, ParsedContext, SectionExtract, SourceItem
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.write_cases import node as write_cases_node


def _parsed_context(doc_id):
    return ParsedContext(
        sources=[
            SourceItem(
                doc_id=doc_id,
                doc_type="prd",
                trust_level=1,
                title="PRD",
                sections=[
                    SectionExtract(
                        heading="IAP 链接",
                        content="IAP 与 IAA 是不同变现链路。",
                        source_ref="PRD §5.8.7",
                    )
                ],
            )
        ],
        features=[
            FeatureItem(
                id="F-001",
                name="IAP 链接配置",
                description="配置 IAP 链接时需要区分 IAA。",
                source_refs=["PRD §5.8.7"],
            )
        ],
    )


def _parsed_context_with_tech_first(tech_doc_id, prd_doc_id):
    return ParsedContext(
        sources=[
            SourceItem(
                doc_id=tech_doc_id,
                doc_type="tech_doc",
                trust_level=2,
                title="技术方案",
                sections=[
                    SectionExtract(
                        heading="技术约束",
                        content="技术实现说明",
                        source_ref="TECH §1",
                    )
                ],
            ),
            SourceItem(
                doc_id=prd_doc_id,
                doc_type="prd",
                trust_level=1,
                title="PRD",
                sections=[
                    SectionExtract(
                        heading="IAP 链接",
                        content="IAP 与 IAA 是不同变现链路。",
                        source_ref="PRD §5.8.7",
                    )
                ],
            ),
        ],
        features=[
            FeatureItem(
                id="F-001",
                name="IAP 链接配置",
                description="配置 IAP 链接时需要区分 IAA。",
                source_refs=["PRD §5.8.7"],
            )
        ],
    )


def _test_points():
    return [
        TestPointSchema(
            id="TP-001",
            feature_id="F-001",
            dimension="functional_correctness",
            description="验证 IAP 链接配置",
            priority="P0",
        )
    ]


def _fake_llm(captured):
    class FakeLLM:
        async def generate_structured(self, *, system_prompt, user_content, output_schema, **kwargs):
            captured["system_prompt"] = system_prompt
            captured["user_content"] = user_content
            return write_cases_node.WriteCasesLLMOutput(
                test_cases=[
                    write_cases_node.LLMGeneratedCase(
                        test_point_id="TP-001",
                        title="验证 IAP 链接配置",
                        preconditions=["已登录"],
                        steps=[
                            write_cases_node.LLMTestStep(
                                step_number=1,
                                action="选择 IAP 链接",
                                input_data="IAP",
                                expected_result="保存成功",
                                source_quote="IAP 与 IAA 是不同变现链路。",
                                source_ref="PRD §5.8.7",
                            )
                        ],
                        expected_results=["保存成功"],
                        priority="P0",
                        dimensions=["functional_correctness"],
                    )
                ]
            )

    return FakeLLM()


def _patch_common(monkeypatch, captured):
    async def fake_retrieve_samples(self, system_id, feature_types):
        return []

    monkeypatch.setattr(write_cases_node.FewShotRetriever, "retrieve_samples", fake_retrieve_samples)
    monkeypatch.setattr(write_cases_node, "get_llm_client", lambda: _fake_llm(captured))


@pytest.mark.asyncio
async def test_generate_cases_injects_approved_cheat_sheet_when_enabled(monkeypatch):
    """开关开：user_content 含 feature 过滤后的 approved cheat_sheet，system prompt 含应用铁律。"""
    doc_id = uuid4()
    captured = {}
    approved = {
        CheatSheetType.CONFUSION_PAIR: [
            CheatSheetInjectionItem(
                id=uuid4(),
                sheet_type=CheatSheetType.CONFUSION_PAIR,
                title="易混：IAP vs IAA",
                content={"item_a": "IAP", "item_b": "IAA", "distinction": "两种变现链路互斥"},
            )
        ]
    }

    class FakeRepo:
        async def get_approved_for_injection(self, document_id):
            assert document_id == doc_id
            return approved

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(write_cases_node.settings, "cheat_sheet_injection_enabled", True)
    monkeypatch.setattr(write_cases_node, "async_session_factory", lambda: FakeSessionContext(), raising=False)
    monkeypatch.setattr(write_cases_node, "CheatSheetRepository", lambda session: FakeRepo(), raising=False)
    _patch_common(monkeypatch, captured)

    await write_cases_node.generate_cases(_parsed_context(doc_id), _test_points(), uuid4())

    payload = json.loads(captured["user_content"])
    assert payload["cheat_sheet"]["confusion_pair"][0]["title"] == "易混：IAP vs IAA"
    assert "如何应用 cheat sheet" in captured["system_prompt"]


@pytest.mark.asyncio
async def test_generate_cases_loads_cheat_sheet_from_prd_source_when_tech_doc_first(monkeypatch):
    """多 source 时优先用 PRD 文档加载 cheat sheet，不误取第一个技术文档。"""
    tech_doc_id = uuid4()
    prd_doc_id = uuid4()
    captured = {}
    seen = {}

    class FakeRepo:
        async def get_approved_for_injection(self, document_id):
            seen["document_id"] = document_id
            return {}

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(write_cases_node.settings, "cheat_sheet_injection_enabled", True)
    monkeypatch.setattr(write_cases_node, "async_session_factory", lambda: FakeSessionContext(), raising=False)
    monkeypatch.setattr(write_cases_node, "CheatSheetRepository", lambda session: FakeRepo(), raising=False)
    _patch_common(monkeypatch, captured)

    await write_cases_node.generate_cases(
        _parsed_context_with_tech_first(tech_doc_id, prd_doc_id),
        _test_points(),
        uuid4(),
    )

    payload = json.loads(captured["user_content"])
    assert payload["cheat_sheet"] == {}
    assert seen["document_id"] == prd_doc_id


@pytest.mark.asyncio
async def test_generate_cases_keeps_original_payload_when_disabled(monkeypatch):
    """开关关：user_content 不出现 cheat_sheet，system prompt 不追加铁律。"""
    captured = {}
    monkeypatch.setattr(write_cases_node.settings, "cheat_sheet_injection_enabled", False)
    _patch_common(monkeypatch, captured)

    await write_cases_node.generate_cases(_parsed_context(uuid4()), _test_points(), uuid4())

    payload = json.loads(captured["user_content"])
    assert set(payload.keys()) == {"test_points", "requirement_context"}
    assert "如何应用 cheat sheet" not in captured["system_prompt"]
