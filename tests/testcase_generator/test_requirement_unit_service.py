from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest

from src.testcase_generator.schemas.parsed_context import SectionExtract
from src.testcase_generator.services.requirement_unit_service import (
    REQUIREMENT_UNIT_PROMPT_REVISION,
    DocumentSnapshotMismatchError,
    RequirementExtractionChunk,
    RequirementUnitDraft,
    RequirementUnitDraftBatch,
    RequirementUnitService,
    build_llm_requirement_unit_extractor,
    build_requirement_chunks,
)

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PROMPT_REVISION = "requirement-unit-v1"
MODEL_REVISION = "fake-model@1"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _section(
    content: str,
    *,
    source_ref: str = "prd:商品管理 §3.2 商品同步",
    section_kind: str = "spec",
) -> SectionExtract:
    return SectionExtract(
        heading="商品同步",
        content=content,
        source_ref=source_ref,
        section_kind=section_kind,
    )


def _draft(
    *,
    quote: str,
    statement: str,
    outcome: str,
    structural_key: str,
    scope_status: str = "atomic",
) -> RequirementUnitDraft:
    return RequirementUnitDraft.model_validate(
        {
            "source_quote": quote,
            "structural_key": structural_key,
            "title": statement,
            "statement": statement,
            "observable_outcome": outcome,
            "scope_status": scope_status,
        }
    )


def _extractor(
    factory: Callable[[RequirementExtractionChunk], list[RequirementUnitDraft]],
) -> Callable[[RequirementExtractionChunk], Awaitable[RequirementUnitDraftBatch]]:
    async def extract(chunk: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        return RequirementUnitDraftBatch(units=factory(chunk))

    return extract


async def test_service_rejects_document_snapshot_hash_mismatch_before_extraction() -> None:
    called = False

    async def extractor(_: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        nonlocal called
        called = True
        return RequirementUnitDraftBatch(units=[])

    with pytest.raises(DocumentSnapshotMismatchError, match="document_snapshot_hash_mismatch"):
        await RequirementUnitService().extract(
            system_id=SYSTEM_ID,
            document_id=DOCUMENT_ID,
            document_content_hash="0" * 64,
            document_snapshot="真实文档",
            sections=[_section("真实文档")],
            extractor=extractor,
            prompt_revision=PROMPT_REVISION,
            model_revision=MODEL_REVISION,
        )

    assert called is False


async def test_service_splits_multi_capability_section_into_independent_grounded_units() -> None:
    first_quote = "商品库数据由巨量平台定时同步。"
    second_quote = "商品下架后，列表展示下架状态。"
    snapshot = f"# 商品管理\n\n{first_quote}\n\n{second_quote}"

    result = await RequirementUnitService().extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(f"{first_quote}\n\n{second_quote}")],
        extractor=_extractor(
            lambda _: [
                _draft(
                    quote=first_quote,
                    statement="商品库从巨量平台同步数据。",
                    outcome="同步完成后商品库展示巨量平台数据。",
                    structural_key="product.sync",
                ),
                _draft(
                    quote=second_quote,
                    statement="商品下架状态需要在列表中展示。",
                    outcome="下架商品在列表中显示下架状态。",
                    structural_key="product.offline-status",
                ),
            ]
        ),
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert [unit.structural_key for unit in result.units] == ["product.offline-status", "product.sync"]
    assert all(unit.scope_status == "atomic" for unit in result.units)
    assert all(unit.source_ref == "prd:商品管理 §3.2 商品同步" for unit in result.units)
    assert result.issues == []


async def test_service_marks_case_only_fact_unsupported_when_quote_is_not_in_prd() -> None:
    snapshot = "# 商品管理\n\n商品库数据由巨量平台同步。"
    hallucinated_case_fact = "点击单个新建商品按钮后创建成功。"

    result = await RequirementUnitService().extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section("商品库数据由巨量平台同步。")],
        extractor=_extractor(
            lambda _: [
                _draft(
                    quote=hallucinated_case_fact,
                    statement="系统支持单个新建商品。",
                    outcome="新商品创建成功。",
                    structural_key="product.create",
                )
            ]
        ),
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert len(result.units) == 1
    assert result.units[0].scope_status == "unsupported"
    assert result.units[0].statement == "系统支持单个新建商品。"
    assert [issue.code for issue in result.issues] == ["source_quote_not_grounded"]


