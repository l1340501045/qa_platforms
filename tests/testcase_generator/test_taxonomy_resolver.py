from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.schemas.taxonomy_resolution import (
    TaxonomyCandidate,
    TaxonomyResolutionPolicy,
)
from src.testcase_generator.services.taxonomy_candidate_retriever import (
    TaxonomyCandidateRetriever,
    TaxonomyCandidateSourceBinding,
    TaxonomySearchConcept,
)
from src.testcase_generator.services.taxonomy_resolver import (
    ApprovedTaxonomyMatch,
    TaxonomyDeciderBinding,
    TaxonomyDecisionDraft,
    TaxonomyDecisionDraftBatch,
    TaxonomyDecisionRequest,
    TaxonomyResolver,
    build_llm_taxonomy_decider,
)

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TAXONOMY_VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")
SYNC_CONCEPT_ID = UUID("22222222-2222-2222-2222-222222222222")
FILTER_CONCEPT_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_CONCEPT_ID = UUID("44444444-4444-4444-4444-444444444444")
MAPPING_ID = UUID("55555555-5555-5555-5555-555555555555")
CONTENT_HASH = "c" * 64
MANIFEST_HASH = "d" * 64
INDEX_HASH = "e" * 64


def _policy(*, model_revision: str = "resolver@1", **overrides) -> TaxonomyResolutionPolicy:
    payload = {
        "schema_version": 1,
        "top_k": 3,
        "minimum_score": 0.8,
        "minimum_margin": 0.1,
        "out_of_scope_conflict_score": 0.9,
        "decision_context_max_chars": 24_000,
        "require_grounding": True,
        "allowed_node_types": ["module", "capability"],
        "allowed_node_statuses": ["active"],
        "model_role": "taxonomy_resolver",
        "model_revision": model_revision,
        "fail_behavior": "abstain",
        "auto_accept_signal": "retrieval_score_margin",
    }
    payload.update(overrides)
    return TaxonomyResolutionPolicy.model_validate(payload)


def _unit(scope_status: str = "atomic") -> RequirementUnit:
    statement = "商品库每天从巨量平台同步商品数据。"
    source_ref = "prd:商品管理 §5.4"
    return RequirementUnit(
        unit_id=build_requirement_unit_id(
            document_content_hash=CONTENT_HASH,
            source_ref=source_ref,
            statement=statement,
        ),
        system_id=SYSTEM_ID,
        document_id=DOCUMENT_ID,
        document_content_hash=CONTENT_HASH,
        source_ref=source_ref,
        source_quote=statement,
        source_quote_hash=build_source_quote_hash(statement),
        structural_key="product.sync",
        title="商品同步",
        statement=statement,
        observable_outcome="本地商品库更新为巨量平台最新数据。",
        scope_status=scope_status,
    )


def _concepts() -> list[TaxonomySearchConcept]:
    return [
        TaxonomySearchConcept.model_validate(
            {
                "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
                "concept_id": str(SYNC_CONCEPT_ID),
                "stable_key": "product.sync",
                "node_type": "capability",
                "node_status": "active",
                "display_name": "商品同步",
                "aliases": ["巨量商品同步"],
                "definition": "从巨量平台拉取商品数据并更新本地商品库。",
                "scope_note": "覆盖批量同步与商品状态更新。",
                "in_scope_examples": [
                    {
                        "text": "商品库每天从巨量平台同步。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'1' * 64}",
                    }
                ],
                "out_of_scope_examples": [
                    {
                        "text": "点击按钮单个新建商品。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'2' * 64}",
                    }
                ],
            }
        ),
        TaxonomySearchConcept.model_validate(
            {
                "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
                "concept_id": str(FILTER_CONCEPT_ID),
                "stable_key": "asset.filter",
                "node_type": "capability",
                "node_status": "active",
                "display_name": "筛选与排序",
                "aliases": ["条件过滤"],
                "definition": "按条件过滤列表并调整顺序。",
                "scope_note": "覆盖筛选、重置和排序。",
                "in_scope_examples": [
                    {
                        "text": "素材列表支持重置筛选条件。",
                        "document_content_hash": CONTENT_HASH,
                        "requirement_unit_id": f"ru_{'3' * 64}",
                    }
                ],
                "out_of_scope_examples": [],
            }
        ),
    ]


