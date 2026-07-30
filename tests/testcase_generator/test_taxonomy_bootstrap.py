from __future__ import annotations

from uuid import UUID

import pytest

from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.services.taxonomy_bootstrap import (
    BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
    BOOTSTRAP_PROPOSAL_PROMPT_REVISION,
    BootstrapCapabilityDraft,
    BootstrapCapabilityDraftBatch,
    BootstrapConsolidationRequest,
    BootstrapNodeDraft,
    BootstrapProposalAssignmentDraft,
    BootstrapStructureDraft,
    BootstrapStructureDraftBatch,
    BootstrapUnitBatch,
    TaxonomyBootstrapModelBinding,
    TaxonomyBootstrapPolicy,
    TaxonomyBootstrapService,
    build_llm_taxonomy_bootstrap_binding,
)

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTENT_HASH = "c" * 64
BFC_NEGATIVE_HASH = "bfc77677" + "0" * 56


def _unit(
    statement: str,
    *,
    structural_key: str,
    title: str,
    scope_status: str = "atomic",
    content_hash: str = CONTENT_HASH,
    source_quote: str | None = None,
) -> RequirementUnit:
    source_ref = f"prd:通用需求 §{structural_key}"
    quote = source_quote or statement
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
        source_quote=quote,
        source_quote_hash=build_source_quote_hash(quote),
        structural_key=structural_key,
        title=title,
        statement=statement,
        observable_outcome=statement,
        scope_status=scope_status,
    )


def _policy(**overrides) -> TaxonomyBootstrapPolicy:
    payload = {
        "schema_version": 1,
        "max_units_per_batch": 10,
        "max_batch_chars": 12_000,
        "max_consolidation_chars": 40_000,
        "max_nodes": 200,
        "fail_behavior": "draft_only",
    }
    payload.update(overrides)
    return TaxonomyBootstrapPolicy.model_validate(payload)


def _proposal_draft(unit: RequirementUnit, *, stable_key: str, display_name: str) -> BootstrapCapabilityDraft:
    return BootstrapCapabilityDraft(
        stable_key=stable_key,
        display_name=display_name,
        aliases=[],
        definition=f"负责{display_name}的业务结果。",
        scope_note=f"仅覆盖{display_name}相关需求。",
        requirement_unit_ids=[unit.unit_id],
    )


def _binding(local, consolidate) -> TaxonomyBootstrapModelBinding:
    return TaxonomyBootstrapModelBinding(
        propose_capabilities=local,
        consolidate_structure=consolidate,
        proposal_prompt_revision=BOOTSTRAP_PROPOSAL_PROMPT_REVISION,
        consolidation_prompt_revision=BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
    )


async def _bootstrap(
    units: list[RequirementUnit],
    *,
    local,
    consolidate,
    policy: TaxonomyBootstrapPolicy | None = None,
):
    return await TaxonomyBootstrapService(policy=policy or _policy()).bootstrap(
        system_id=SYSTEM_ID,
        version=1,
        change_note="从 grounded requirements 初始化通用业务分类。",
        created_by="taxonomy-test",
        requirement_units=units,
        model_binding=_binding(local, consolidate),
    )