async def test_service_keeps_unsplittable_wide_requirement_wide() -> None:
    quote = "提交任务时同时校验账户、素材、商品、预算和排期，任一失败则阻止提交。"
    snapshot = f"# 任务提交\n\n{quote}"

    result = await RequirementUnitService().extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(quote, source_ref="prd:任务 §5.1 提交")],
        extractor=_extractor(
            lambda _: [
                _draft(
                    quote=quote,
                    statement="任务提交包含多个不可独立确认的联合校验。",
                    outcome="任一联合校验失败时任务不提交。",
                    structural_key="task.submit-validation",
                    scope_status="wide",
                )
            ]
        ),
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert len(result.units) == 1
    assert result.units[0].scope_status == "wide"
    assert not any(issue.code == "forced_first_classification" for issue in result.issues)


async def test_overlap_duplicates_are_deduplicated_by_stable_unit_id() -> None:
    quote = "筛选条件支持重置。"
    padding = "前置说明。" * 30
    snapshot = f"{padding}{quote}{padding}"
    section = _section(snapshot)

    result = await RequirementUnitService(max_chunk_chars=120, chunk_overlap_chars=60).extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[section],
        extractor=_extractor(
            lambda chunk: (
                [
                    _draft(
                        quote=quote,
                        statement="筛选条件可以重置。",
                        outcome="重置后所有筛选条件恢复为空。",
                        structural_key="filter.reset",
                    )
                ]
                if quote in chunk.content
                else []
            )
        ),
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert len(result.units) == 1
    assert result.issues == []


async def test_conflicting_duplicate_payloads_fail_closed_instead_of_keeping_first() -> None:
    quote = "列表默认按创建时间降序排列。"
    padding = "背景说明。" * 30
    snapshot = f"{padding}{quote}{padding}"
    calls = 0

    async def extractor(chunk: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        nonlocal calls
        if quote not in chunk.content:
            return RequirementUnitDraftBatch(units=[])
        calls += 1
        outcome = "最新数据排在最前。" if calls == 1 else "最早数据排在最前。"
        return RequirementUnitDraftBatch(
            units=[
                _draft(
                    quote=quote,
                    statement="列表默认按创建时间降序排列。",
                    outcome=outcome,
                    structural_key="list.default-sort",
                )
            ]
        )

    result = await RequirementUnitService(max_chunk_chars=120, chunk_overlap_chars=60).extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(snapshot)],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert calls >= 2
    assert result.units == []
    assert [issue.code for issue in result.issues] == ["duplicate_unit_payload_conflict"]


def test_long_section_chunking_never_drops_middle_constraints_or_source_anchor() -> None:
    key_constraint = "单次 Excel 上传不得超过 1000 行。"
    content = f"{'头部说明。' * 80}\n{key_constraint}\n{'尾部说明。' * 80}"
    section = _section(content, source_ref="prd:导入 §8.3 Excel 上传")

    chunks = build_requirement_chunks(section, max_chars=160, overlap_chars=40)

    assert len(chunks) > 2
    assert all(len(chunk.content) <= 160 for chunk in chunks)
    assert all(chunk.source_ref == "prd:导入 §8.3 Excel 上传" for chunk in chunks)
    assert any(key_constraint in chunk.content for chunk in chunks)
    assert chunks[0].content.startswith("头部说明。")
    assert chunks[-1].content.endswith("尾部说明。")


async def test_extractor_failure_is_recorded_and_other_chunks_continue() -> None:
    first = "第一段规则：筛选条件支持重置。"
    second = "第二段规则：列表支持按时间排序。"
    snapshot = f"{first}{'填充。' * 50}{second}"

    async def extractor(chunk: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        if first in chunk.content:
            raise TimeoutError("gateway timeout")
        if second in chunk.content:
            return RequirementUnitDraftBatch(
                units=[
                    _draft(
                        quote=second,
                        statement="列表支持按时间排序。",
                        outcome="列表顺序按所选时间方向变化。",
                        structural_key="list.sort",
                    )
                ]
            )
        return RequirementUnitDraftBatch(units=[])

    result = await RequirementUnitService(max_chunk_chars=120, chunk_overlap_chars=20).extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(snapshot)],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert [unit.structural_key for unit in result.units] == ["list.sort"]
    assert any(issue.code == "extractor_failed" for issue in result.issues)