def _candidate(
    concept_id: UUID,
    stable_key: str,
    score: float,
    rank: int,
    *,
    conflict: bool = False,
    taxonomy_version_id: UUID = TAXONOMY_VERSION_ID,
) -> TaxonomyCandidate:
    return TaxonomyCandidate(
        taxonomy_version_id=taxonomy_version_id,
        concept_id=concept_id,
        stable_key=stable_key,
        score=score,
        rank=rank,
        evidence=["embedding_similarity"],
        scope_conflict=conflict,
        scope_conflict_evidence=([f"negative_example:ru_{'9' * 64}"] if conflict else []),
    )


def _candidates(
    *,
    first_score: float = 0.95,
    second_score: float = 0.70,
    conflict: bool = False,
) -> list[TaxonomyCandidate]:
    return [
        _candidate(SYNC_CONCEPT_ID, "product.sync", first_score, 1, conflict=conflict),
        _candidate(FILTER_CONCEPT_ID, "asset.filter", second_score, 2),
    ]


def _decision(
    decision: str = "accept",
    *,
    selected: UUID | None = SYNC_CONCEPT_ID,
    related: list[UUID] | None = None,
) -> TaxonomyDecisionDraft:
    return TaxonomyDecisionDraft.model_validate(
        {
            "decision": decision,
            "selected_concept_id": str(selected) if selected else None,
            "related_concept_ids": [str(item) for item in (related or [])],
            "reason_code": f"model_{decision}",
            "reason": "候选定义与需求证据一致。",
        }
    )


def _resolver(
    *,
    candidates: list[TaxonomyCandidate] | None = None,
    decision: TaxonomyDecisionDraft | Exception | None = None,
    calls: dict[str, int] | None = None,
    model_revision: str = "resolver@1",
    policy: TaxonomyResolutionPolicy | None = None,
) -> TaxonomyResolver:
    calls = calls if calls is not None else {"retrieve": 0, "decide": 0}
    source_policy = policy or _policy(model_revision=model_revision)

    async def retrieve(_: RequirementUnit) -> list[TaxonomyCandidate]:
        calls["retrieve"] += 1
        return list(candidates if candidates is not None else _candidates())

    async def decide(_: TaxonomyDecisionRequest) -> object:
        calls["decide"] += 1
        if isinstance(decision, Exception):
            raise decision
        return TaxonomyDecisionDraftBatch(
            result=decision if decision is not None else _decision(),
        )

    return TaxonomyResolver(
        candidate_source=TaxonomyCandidateSourceBinding(
            retrieve_candidates=retrieve,
            taxonomy_version_id=TAXONOMY_VERSION_ID,
            taxonomy_manifest_hash=MANIFEST_HASH,
            policy_version=source_policy.canonical_hash,
            candidate_index_hash=INDEX_HASH,
        ),
        decider_binding=TaxonomyDeciderBinding(
            decide=decide,
            prompt_revision="taxonomy-resolver-v1",
            model_revision=model_revision,
        ),
    )


async def _resolve(
    resolver: TaxonomyResolver,
    *,
    unit: RequirementUnit | None = None,
    policy: TaxonomyResolutionPolicy | None = None,
    approved_match: ApprovedTaxonomyMatch | None = None,
    concepts: list[TaxonomySearchConcept] | None = None,
):
    return await resolver.resolve(
        unit or _unit(),
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=concepts or _concepts(),
        policy=policy or _policy(),
        approved_match=approved_match,
    )


async def test_approved_exact_mapping_bypasses_retrieval_and_model() -> None:
    calls = {"retrieve": 0, "decide": 0}
    unit = _unit()
    approved = ApprovedTaxonomyMatch(
        mapping_id=MAPPING_ID,
        requirement_unit_id=unit.unit_id,
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=SYNC_CONCEPT_ID,
        reason="人工校准确认。",
    )

    result = await _resolve(
        _resolver(calls=calls),
        unit=unit,
        approved_match=approved,
    )

    assert result.status == "mapped"
    assert result.method == "approved_mapping"
    assert result.primary_concept_id == SYNC_CONCEPT_ID
    assert result.confidence == 1.0
    assert result.candidates == []
    assert calls == {"retrieve": 0, "decide": 0}