async def test_bootstrap_builds_evidence_backed_tree_and_assignments() -> None:
    sync = _unit("商品库每天从上游平台同步商品。", structural_key="product.sync", title="商品同步")
    filtering = _unit("素材列表支持筛选和重置。", structural_key="asset.filter", title="筛选与排序")

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        drafts = {
            sync.unit_id: _proposal_draft(sync, stable_key="product.sync", display_name="商品同步"),
            filtering.unit_id: _proposal_draft(filtering, stable_key="asset.filter", display_name="筛选与排序"),
        }
        return BootstrapCapabilityDraftBatch(proposals=[drafts[unit.unit_id] for unit in batch.units])

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        by_key = {proposal.stable_key: proposal for proposal in request.proposals}
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="content-assets",
                        stable_key="content.assets",
                        node_type="module",
                        display_name="内容资产",
                        definition="管理内容生产所需的业务资产。",
                        scope_note="覆盖商品和素材资产能力。",
                        source_proposal_ids=[proposal.proposal_id for proposal in request.proposals],
                    ),
                    BootstrapNodeDraft(
                        node_key="product-sync",
                        stable_key="product.sync",
                        node_type="capability",
                        display_name="商品同步",
                        definition="从上游平台同步商品。",
                        scope_note="只覆盖同步，不包含人工单个新建。",
                        parent_node_key="content-assets",
                        source_proposal_ids=[by_key["product.sync"].proposal_id],
                    ),
                    BootstrapNodeDraft(
                        node_key="asset-filter",
                        stable_key="asset.filter",
                        node_type="capability",
                        display_name="筛选与排序",
                        definition="按条件筛选素材列表。",
                        scope_note="覆盖筛选、重置和排序。",
                        parent_node_key="content-assets",
                        source_proposal_ids=[by_key["asset.filter"].proposal_id],
                    ),
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=by_key["product.sync"].proposal_id,
                        target_node_key="product-sync",
                    ),
                    BootstrapProposalAssignmentDraft(
                        proposal_id=by_key["asset.filter"].proposal_id,
                        target_node_key="asset-filter",
                    ),
                ],
            )
        )

    result = await _bootstrap([filtering, sync], local=local, consolidate=consolidate)

    assert result.draft_manifest is not None
    assert result.draft_manifest_hash is not None
    assert result.review_required is True
    assert result.activation_allowed is False
    assert result.unresolved_requirement_unit_ids == []
    nodes = {node.stable_key: node for node in result.draft_manifest.nodes}
    assert set(nodes) == {"content.assets", "product.sync", "asset.filter"}
    assert nodes["product.sync"].parent_stable_key == "content.assets"
    assert {example.requirement_unit_id for example in nodes["content.assets"].in_scope_examples or []} == {
        sync.unit_id,
        filtering.unit_id,
    }
    assert all(node.definition and node.scope_note and node.in_scope_examples for node in nodes.values())
    assert {assignment.requirement_unit_id for assignment in result.assignments} == {
        sync.unit_id,
        filtering.unit_id,
    }


async def test_manifest_examples_preserve_grounded_quote_not_model_summary() -> None:
    unit = _unit(
        "系统应按固定周期同步商品。",
        structural_key="product.sync",
        title="商品同步",
        source_quote="商品库每日 02:00 从巨量平台拉取最新商品数据。",
    )

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[_proposal_draft(unit, stable_key="product.sync", display_name="商品同步")]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        proposal = request.proposals[0]
        assert proposal.evidence_count == 1
        assert len(proposal.evidence_excerpts) == 1
        excerpt = proposal.evidence_excerpts[0]
        assert excerpt.requirement_unit_id == unit.unit_id
        assert excerpt.text == unit.source_quote
        assert excerpt.source_quote_hash == unit.source_quote_hash
        assert excerpt.truncated is False
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="product-sync",
                        stable_key="product.sync",
                        node_type="module",
                        display_name="商品同步",
                        definition="按周期从上游同步商品。",
                        scope_note="覆盖定时拉取商品数据。",
                        source_proposal_ids=[proposal.proposal_id],
                    )
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key="product-sync",
                    )
                ],
            )
        )

    result = await _bootstrap([unit], local=local, consolidate=consolidate)

    assert result.draft_manifest is not None
    assert (result.draft_manifest.nodes[0].in_scope_examples or [])[0].text == unit.source_quote


async def test_consolidation_evidence_is_deterministically_bounded() -> None:
    units = [
        _unit(
            f"规则 {index}",
            structural_key=f"product.rule.{index}",
            title=f"规则 {index}",
            source_quote=(f"原始规则 {index}：" + "证据" * 300),
        )
        for index in range(5)
    ]

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                BootstrapCapabilityDraft(
                    stable_key="product.rules",
                    display_name="商品规则",
                    definition="负责商品规则。",
                    scope_note="仅覆盖输入规则。",
                    requirement_unit_ids=[unit.unit_id for unit in units],
                )
            ]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        proposal = request.proposals[0]
        assert proposal.evidence_count == 5
        ordered = sorted(units, key=lambda item: item.unit_id)
        assert [item.requirement_unit_id for item in proposal.evidence_excerpts] == [
            ordered[0].unit_id,
            ordered[2].unit_id,
            ordered[4].unit_id,
        ]
        for excerpt in proposal.evidence_excerpts:
            source = next(unit for unit in units if unit.unit_id == excerpt.requirement_unit_id)
            assert excerpt.text == source.source_quote[:320]
            assert excerpt.source_quote_hash == source.source_quote_hash
            assert excerpt.truncated is True
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="product-rules",
                        stable_key="product.rules",
                        node_type="module",
                        display_name="商品规则",
                        definition="负责商品规则。",
                        scope_note="仅覆盖输入规则。",
                        source_proposal_ids=[proposal.proposal_id],
                    )
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key="product-rules",
                    )
                ],
            )
        )

    result = await _bootstrap(units, local=local, consolidate=consolidate)

    assert result.draft_manifest is not None


