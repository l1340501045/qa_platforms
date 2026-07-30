from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.taxonomy_resolution import (
    TaxonomyCandidate,
    TaxonomyResolution,
    TaxonomyResolutionPolicy,
    bootstrap_proposal_id,
)

TAXONOMY_VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_VERSION_ID = UUID("22222222-2222-2222-2222-222222222222")
PRIMARY_CONCEPT_ID = UUID("33333333-3333-3333-3333-333333333333")
RELATED_CONCEPT_ID = UUID("44444444-4444-4444-4444-444444444444")
OUTSIDE_CONCEPT_ID = UUID("55555555-5555-5555-5555-555555555555")
MANIFEST_HASH = "a" * 64
INPUT_HASH = "b" * 64
UNIT_ID = f"ru_{'c' * 64}"


def _candidate(
    *,
    concept_id: UUID = PRIMARY_CONCEPT_ID,
    taxonomy_version_id: UUID = TAXONOMY_VERSION_ID,
    stable_key: str = "product.sync",
    score: float = 0.92,
    rank: int = 1,
) -> dict:
    return {
        "taxonomy_version_id": str(taxonomy_version_id),
        "concept_id": str(concept_id),
        "stable_key": stable_key,
        "score": score,
        "rank": rank,
        "evidence": ["definition_embedding", "alias_exact"],
    }


def _policy_data() -> dict:
    return {
        "schema_version": 1,
        "top_k": 5,
        "minimum_score": 0.85,
        "minimum_margin": 0.12,
        "out_of_scope_conflict_score": 0.9,
        "decision_context_max_chars": 24_000,
        "require_grounding": True,
        "allowed_node_types": ["capability", "module"],
        "allowed_node_statuses": ["active"],
        "model_role": "taxonomy_resolver",
        "model_revision": "deepseek-v4-pro-office@2026-07-21",
        "fail_behavior": "abstain",
        "auto_accept_signal": "retrieval_score_margin",
    }


def _mapped_resolution_data() -> dict:
    policy = TaxonomyResolutionPolicy.model_validate(_policy_data())
    return {
        "schema_version": 1,
        "status": "mapped",
        "unresolved_kind": None,
        "method": "policy_auto",
        "taxonomy_version_id": str(TAXONOMY_VERSION_ID),
        "primary_concept_id": str(PRIMARY_CONCEPT_ID),
        "related_concept_ids": [],
        "candidates": [
            _candidate(),
            _candidate(
                concept_id=RELATED_CONCEPT_ID,
                stable_key="product.import",
                score=0.72,
                rank=2,
            ),
        ],
        "confidence": 0.92,
        "margin": 0.2,
        "reason_code": "policy.thresholds_met",
        "reason": "候选分数和间隔均达到固定策略门槛。",
        "input_hash": INPUT_HASH,
        "taxonomy_manifest_hash": MANIFEST_HASH,
        "policy_version": policy.canonical_hash,
        "model_revision": "deepseek-v4-pro-office@2026-07-21",
        "requirement_unit_ids": [UNIT_ID],
    }


def test_candidate_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        TaxonomyCandidate.model_validate(_candidate(score=1.01))


def test_candidate_scope_conflict_requires_separate_negative_evidence() -> None:
    missing_evidence = _candidate()
    missing_evidence["scope_conflict"] = True
    false_conflict = _candidate()
    false_conflict["scope_conflict_evidence"] = ["negative_example:ru_123"]

    with pytest.raises(ValidationError, match="scope_conflict_evidence_required"):
        TaxonomyCandidate.model_validate(missing_evidence)
    with pytest.raises(ValidationError, match="scope_conflict_evidence_forbidden"):
        TaxonomyCandidate.model_validate(false_conflict)


def test_policy_auto_cannot_map_a_scope_conflicted_top_candidate() -> None:
    data = _mapped_resolution_data()
    data["candidates"][0]["scope_conflict"] = True
    data["candidates"][0]["scope_conflict_evidence"] = ["negative_example:ru_123"]

    with pytest.raises(ValidationError, match="policy_auto_scope_conflict"):
        TaxonomyResolution.model_validate(data)