async def test_approved_mapping_hash_ignores_unused_candidate_and_model_bindings() -> None:
    unit = _unit()
    approved = ApprovedTaxonomyMatch(
        mapping_id=MAPPING_ID,
        requirement_unit_id=unit.unit_id,
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=SYNC_CONCEPT_ID,
        reason="人工校准确认。",
    )
    first = await _resolve(_resolver(), unit=unit, approved_match=approved)
    changed_runtime = _resolver(model_revision="resolver@2")
    assert changed_runtime.candidate_source is not None
    changed_runtime.candidate_source = TaxonomyCandidateSourceBinding(
        retrieve_candidates=changed_runtime.candidate_source.retrieve_candidates,
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        policy_version=_policy(model_revision="resolver@2").canonical_hash,
        candidate_index_hash="f" * 64,
    )

    replay = await _resolve(changed_runtime, unit=unit, approved_match=approved)

    assert first.input_hash == replay.input_hash


async def test_invalid_approved_mapping_fails_closed_without_fallback() -> None:
    calls = {"retrieve": 0, "decide": 0}
    unit = _unit()
    approved = ApprovedTaxonomyMatch(
        mapping_id=MAPPING_ID,
        requirement_unit_id=unit.unit_id,
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=OTHER_CONCEPT_ID,
        reason="指向不在当前 active manifest 的概念。",
    )

    result = await _resolve(_resolver(calls=calls), unit=unit, approved_match=approved)

    assert result.status == "unresolved"
    assert result.unresolved_kind == "conflicted"
    assert result.reason_code == "approved_mapping_invalid"
    assert calls == {"retrieve": 0, "decide": 0}


@pytest.mark.parametrize(
    ("scope_status", "unresolved_kind", "reason_code"),
    [
        ("unsupported", "unsupported", "requirement_unsupported"),
        ("conflicted", "conflicted", "requirement_conflicted"),
        ("wide", "abstained", "requirement_scope_wide"),
    ],
)
async def test_non_atomic_requirements_short_circuit(
    scope_status: str,
    unresolved_kind: str,
    reason_code: str,
) -> None:
    calls = {"retrieve": 0, "decide": 0}

    result = await _resolve(_resolver(calls=calls), unit=_unit(scope_status))

    assert result.status == "unresolved"
    assert result.unresolved_kind == unresolved_kind
    assert result.reason_code == reason_code
    assert calls == {"retrieve": 0, "decide": 0}


async def test_high_score_margin_and_rank_one_accept_maps_with_derived_metrics() -> None:
    captured: list[TaxonomyDecisionRequest] = []

    async def retrieve(_: RequirementUnit) -> list[TaxonomyCandidate]:
        return _candidates()

    async def decide(request: TaxonomyDecisionRequest) -> TaxonomyDecisionDraftBatch:
        captured.append(request)
        return TaxonomyDecisionDraftBatch(result=_decision())

    resolver = TaxonomyResolver(
        candidate_source=TaxonomyCandidateSourceBinding(
            retrieve_candidates=retrieve,
            taxonomy_version_id=TAXONOMY_VERSION_ID,
            taxonomy_manifest_hash=MANIFEST_HASH,
            policy_version=_policy().canonical_hash,
            candidate_index_hash=INDEX_HASH,
        ),
        decider_binding=TaxonomyDeciderBinding(
            decide=decide,
            prompt_revision="taxonomy-resolver-v1",
            model_revision="resolver@1",
        ),
    )

    result = await _resolve(resolver)

    assert result.status == "mapped"
    assert result.method == "policy_auto"
    assert result.primary_concept_id == SYNC_CONCEPT_ID
    assert result.confidence == pytest.approx(0.95)
    assert result.margin == pytest.approx(0.25)
    assert result.model_revision == "resolver@1"
    assert [item.candidate.concept_id for item in captured[0].candidates] == [
        SYNC_CONCEPT_ID,
        FILTER_CONCEPT_ID,
    ]
    assert captured[0].candidates[0].definition.startswith("从巨量平台")
    assert captured[0].candidates[0].out_of_scope_examples == ["点击按钮单个新建商品。"]