async def test_synonymous_requirements_can_consolidate_to_one_capability() -> None:
    first = _unit("每日从巨量拉取商品。", structural_key="product.sync", title="商品同步")
    second = _unit("定时刷新上游商品库。", structural_key="upstream.product.refresh", title="上游商品刷新")

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                _proposal_draft(unit, stable_key=unit.structural_key, display_name=unit.title) for unit in batch.units
            ]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="product-sync",
                        stable_key="product.sync",
                        node_type="capability",
                        display_name="商品同步",
                        aliases=["上游商品刷新"],
                        definition="从外部平台同步并刷新商品数据。",
                        scope_note="覆盖定时拉取和状态刷新。",
                        source_proposal_ids=[proposal.proposal_id for proposal in request.proposals],
                    )
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key="product-sync",
                    )
                    for proposal in request.proposals
                ],
            )
        )

    result = await _bootstrap([first, second], local=local, consolidate=consolidate)

    assert result.draft_manifest is not None
    assert [node.stable_key for node in result.draft_manifest.nodes] == ["product.sync"]
    assert len(result.assignments) == 2
    assert {assignment.target_stable_key for assignment in result.assignments} == {"product.sync"}


async def test_bootstrap_does_not_force_a_fixed_three_level_tree() -> None:
    unit = _unit("账户支持授权给投手。", structural_key="account.authorization", title="账户授权")

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[_proposal_draft(unit, stable_key="account.authorization", display_name="账户授权")]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        proposal = request.proposals[0]
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="account-authorization",
                        stable_key="account.authorization",
                        node_type="module",
                        display_name="账户授权",
                        definition="管理账户授权关系。",
                        scope_note="覆盖授权、取消和可见性。",
                        source_proposal_ids=[proposal.proposal_id],
                    )
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key="account-authorization",
                    )
                ],
            )
        )

    result = await _bootstrap([unit], local=local, consolidate=consolidate)

    assert result.draft_manifest is not None
    assert len(result.draft_manifest.nodes) == 1
    assert result.draft_manifest.nodes[0].node_type == "module"
    assert result.draft_manifest.nodes[0].parent_stable_key is None


async def test_fabricated_or_unsettled_evidence_fails_closed() -> None:
    unit = _unit("任务支持定时提交。", structural_key="task.schedule", title="定时提交")
    unknown_id = f"ru_{'9' * 64}"
    consolidate_calls = 0

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                BootstrapCapabilityDraft(
                    stable_key="task.schedule",
                    display_name="定时提交",
                    definition="在指定时间提交任务。",
                    scope_note="覆盖未来时间调度。",
                    requirement_unit_ids=[unknown_id],
                )
            ]
        )

    async def consolidate(_) -> BootstrapStructureDraftBatch:
        nonlocal consolidate_calls
        consolidate_calls += 1
        raise AssertionError("不应调用")

    result = await _bootstrap([unit], local=local, consolidate=consolidate)

    assert result.draft_manifest is None
    assert result.issue_codes == ["proposal_evidence_invalid"]
    assert consolidate_calls == 0


async def test_invalid_number_only_display_name_becomes_issue_instead_of_exception() -> None:
    unit = _unit("任务支持定时提交。", structural_key="task.schedule", title="定时提交")

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                BootstrapCapabilityDraft(
                    stable_key="task.schedule",
                    display_name="5.4",
                    definition="在指定时间提交任务。",
                    scope_note="覆盖未来时间调度。",
                    requirement_unit_ids=[unit.unit_id],
                )
            ]
        )

    async def consolidate(_) -> BootstrapStructureDraftBatch:
        raise AssertionError("不应调用")

    result = await _bootstrap([unit], local=local, consolidate=consolidate)

    assert result.draft_manifest is None
    assert result.issue_codes == ["proposal_evidence_invalid"]