async def test_non_spec_section_is_excluded_from_induction_input() -> None:
    called = False
    snapshot = "# 后续规划\n\n二期支持自动创建商品。"

    async def extractor(_: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        nonlocal called
        called = True
        return RequirementUnitDraftBatch(units=[])

    result = await RequirementUnitService().extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section("二期支持自动创建商品。", section_kind="future")],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert called is False
    assert result.units == []
    assert [issue.code for issue in result.issues] == ["section_not_induction_eligible"]


def test_chunking_does_not_emit_a_redundant_tiny_tail_window() -> None:
    content = "A" * 181

    chunks = build_requirement_chunks(_section(content), max_chars=120, overlap_chars=60)

    assert [len(chunk.content) for chunk in chunks] == [120, 120]
    assert all(chunk.content_hash == _content_hash(chunk.content) for chunk in chunks)


async def test_invalid_extractor_output_is_recorded_as_failure() -> None:
    snapshot = "筛选条件支持重置。"

    async def extractor(_: RequirementExtractionChunk):
        return {"unexpected": True}

    result = await RequirementUnitService().extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(snapshot)],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert result.units == []
    assert [issue.code for issue in result.issues] == ["extractor_failed"]


async def test_duplicate_units_with_title_only_variation_are_not_false_conflicts() -> None:
    quote = "筛选条件支持重置。"
    padding = "背景说明。" * 30
    snapshot = f"{padding}{quote}{padding}"
    calls = 0

    async def extractor(chunk: RequirementExtractionChunk) -> RequirementUnitDraftBatch:
        nonlocal calls
        if quote not in chunk.content:
            return RequirementUnitDraftBatch(units=[])
        calls += 1
        title = "重置筛选" if calls == 1 else "筛选条件重置"
        draft = _draft(
            quote=quote,
            statement="筛选条件可以重置。",
            outcome="重置后所有筛选条件恢复为空。",
            structural_key="filter.reset",
        )
        return RequirementUnitDraftBatch(units=[draft.model_copy(update={"title": title})])

    result = await RequirementUnitService(max_chunk_chars=120, chunk_overlap_chars=60).extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[_section(snapshot)],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert calls >= 2
    assert len(result.units) == 1
    assert result.units[0].title == "筛选条件重置"
    assert result.issues == []


async def test_result_identity_records_prompt_model_and_is_stable_under_section_order() -> None:
    first = _section("筛选条件支持重置。", source_ref="prd:列表 §1 筛选")
    second = _section("列表支持按时间排序。", source_ref="prd:列表 §2 排序")
    snapshot = f"{first.content}\n{second.content}"
    extractor = _extractor(lambda _: [])
    service = RequirementUnitService()

    one = await service.extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[first, second],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )
    two = await service.extract(
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=_content_hash(snapshot),
        document_snapshot=snapshot,
        sections=[second, first],
        extractor=extractor,
        prompt_revision=PROMPT_REVISION,
        model_revision=MODEL_REVISION,
    )

    assert one.prompt_revision == PROMPT_REVISION
    assert one.model_revision == MODEL_REVISION
    assert one.input_hash == two.input_hash


async def test_llm_extractor_adapter_sends_only_current_chunk_with_fixed_revision() -> None:
    captured: dict = {}
    expected = RequirementUnitDraftBatch(
        units=[
            _draft(
                quote="筛选条件支持重置。",
                statement="筛选条件可以重置。",
                outcome="重置后筛选条件为空。",
                structural_key="filter.reset",
            )
        ]
    )

    async def generate_structured(system_prompt, user_content, output_schema, **kwargs):
        captured.update(
            {
                "system_prompt": system_prompt,
                "user_content": user_content,
                "output_schema": output_schema,
                **kwargs,
            }
        )
        return expected

    binding = build_llm_requirement_unit_extractor(
        generate_structured,
        model_revision="primary-model@config-7",
    )
    chunk = build_requirement_chunks(_section("筛选条件支持重置。"))[0]

    actual = await binding.extractor(chunk)

    assert actual == expected
    assert binding.prompt_revision == REQUIREMENT_UNIT_PROMPT_REVISION
    assert binding.model_revision == "primary-model@config-7"
    assert captured["output_schema"] is RequirementUnitDraftBatch
    assert captured["temperature"] == 0
    assert captured["model_role"] == "primary"
    assert "筛选条件支持重置。" in captured["user_content"]
    assert "只引用当前输入中的原文" in captured["system_prompt"]
    assert "test_case" not in captured["user_content"]