@pytest.mark.parametrize(
    ("candidates", "unresolved_kind", "reason_code"),
    [
        ([], "novel", "no_existing_candidate"),
        (_candidates(first_score=0.79, second_score=0.50), "novel", "candidate_score_below_policy"),
        (_candidates(first_score=0.91, second_score=0.86), "abstained", "candidate_margin_below_policy"),
        (_candidates(conflict=True), "abstained", "candidate_scope_conflict"),
    ],
)
async def test_deterministic_gates_run_before_model(
    candidates: list[TaxonomyCandidate],
    unresolved_kind: str,
    reason_code: str,
) -> None:
    calls = {"retrieve": 0, "decide": 0}

    result = await _resolve(_resolver(candidates=candidates, calls=calls))

    assert result.status == "unresolved"
    assert result.unresolved_kind == unresolved_kind
    assert result.reason_code == reason_code
    assert calls["retrieve"] == 1
    assert calls["decide"] == 0


async def test_retrieval_or_model_failure_is_abstained_without_vendor_detail() -> None:
    async def failed_retrieval(_: RequirementUnit) -> list[TaxonomyCandidate]:
        raise TimeoutError("gateway secret")

    retrieval_result = await _resolve(
        TaxonomyResolver(
            candidate_source=TaxonomyCandidateSourceBinding(
                retrieve_candidates=failed_retrieval,
                taxonomy_version_id=TAXONOMY_VERSION_ID,
                taxonomy_manifest_hash=MANIFEST_HASH,
                policy_version=_policy().canonical_hash,
                candidate_index_hash=INDEX_HASH,
            ),
            decider_binding=TaxonomyDeciderBinding(
                decide=lambda _: None,  # type: ignore[arg-type]
                prompt_revision="taxonomy-resolver-v1",
                model_revision="resolver@1",
            ),
        )
    )
    model_result = await _resolve(_resolver(decision=TimeoutError("gateway secret")))

    assert retrieval_result.unresolved_kind == "abstained"
    assert retrieval_result.reason_code == "candidate_retrieval_failed"
    assert model_result.unresolved_kind == "abstained"
    assert model_result.reason_code == "resolver_model_failed"
    assert "gateway secret" not in retrieval_result.reason
    assert "gateway secret" not in model_result.reason


@pytest.mark.parametrize(
    ("decision", "reason_code"),
    [
        (_decision(selected=OTHER_CONCEPT_ID), "resolver_selection_outside_candidates"),
        (_decision(selected=FILTER_CONCEPT_ID), "resolver_selection_not_rank_one"),
        (
            _decision(related=[FILTER_CONCEPT_ID]),
            "resolver_related_requires_multiple_units",
        ),
    ],
)
async def test_model_cannot_escape_candidate_and_atomicity_constraints(
    decision: TaxonomyDecisionDraft,
    reason_code: str,
) -> None:
    result = await _resolve(_resolver(decision=decision))

    assert result.status == "unresolved"
    assert result.unresolved_kind == "abstained"
    assert result.reason_code == reason_code


async def test_model_can_explicitly_mark_grounded_requirement_novel() -> None:
    result = await _resolve(_resolver(decision=_decision("novel", selected=None)))

    assert result.status == "unresolved"
    assert result.unresolved_kind == "novel"
    assert result.reason_code == "model_novel"


async def test_oversized_decision_context_abstains_before_model_call() -> None:
    calls = {"retrieve": 0, "decide": 0}
    concepts = _concepts()
    concepts[0] = concepts[0].model_copy(update={"definition": "超长定义" * 3000})
    policy = _policy(decision_context_max_chars=5_000)

    result = await _resolve(
        _resolver(calls=calls, policy=policy),
        concepts=concepts,
        policy=policy,
    )

    assert result.status == "unresolved"
    assert result.unresolved_kind == "abstained"
    assert result.reason_code == "resolver_context_budget_exceeded"
    assert calls == {"retrieve": 1, "decide": 0}


def test_model_decision_schema_has_no_self_reported_confidence() -> None:
    payload = _decision().model_dump(mode="json")
    payload["confidence"] = 0.99

    with pytest.raises(ValidationError, match="extra_forbidden"):
        TaxonomyDecisionDraft.model_validate(payload)


