from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.taxonomy import TaxonomyAssignmentSet
from src.testcase_generator.services.taxonomy_manifest import assignment_hash

CASE_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CASE_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _assignment_data() -> dict:
    return {
        "schema_version": 1,
        "batch_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "taxonomy_version": 1,
        "manifest_hash": "f" * 64,
        "prepared_by": "codex",
        "prepared_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
        "approval_status": "approved",
        "approved_by": "echo_lacey",
        "approved_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
        "assignments": [
            {
                "case_id": str(CASE_A),
                "target_stable_key": "asset-center.filter",
                "related_stable_keys": ["task-center", "asset-center"],
                "assignment_source": "reviewed_override",
                "reason": "历史批次人工校准",
                "confidence": 1,
            },
            {
                "case_id": str(CASE_B),
                "assignment_source": "unresolved",
                "reason": "需求证据不足",
                "unresolved_reason": "无法确定业务能力",
            },
        ],
    }


def test_assignment_hash_uses_set_and_case_order_independent_semantics() -> None:
    first = TaxonomyAssignmentSet.model_validate(_assignment_data())
    reordered = deepcopy(_assignment_data())
    reordered["assignments"].reverse()
    reordered["assignments"][1]["related_stable_keys"].reverse()

    assert assignment_hash(first) == assignment_hash(TaxonomyAssignmentSet.model_validate(reordered))


def test_assignment_set_rejects_duplicate_case_id() -> None:
    data = _assignment_data()
    data["assignments"].append(deepcopy(data["assignments"][0]))

    with pytest.raises(ValidationError, match="duplicate_case_assignment"):
        TaxonomyAssignmentSet.model_validate(data)


def test_unresolved_assignment_cannot_carry_target() -> None:
    data = _assignment_data()
    data["assignments"][1]["target_stable_key"] = "asset-center"

    with pytest.raises(ValidationError, match="unresolved_assignment_must_not_resolve"):
        TaxonomyAssignmentSet.model_validate(data)


def test_approved_mapping_assignment_requires_mapping_id() -> None:
    data = _assignment_data()
    data["assignments"][0]["assignment_source"] = "approved_mapping"

    with pytest.raises(ValidationError, match="approved_mapping_id_required"):
        TaxonomyAssignmentSet.model_validate(data)


def test_assignment_set_requires_timezone_aware_prepared_time() -> None:
    data = _assignment_data()
    data["prepared_at"] = "2026-07-21T10:00:00"

    with pytest.raises(ValidationError, match="prepared_at_timezone_required"):
        TaxonomyAssignmentSet.model_validate(data)


def test_draft_assignment_set_cannot_claim_approval_metadata() -> None:
    data = _assignment_data()
    data["approval_status"] = "draft"

    with pytest.raises(ValidationError, match="draft_assignment_approval_metadata_forbidden"):
        TaxonomyAssignmentSet.model_validate(data)


def test_assignment_set_rejects_approval_before_preparation() -> None:
    data = _assignment_data()
    data["approved_at"] = datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat()

    with pytest.raises(ValidationError, match="approval_before_preparation"):
        TaxonomyAssignmentSet.model_validate(data)


def test_assignment_set_rejects_self_approval() -> None:
    data = _assignment_data()
    data["approved_by"] = data["prepared_by"]

    with pytest.raises(ValidationError, match="assignment_self_approval_forbidden"):
        TaxonomyAssignmentSet.model_validate(data)


def test_draft_assignment_set_accepts_candidate_proposal() -> None:
    data = _assignment_data()
    data["approval_status"] = "draft"
    data["approved_by"] = None
    data["approved_at"] = None
    data["assignments"][0]["assignment_source"] = "candidate_proposal"
    data["assignments"][0].pop("confidence")

    assignments = TaxonomyAssignmentSet.model_validate(data)

    assert assignments.assignments[0].assignment_source == "candidate_proposal"


def test_candidate_proposal_cannot_claim_uncalibrated_confidence() -> None:
    data = _assignment_data()
    data["approval_status"] = "draft"
    data["approved_by"] = None
    data["approved_at"] = None
    data["assignments"][0]["assignment_source"] = "candidate_proposal"

    with pytest.raises(ValidationError, match="uncalibrated_candidate_confidence_forbidden"):
        TaxonomyAssignmentSet.model_validate(data)


def test_approved_assignment_set_rejects_candidate_proposal() -> None:
    data = _assignment_data()
    data["assignments"][0]["assignment_source"] = "candidate_proposal"
    data["assignments"][0].pop("confidence")

    with pytest.raises(ValidationError, match="approved_assignment_contains_candidate_proposal"):
        TaxonomyAssignmentSet.model_validate(data)


def test_candidate_proposal_cannot_claim_mapping_id() -> None:
    data = _assignment_data()
    data["approval_status"] = "draft"
    data["approved_by"] = None
    data["approved_at"] = None
    data["assignments"][0]["assignment_source"] = "candidate_proposal"
    data["assignments"][0].pop("confidence")
    data["assignments"][0]["mapping_id"] = "dddddddd-dddd-dddd-dddd-dddddddddddd"

    with pytest.raises(ValidationError, match="non_mapping_assignment_mapping_id_forbidden"):
        TaxonomyAssignmentSet.model_validate(data)