async def test_assignment_target_must_cite_the_assigned_proposal() -> None:
    first = _unit("规则一。", structural_key="rule.one", title="规则一")
    second = _unit("规则二。", structural_key="rule.two", title="规则二")

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                _proposal_draft(unit, stable_key=unit.structural_key, display_name=unit.title) for unit in batch.units
            ]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        first_proposal, second_proposal = request.proposals
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="first",
                        stable_key="rule.one",
                        node_type="module",
                        display_name="规则一",
                        definition="规则一。",
                        scope_note="规则一范围。",
                        source_proposal_ids=[first_proposal.proposal_id],
                    ),
                    BootstrapNodeDraft(
                        node_key="second",
                        stable_key="rule.two",
                        node_type="module",
                        display_name="规则二",
                        definition="规则二。",
                        scope_note="规则二范围。",
                        source_proposal_ids=[second_proposal.proposal_id],
                    ),
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=first_proposal.proposal_id,
                        target_node_key="second",
                    ),
                    BootstrapProposalAssignmentDraft(
                        proposal_id=second_proposal.proposal_id,
                        target_node_key="first",
                    ),
                ],
            )
        )

    result = await _bootstrap([first, second], local=local, consolidate=consolidate)

    assert result.draft_manifest is None
    assert result.issue_codes == ["structure_invalid"]


async def test_parent_evidence_must_cover_exactly_its_assignment_subtree() -> None:
    first = _unit("规则一。", structural_key="rule.one", title="规则一")
    second = _unit("规则二。", structural_key="rule.two", title="规则二")

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                _proposal_draft(unit, stable_key=unit.structural_key, display_name=unit.title) for unit in batch.units
            ]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        first_proposal, second_proposal = request.proposals
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="rules",
                        stable_key="rules",
                        node_type="module",
                        display_name="规则",
                        definition="规则集合。",
                        scope_note="覆盖规则一和规则二。",
                        source_proposal_ids=[first_proposal.proposal_id],
                    ),
                    BootstrapNodeDraft(
                        node_key="first",
                        stable_key="rule.one",
                        node_type="capability",
                        display_name="规则一",
                        definition="规则一。",
                        scope_note="规则一范围。",
                        parent_node_key="rules",
                        source_proposal_ids=[first_proposal.proposal_id],
                    ),
                    BootstrapNodeDraft(
                        node_key="second",
                        stable_key="rule.two",
                        node_type="capability",
                        display_name="规则二",
                        definition="规则二。",
                        scope_note="规则二范围。",
                        parent_node_key="rules",
                        source_proposal_ids=[second_proposal.proposal_id],
                    ),
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=first_proposal.proposal_id,
                        target_node_key="first",
                    ),
                    BootstrapProposalAssignmentDraft(
                        proposal_id=second_proposal.proposal_id,
                        target_node_key="second",
                    ),
                ],
            )
        )

    result = await _bootstrap([first, second], local=local, consolidate=consolidate)

    assert result.draft_manifest is None
    assert result.issue_codes == ["structure_invalid"]


async def test_unsupported_negative_case_fact_never_enters_bootstrap_prompt_or_tree() -> None:
    sync = _unit("商品库只同步巨量商品。", structural_key="product.sync", title="商品同步")
    hallucinated = _unit(
        "系统提供按钮单个新建商品。",
        structural_key="product.create_single",
        title="单个新建商品",
        scope_status="unsupported",
        content_hash=BFC_NEGATIVE_HASH,
    )
    seen_unit_ids: list[str] = []

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        seen_unit_ids.extend(unit.unit_id for unit in batch.units)
        return BootstrapCapabilityDraftBatch(
            proposals=[_proposal_draft(sync, stable_key="product.sync", display_name="商品同步")]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        proposal = request.proposals[0]
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key="product-sync",
                        stable_key="product.sync",
                        node_type="module",
                        display_name="商品同步",
                        definition="从巨量同步商品数据。",
                        scope_note="不包含单个新建商品。",
                        source_proposal_ids=[proposal.proposal_id],
                    )
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key="product-sync",
                    )
                ],
            )
        )

    result = await _bootstrap([sync, hallucinated], local=local, consolidate=consolidate)

    assert seen_unit_ids == [sync.unit_id]
    assert result.draft_manifest is not None
    assert hallucinated.unit_id in result.unresolved_requirement_unit_ids
    assert "单个新建商品" not in {node.display_name for node in result.draft_manifest.nodes}