async def test_resolution_hash_is_stable_and_changes_with_bound_model_revision() -> None:
    first = await _resolve(_resolver())
    replay = await _resolve(_resolver())
    changed = await _resolve(
        _resolver(model_revision="resolver@2"),
        policy=_policy(model_revision="resolver@2"),
    )

    assert first.input_hash == replay.input_hash
    assert first.input_hash != changed.input_hash


async def test_llm_adapter_sends_only_bounded_request_with_fixed_runtime_controls() -> None:
    calls: list[tuple[tuple, dict]] = []

    async def generate(*args, **kwargs) -> TaxonomyDecisionDraftBatch:
        calls.append((args, kwargs))
        return TaxonomyDecisionDraftBatch(result=_decision())

    binding = build_llm_taxonomy_decider(generate, model_revision="resolver@1")
    request = TaxonomyDecisionRequest(
        requirement_unit=_unit(),
        candidates=[],
    )

    result = await binding.decide(request)

    assert result.result.decision == "accept"
    assert binding.prompt_revision == "taxonomy-resolver-v1"
    assert binding.model_revision == "resolver@1"
    assert calls[0][1]["temperature"] == 0
    assert calls[0][1]["model_role"] == "verify"
    assert calls[0][0][2] is TaxonomyDecisionDraftBatch
    assert '"requirement_unit"' in calls[0][0][1]


async def test_policy_and_bound_model_revision_mismatch_abstains_without_calls() -> None:
    calls = {"retrieve": 0, "decide": 0}

    result = await _resolve(
        _resolver(calls=calls, model_revision="resolver@2"),
        policy=_policy(model_revision="resolver@1"),
    )

    assert result.status == "unresolved"
    assert result.reason_code == "resolver_model_revision_mismatch"
    assert calls == {"retrieve": 0, "decide": 0}


async def test_candidate_source_identity_mismatch_abstains_before_external_calls() -> None:
    calls = {"retrieve": 0, "decide": 0}

    async def retrieve(_: RequirementUnit) -> list[TaxonomyCandidate]:
        calls["retrieve"] += 1
        return _candidates()

    async def decide(_: TaxonomyDecisionRequest) -> TaxonomyDecisionDraftBatch:
        calls["decide"] += 1
        return TaxonomyDecisionDraftBatch(result=_decision())

    resolver = TaxonomyResolver(
        candidate_source=TaxonomyCandidateSourceBinding(
            retrieve_candidates=retrieve,
            taxonomy_version_id=TAXONOMY_VERSION_ID,
            taxonomy_manifest_hash="f" * 64,
            policy_version=_policy().canonical_hash,
            candidate_index_hash=INDEX_HASH,
        ),
        decider_binding=TaxonomyDeciderBinding(
            decide=decide,
            prompt_revision="taxonomy-resolver-v1",
            model_revision="resolver@1",
        ),
    )

    result = await _resolve(resolver)

    assert result.status == "unresolved"
    assert result.reason_code == "candidate_source_identity_mismatch"
    assert calls == {"retrieve": 0, "decide": 0}


async def test_retriever_binding_drives_resolver_end_to_end() -> None:
    async def embed(texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0, 0.0, 0.0] if any(token in text for token in ("商品同步", "巨量平台", "商品库")) else [0.0, 1.0, 0.0]
            for text in texts
        ]

    async def decide(_: TaxonomyDecisionRequest) -> TaxonomyDecisionDraftBatch:
        return TaxonomyDecisionDraftBatch(result=_decision())

    policy = _policy()
    retriever = TaxonomyCandidateRetriever(embed_batch=embed, embedding_revision="embedding@1")
    index = await retriever.build_index(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        taxonomy_manifest_hash=MANIFEST_HASH,
        concepts=_concepts(),
        policy=policy,
    )
    resolver = TaxonomyResolver(
        candidate_source=retriever.bind(index=index, policy=policy),
        decider_binding=TaxonomyDeciderBinding(
            decide=decide,
            prompt_revision="taxonomy-resolver-v1",
            model_revision="resolver@1",
        ),
    )

    result = await _resolve(resolver, policy=policy)

    assert result.status == "mapped"
    assert result.primary_concept_id == SYNC_CONCEPT_ID
    assert result.candidates[0].stable_key == "product.sync"