def test_resolution_rejects_duplicate_candidate_rank() -> None:
    data = _mapped_resolution_data()
    data["candidates"].append(
        _candidate(
            concept_id=OUTSIDE_CONCEPT_ID,
            stable_key="product.create",
            score=0.88,
            rank=1,
        )
    )

    with pytest.raises(ValidationError, match="duplicate_candidate_rank"):
        TaxonomyResolution.model_validate(data)


def test_resolution_rejects_candidate_from_another_taxonomy_version() -> None:
    data = _mapped_resolution_data()
    data["candidates"][0]["taxonomy_version_id"] = str(OTHER_VERSION_ID)

    with pytest.raises(ValidationError, match="candidate_taxonomy_version_mismatch"):
        TaxonomyResolution.model_validate(data)


def test_resolution_rejects_primary_outside_candidate_set_for_policy_auto() -> None:
    data = _mapped_resolution_data()
    data["primary_concept_id"] = str(OUTSIDE_CONCEPT_ID)

    with pytest.raises(ValidationError, match="policy_auto_primary_not_in_candidates"):
        TaxonomyResolution.model_validate(data)


def test_policy_auto_uses_ranked_retrieval_score_not_model_self_confidence() -> None:
    data = _mapped_resolution_data()
    data["confidence"] = 0.99

    with pytest.raises(ValidationError, match="policy_auto_confidence_not_top_score"):
        TaxonomyResolution.model_validate(data)


def test_policy_auto_margin_must_match_ranked_candidate_scores() -> None:
    data = _mapped_resolution_data()
    data["margin"] = 0.3

    with pytest.raises(ValidationError, match="policy_auto_margin_mismatch"):
        TaxonomyResolution.model_validate(data)


def test_policy_auto_related_concepts_must_come_from_candidates() -> None:
    data = _mapped_resolution_data()
    data["related_concept_ids"] = [str(OUTSIDE_CONCEPT_ID)]

    with pytest.raises(ValidationError, match="policy_auto_related_not_in_candidates"):
        TaxonomyResolution.model_validate(data)


def test_unresolved_resolution_cannot_write_concept_coordinates() -> None:
    data = _mapped_resolution_data()
    data.update(
        {
            "status": "unresolved",
            "unresolved_kind": "abstained",
            "primary_concept_id": str(PRIMARY_CONCEPT_ID),
            "related_concept_ids": [str(RELATED_CONCEPT_ID)],
            "confidence": None,
            "margin": None,
            "reason_code": "policy.margin_below_threshold",
        }
    )

    with pytest.raises(ValidationError, match="unresolved_must_not_resolve"):
        TaxonomyResolution.model_validate(data)


def test_policy_hash_uses_set_semantics_and_policy_is_frozen() -> None:
    first = TaxonomyResolutionPolicy.model_validate(_policy_data())
    reordered = _policy_data()
    reordered["allowed_node_types"].reverse()
    second = TaxonomyResolutionPolicy.model_validate(reordered)

    assert first.canonical_hash == second.canonical_hash
    with pytest.raises(ValidationError):
        first.top_k = 10


def test_policy_only_allows_fail_closed_and_calibrated_acceptance_signal() -> None:
    fail_open = _policy_data()
    fail_open["fail_behavior"] = "legacy_fallback"
    llm_confidence = _policy_data()
    llm_confidence["auto_accept_signal"] = "llm_self_confidence"

    with pytest.raises(ValidationError):
        TaxonomyResolutionPolicy.model_validate(fail_open)
    with pytest.raises(ValidationError):
        TaxonomyResolutionPolicy.model_validate(llm_confidence)


def test_policy_rejects_inactive_taxonomy_targets() -> None:
    data = _policy_data()
    data["allowed_node_statuses"] = ["active", "deprecated"]

    with pytest.raises(ValidationError):
        TaxonomyResolutionPolicy.model_validate(data)


def test_bootstrap_proposal_identity_depends_only_on_sorted_evidence_hashes() -> None:
    evidence = ["1" * 64, "2" * 64]

    original = bootstrap_proposal_id(evidence)
    renamed = bootstrap_proposal_id(list(reversed(evidence)))

    assert original == renamed
