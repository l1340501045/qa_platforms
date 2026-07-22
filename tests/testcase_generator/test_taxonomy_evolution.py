from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest
from src.testcase_generator.services.taxonomy_evolution import (
    EvolutionNodeDraft,
    TaxonomyEvolutionDraftBatch,
    TaxonomyEvolutionModelBinding,
    TaxonomyEvolutionOperationDraft,
    TaxonomyEvolutionPolicy,
    TaxonomyEvolutionRequest,
    TaxonomyEvolutionService,
    build_llm_taxonomy_evolution_binding,
    validate_taxonomy_evolution_result_replay,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTENT_HASH = "c" * 64
ACTIVE_EXAMPLE_HASH = "a" * 64
BFC_NEGATIVE_HASH = "bfc77677" + "0" * 56


def _unit(
    statement: str,
    *,
    structural_key: str,
    title: str,
    scope_status: str = "atomic",
    content_hash: str = CONTENT_HASH,
    source_ref: str | None = None,
) -> RequirementUnit:
    source_ref = source_ref or f"prd:增量需求 §{structural_key}"
    return RequirementUnit(
        unit_id=build_requirement_unit_id(
            document_content_hash=content_hash,
            source_ref=source_ref,
            statement=statement,
        ),
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=content_hash,
        source_ref=source_ref,
        source_quote=statement,
        source_quote_hash=build_source_quote_hash(statement),
        structural_key=structural_key,
        title=title,
        statement=statement,
        observable_outcome=statement,
        scope_status=scope_status,
    )


def _active_manifest() -> TaxonomyManifest:
    return TaxonomyManifest.model_validate(
        {
            "schema_version": 2,
            "system_id": str(SYSTEM_ID),
            "version": 3,
            "change_note": "当前已激活 taxonomy。",
            "created_by": "taxonomy-owner",
            "nodes": [
                {
                    "stable_key": "product.sync",
                    "node_type": "module",
                    "display_name": "商品同步",
                    "aliases": ["巨量商品同步"],
                    "sort_order": 0,
                    "node_status": "active",
                    "definition": "从上游平台同步商品数据。",
                    "scope_note": "覆盖批量同步与状态刷新。",
                    "in_scope_examples": [
                        {
                            "text": "商品库每日从上游同步。",
                            "document_content_hash": ACTIVE_EXAMPLE_HASH,
                            "requirement_unit_id": f"ru_{'1' * 64}",
                        }
                    ],
                    "out_of_scope_examples": [],
                },
                {
                    "stable_key": "asset.filter",
                    "node_type": "module",
                    "display_name": "筛选与排序",
                    "aliases": ["条件过滤"],
                    "sort_order": 1,
                    "node_status": "active",
                    "definition": "按条件筛选列表并调整顺序。",
                    "scope_note": "覆盖筛选、重置和排序。",
                    "in_scope_examples": [
                        {
                            "text": "素材列表支持筛选和重置。",
                            "document_content_hash": ACTIVE_EXAMPLE_HASH,
                            "requirement_unit_id": f"ru_{'2' * 64}",
                        }
                    ],
                    "out_of_scope_examples": [],
                },
            ],
            "mappings": [],
        }
    )


def _policy(**overrides) -> TaxonomyEvolutionPolicy:
    payload = {
        "schema_version": 1,
        "max_context_chars": 30_000,
        "max_operations": 100,
        "fail_behavior": "draft_only",
    }
    payload.update(overrides)
    return TaxonomyEvolutionPolicy.model_validate(payload)


def _binding(propose, *, model_revision: str = "verify@1") -> TaxonomyEvolutionModelBinding:
    return TaxonomyEvolutionModelBinding(
        propose_changes=propose,
        prompt_revision="taxonomy-evolution-v1",
        model_revision=model_revision,
    )


async def _evolve(
    units: list[RequirementUnit],
    *,
    propose,
    manifest: TaxonomyManifest | None = None,
    policy: TaxonomyEvolutionPolicy | None = None,
    binding: TaxonomyEvolutionModelBinding | None = None,
):
    return await TaxonomyEvolutionService(policy=policy or _policy()).evolve(
        active_manifest=manifest or _active_manifest(),
        requirement_units=units,
        model_binding=binding or _binding(propose),
        impact_snapshot={"product.sync": {"case_count": 12, "mapping_count": 3}},
    )


async def test_existing_structural_key_replays_as_no_change_without_model() -> None:
    unit = _unit(
        "商品库每日同步商品。",
        structural_key="product.sync",
        title="商品同步",
        source_ref="prd:新版本 §9.7 商品同步",
    )
    model_calls = 0
    active = _active_manifest()
    before = active.model_dump(mode="json")

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("确定性命中不应调用模型")

    result = await _evolve([unit], propose=propose, manifest=active)

    assert model_calls == 0
    assert result.active_manifest_hash == manifest_hash(active)
    assert active.model_dump(mode="json") == before
    assert result.apply_allowed is False
    assert result.review_required is True
    assert len(result.operations) == 1
    operation = result.operations[0]
    assert operation.operation == "no_change"
    assert operation.target_stable_keys == ["product.sync"]
    assert operation.evidence[0].text == unit.source_quote
    assert operation.impact.case_count == 12
    assert operation.impact.complete is True


async def test_title_rewording_on_same_stable_key_becomes_alias_not_add() -> None:
    unit = _unit(
        "商品库按固定周期拉取上游商品。",
        structural_key="product.sync",
        title="上游商品定时刷新",
    )

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        raise AssertionError("stable key 命中不应调用模型")

    result = await _evolve([unit], propose=propose)

    assert len(result.operations) == 1
    operation = result.operations[0]
    assert operation.operation == "alias"
    assert operation.aliases_to_add == ["上游商品定时刷新"]
    assert operation.proposed_nodes == []


async def test_existing_alias_match_survives_chapter_reorder_as_no_change() -> None:
    unit = _unit(
        "调整章节后仍描述同一同步能力。",
        structural_key="renamed.chapter.key",
        title="5.9 巨量商品同步",
        source_ref="prd:重排版 §5.9",
    )

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        raise AssertionError("alias 命中不应调用模型")

    result = await _evolve([unit], propose=propose)

    assert result.operations[0].operation == "no_change"
    assert result.operations[0].target_stable_keys == ["product.sync"]


async def test_novel_requirement_produces_explicit_add_proposal_without_mutating_active() -> None:
    unit = _unit(
        "任务可在指定未来时间自动提交。",
        structural_key="task.scheduled_submit",
        title="定时提交",
    )
    active = _active_manifest()
    before_hash = manifest_hash(active)

    async def propose(request: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        assert [item.unit_id for item in request.requirement_units] == [unit.unit_id]
        return TaxonomyEvolutionDraftBatch(
            operations=[
                TaxonomyEvolutionOperationDraft(
                    operation="add",
                    proposed_nodes=[
                        EvolutionNodeDraft(
                            stable_key="task.scheduled_submit",
                            node_type="module",
                            display_name="定时提交",
                            definition="在指定未来时间自动提交任务。",
                            scope_note="覆盖定时调度，不包含立即提交。",
                            requirement_unit_ids=[unit.unit_id],
                        )
                    ],
                    requirement_unit_ids=[unit.unit_id],
                    reason="当前 taxonomy 不含任务调度能力。",
                )
            ]
        )

    result = await _evolve([unit], propose=propose, manifest=active)

    assert manifest_hash(active) == before_hash
    assert result.active_manifest_hash == before_hash
    assert result.proposal_hash is not None
    assert result.unresolved_requirement_unit_ids == []
    assert len(result.operations) == 1
    operation = result.operations[0]
    assert operation.operation == "add"
    assert operation.before_nodes == []
    assert operation.impact.complete is True
    assert operation.proposed_nodes[0].stable_key == "task.scheduled_submit"
    assert operation.evidence[0].text == unit.source_quote
    assert operation.operation_id.startswith("evo_")

    round_tripped = type(result).model_validate_json(result.model_dump_json())
    validate_taxonomy_evolution_result_replay(
        active_manifest=active,
        requirement_units=[unit],
        policy=_policy(),
        result=round_tripped,
        impact_snapshot={"product.sync": {"case_count": 12, "mapping_count": 3}},
    )
    tampered = round_tripped.model_copy(update={"input_hash": "f" * 64})
    with pytest.raises(ValueError, match="evolution_result_input_binding_mismatch"):
        validate_taxonomy_evolution_result_replay(
            active_manifest=active,
            requirement_units=[unit],
            policy=_policy(),
            result=tampered,
            impact_snapshot={"product.sync": {"case_count": 12, "mapping_count": 3}},
        )
    tampered_operation = round_tripped.operations[0].model_copy(update={"rollback": "伪造回滚说明"})
    tampered = round_tripped.model_copy(update={"operations": [tampered_operation]})
    with pytest.raises(ValueError, match="evolution_result_operation_replay_mismatch"):
        validate_taxonomy_evolution_result_replay(
            active_manifest=active,
            requirement_units=[unit],
            policy=_policy(),
            result=tampered,
            impact_snapshot={"product.sync": {"case_count": 12, "mapping_count": 3}},
        )


async def test_model_add_cannot_duplicate_existing_stable_key_or_label() -> None:
    unit = _unit("新增一种商品同步写法。", structural_key="new.product.behavior", title="商品同步增强")

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch(
            operations=[
                TaxonomyEvolutionOperationDraft(
                    operation="add",
                    proposed_nodes=[
                        EvolutionNodeDraft(
                            stable_key="product.sync",
                            node_type="capability",
                            display_name="商品同步增强",
                            definition="重复已有能力。",
                            scope_note="重复范围。",
                            requirement_unit_ids=[unit.unit_id],
                        )
                    ],
                    requirement_unit_ids=[unit.unit_id],
                    reason="模型误判为新增。",
                )
            ]
        )

    result = await _evolve([unit], propose=propose)

    assert result.operations == []
    assert result.issue_codes == ["operation_invalid"]
    assert result.unresolved_requirement_unit_ids == [unit.unit_id]


async def test_unsupported_negative_case_fact_never_reaches_evolution_model() -> None:
    hallucinated = _unit(
        "系统提供按钮单个新建商品。",
        structural_key="product.create_single",
        title="单个新建商品",
        scope_status="unsupported",
        content_hash=BFC_NEGATIVE_HASH,
    )
    model_calls = 0

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        nonlocal model_calls
        model_calls += 1
        return TaxonomyEvolutionDraftBatch()

    result = await _evolve([hallucinated], propose=propose)

    assert model_calls == 0
    assert result.operations == []
    assert result.unresolved_requirement_unit_ids == [hallucinated.unit_id]


async def test_model_failure_or_incomplete_settlement_fails_closed() -> None:
    unit = _unit("新增规则。", structural_key="new.rule", title="新增规则")

    async def failed(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        raise TimeoutError("vendor secret")

    async def incomplete(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch()

    failed_result = await _evolve([unit], propose=failed)
    incomplete_result = await _evolve([unit], propose=incomplete)

    assert failed_result.issue_codes == ["model_failed"]
    assert incomplete_result.issue_codes == ["operation_evidence_invalid"]
    assert "vendor secret" not in str(failed_result.issues)
    assert failed_result.unresolved_requirement_unit_ids == [unit.unit_id]
    assert incomplete_result.unresolved_requirement_unit_ids == [unit.unit_id]


def test_change_operation_schema_rejects_ambiguous_payloads() -> None:
    unit_id = f"ru_{'9' * 64}"

    with pytest.raises(ValidationError, match="evolution_add_target_forbidden"):
        TaxonomyEvolutionOperationDraft.model_validate(
            {
                "operation": "add",
                "target_stable_keys": ["product.sync"],
                "proposed_nodes": [
                    {
                        "stable_key": "new.node",
                        "node_type": "module",
                        "display_name": "新节点",
                        "definition": "新节点。",
                        "scope_note": "新范围。",
                        "requirement_unit_ids": [unit_id],
                    }
                ],
                "requirement_unit_ids": [unit_id],
                "reason": "不合法。",
            }
        )

    with pytest.raises(ValidationError, match="evolution_add_change_field_forbidden"):
        TaxonomyEvolutionOperationDraft.model_validate(
            {
                "operation": "add",
                "new_parent_stable_key": "product.sync",
                "proposed_nodes": [
                    {
                        "stable_key": "new.node",
                        "node_type": "module",
                        "display_name": "新节点",
                        "definition": "新节点。",
                        "scope_note": "新范围。",
                        "requirement_unit_ids": [unit_id],
                    }
                ],
                "requirement_unit_ids": [unit_id],
                "reason": "不合法。",
            }
        )


async def test_proposed_graph_cycle_is_rejected() -> None:
    unit = _unit("新增成组规则。", structural_key="new.rule.group", title="成组规则")

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch(
            operations=[
                TaxonomyEvolutionOperationDraft(
                    operation="add",
                    proposed_nodes=[
                        EvolutionNodeDraft(
                            stable_key="new.parent",
                            node_type="module",
                            display_name="新父级",
                            parent_stable_key="new.child",
                            definition="父级。",
                            scope_note="父级范围。",
                            requirement_unit_ids=[unit.unit_id],
                        ),
                        EvolutionNodeDraft(
                            stable_key="new.child",
                            node_type="module",
                            display_name="新子级",
                            parent_stable_key="new.parent",
                            definition="子级。",
                            scope_note="子级范围。",
                            requirement_unit_ids=[unit.unit_id],
                        ),
                    ],
                    requirement_unit_ids=[unit.unit_id],
                    reason="模型生成了环。",
                )
            ]
        )

    result = await _evolve([unit], propose=propose)

    assert result.operations == []
    assert result.issue_codes == ["operation_invalid"]


async def test_model_cannot_add_an_alias_already_owned_by_target() -> None:
    unit = _unit("新增同步术语。", structural_key="new.sync.wording", title="同步术语")

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch(
            operations=[
                TaxonomyEvolutionOperationDraft(
                    operation="alias",
                    target_stable_keys=["product.sync"],
                    aliases_to_add=["巨量商品同步"],
                    requirement_unit_ids=[unit.unit_id],
                    reason="该别名其实已经存在。",
                )
            ]
        )

    result = await _evolve([unit], propose=propose)

    assert result.operations == []
    assert result.issue_codes == ["operation_invalid"]


@pytest.mark.parametrize("operation_name", ["rename", "move", "split", "merge", "deprecate"])
async def test_all_structural_operation_types_materialize_as_review_only_drafts(
    operation_name: str,
) -> None:
    unit = _unit("审核 taxonomy 结构调整。", structural_key="taxonomy.change.request", title="结构调整")

    async def propose(_: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        common = {
            "operation": operation_name,
            "requirement_unit_ids": [unit.unit_id],
            "reason": "基于新需求形成待审结构变更。",
        }
        if operation_name == "rename":
            common.update(
                target_stable_keys=["product.sync"],
                new_display_name="上游商品同步",
            )
        elif operation_name == "move":
            common.update(
                target_stable_keys=["product.sync"],
                new_parent_stable_key="asset.filter",
            )
        elif operation_name == "split":
            common.update(
                target_stable_keys=["product.sync"],
                proposed_nodes=[
                    {
                        "stable_key": "product.sync.schedule",
                        "node_type": "capability",
                        "display_name": "定时商品同步",
                        "definition": "按计划同步商品。",
                        "scope_note": "覆盖定时同步。",
                        "requirement_unit_ids": [unit.unit_id],
                    },
                    {
                        "stable_key": "product.sync.manual",
                        "node_type": "capability",
                        "display_name": "手动商品同步",
                        "definition": "人工触发同步商品。",
                        "scope_note": "覆盖手动触发同步。",
                        "requirement_unit_ids": [unit.unit_id],
                    },
                ],
            )
        elif operation_name == "merge":
            common.update(
                target_stable_keys=["product.sync", "asset.filter"],
                replacement_stable_key="product.sync",
            )
        else:
            common.update(
                target_stable_keys=["asset.filter"],
                replacement_stable_key="product.sync",
            )
        return TaxonomyEvolutionDraftBatch(operations=[TaxonomyEvolutionOperationDraft.model_validate(common)])

    result = await _evolve([unit], propose=propose)

    assert result.issue_codes == []
    assert len(result.operations) == 1
    assert result.operations[0].operation == operation_name
    assert result.operations[0].before_nodes
    assert result.operations[0].rollback
    assert result.apply_allowed is False


async def test_llm_evolution_binding_uses_verify_role_and_revision_in_hash() -> None:
    calls: list[tuple[tuple, dict]] = []

    async def generate(*args, **kwargs) -> TaxonomyEvolutionDraftBatch:
        calls.append((args, kwargs))
        return TaxonomyEvolutionDraftBatch(unresolved_requirement_unit_ids=[f"ru_{'8' * 64}"])

    binding = build_llm_taxonomy_evolution_binding(generate, model_revision="verify@1")
    request = TaxonomyEvolutionRequest(active_nodes=[], requirement_units=[])
    await binding.propose_changes(request)

    assert binding.prompt_revision == "taxonomy-evolution-v1"
    assert binding.model_revision == "verify@1"
    assert calls[0][1]["model_role"] == "verify"
    assert calls[0][1]["temperature"] == 0
    assert calls[0][0][2] is TaxonomyEvolutionDraftBatch


async def test_evolution_input_hash_is_order_independent_and_model_revision_sensitive() -> None:
    first = _unit("新增规则一。", structural_key="new.rule.one", title="规则一")
    second = _unit("新增规则二。", structural_key="new.rule.two", title="规则二")

    async def unresolved(request: TaxonomyEvolutionRequest) -> TaxonomyEvolutionDraftBatch:
        return TaxonomyEvolutionDraftBatch(
            unresolved_requirement_unit_ids=[unit.unit_id for unit in request.requirement_units]
        )

    base = await _evolve([first, second], propose=unresolved)
    reordered = await _evolve([second, first], propose=unresolved)
    changed = await _evolve(
        [first, second],
        propose=unresolved,
        binding=_binding(unresolved, model_revision="verify@2"),
    )

    assert base.input_hash == reordered.input_hash
    assert base.input_hash != changed.input_hash