async def test_oversized_atomic_unit_is_not_truncated_or_sent_to_model() -> None:
    unit = _unit(
        "超长规则仍是一个原子需求。",
        structural_key="large.atomic.rule",
        title="超长规则",
        source_quote="原文" * 2000,
    )
    calls = {"local": 0, "consolidate": 0}

    async def local(_: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        calls["local"] += 1
        return BootstrapCapabilityDraftBatch()

    async def consolidate(_) -> BootstrapStructureDraftBatch:
        calls["consolidate"] += 1
        return BootstrapStructureDraftBatch(structure=BootstrapStructureDraft(nodes=[], assignments=[]))

    result = await _bootstrap(
        [unit],
        local=local,
        consolidate=consolidate,
        policy=_policy(max_batch_chars=1_000),
    )

    assert result.draft_manifest is None
    assert result.issue_codes == ["unit_context_budget_exceeded"]
    assert result.unresolved_requirement_unit_ids == [unit.unit_id]
    assert calls == {"local": 0, "consolidate": 0}


async def test_llm_bootstrap_binding_uses_primary_then_verify_with_fixed_controls() -> None:
    calls: list[tuple[tuple, dict]] = []

    async def generate(*args, **kwargs):
        calls.append((args, kwargs))
        if args[2] is BootstrapCapabilityDraftBatch:
            return BootstrapCapabilityDraftBatch()
        return BootstrapStructureDraftBatch(structure=BootstrapStructureDraft(nodes=[], assignments=[]))

    binding = build_llm_taxonomy_bootstrap_binding(
        generate,
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
    )
    await binding.propose_capabilities(BootstrapUnitBatch(batch_index=1, batch_count=1, units=[]))
    await binding.consolidate_structure(BootstrapConsolidationRequest.model_construct(proposals=[]))

    assert binding.proposal_prompt_revision == "taxonomy-bootstrap-proposal-v1"
    assert binding.consolidation_prompt_revision == BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION
    assert [call[1]["model_role"] for call in calls] == ["primary", "verify"]
    assert all(call[1]["temperature"] == 0 for call in calls)


def test_bootstrap_binding_rejects_blank_or_ambiguous_revisions() -> None:
    async def noop(_):
        return None

    with pytest.raises(ValueError, match="taxonomy_bootstrap_binding_revision_required"):
        TaxonomyBootstrapModelBinding(
            propose_capabilities=noop,
            consolidate_structure=noop,
            proposal_prompt_revision=" taxonomy-bootstrap-proposal-v1 ",
            consolidation_prompt_revision=BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
            proposal_model_revision="primary@1",
            consolidation_model_revision="verify@1",
        )


async def test_bootstrap_input_hash_is_order_independent_but_model_revision_sensitive() -> None:
    first = _unit("规则一。", structural_key="rule.one", title="规则一")
    second = _unit("规则二。", structural_key="rule.two", title="规则二")

    async def local(batch: BootstrapUnitBatch) -> BootstrapCapabilityDraftBatch:
        return BootstrapCapabilityDraftBatch(
            proposals=[
                _proposal_draft(unit, stable_key=unit.structural_key, display_name=unit.title) for unit in batch.units
            ]
        )

    async def consolidate(request) -> BootstrapStructureDraftBatch:
        return BootstrapStructureDraftBatch(
            structure=BootstrapStructureDraft(
                nodes=[
                    BootstrapNodeDraft(
                        node_key=f"node-{index}",
                        stable_key=proposal.stable_key,
                        node_type="module",
                        display_name=proposal.display_name,
                        definition=proposal.definition,
                        scope_note=proposal.scope_note,
                        source_proposal_ids=[proposal.proposal_id],
                    )
                    for index, proposal in enumerate(request.proposals, start=1)
                ],
                assignments=[
                    BootstrapProposalAssignmentDraft(
                        proposal_id=proposal.proposal_id,
                        target_node_key=f"node-{index}",
                    )
                    for index, proposal in enumerate(request.proposals, start=1)
                ],
            )
        )

    base = await _bootstrap([first, second], local=local, consolidate=consolidate)
    reordered = await _bootstrap([second, first], local=local, consolidate=consolidate)
    changed_binding = TaxonomyBootstrapModelBinding(
        **{
            **_binding(local, consolidate).__dict__,
            "consolidation_model_revision": "verify@2",
        }
    )
    changed = await TaxonomyBootstrapService(policy=_policy()).bootstrap(
        system_id=SYSTEM_ID,
        version=1,
        change_note="从 grounded requirements 初始化通用业务分类。",
        created_by="taxonomy-test",
        requirement_units=[first, second],
        model_binding=changed_binding,
    )

    assert base.input_hash == reordered.input_hash
    assert base.input_hash != changed.input_hash
