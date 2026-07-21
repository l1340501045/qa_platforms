"""Taxonomy 候选、决议与不可变策略契约。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnitId, Sha256

StableKey = str


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    taxonomy_version_id: UUID
    concept_id: UUID
    stable_key: StableKey = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=160)
    score: float = Field(ge=0, le=1)
    rank: int = Field(ge=1)
    evidence: list[str] = Field(min_length=1)
    scope_conflict: bool = False
    scope_conflict_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence(self) -> TaxonomyCandidate:
        if len(self.evidence) != len(set(self.evidence)):
            raise ValueError("duplicate_candidate_evidence")
        if any(not item for item in self.evidence):
            raise ValueError("empty_candidate_evidence")
        if self.scope_conflict and not self.scope_conflict_evidence:
            raise ValueError("scope_conflict_evidence_required")
        if not self.scope_conflict and self.scope_conflict_evidence:
            raise ValueError("scope_conflict_evidence_forbidden")
        if len(self.scope_conflict_evidence) != len(set(self.scope_conflict_evidence)):
            raise ValueError("duplicate_scope_conflict_evidence")
        return self


class TaxonomyResolutionPolicy(BaseModel):
    """内容寻址的 fail-closed 自动决议策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    top_k: int = Field(ge=1, le=50)
    minimum_score: float = Field(ge=0, le=1)
    minimum_margin: float = Field(ge=0, le=1)
    out_of_scope_conflict_score: float = Field(ge=0, le=1)
    decision_context_max_chars: int = Field(ge=1000, le=200_000)
    require_grounding: Literal[True] = True
    allowed_node_types: tuple[Literal["domain", "module", "capability"], ...] = Field(min_length=1)
    allowed_node_statuses: tuple[Literal["active", "deprecated", "merged"], ...] = Field(min_length=1)
    model_role: Literal["taxonomy_resolver"]
    model_revision: str = Field(min_length=1, max_length=255)
    fail_behavior: Literal["abstain"] = "abstain"
    auto_accept_signal: Literal["retrieval_score_margin"] = "retrieval_score_margin"

    @model_validator(mode="after")
    def validate_sets(self) -> TaxonomyResolutionPolicy:
        if len(self.allowed_node_types) != len(set(self.allowed_node_types)):
            raise ValueError("duplicate_allowed_node_type")
        if len(self.allowed_node_statuses) != len(set(self.allowed_node_statuses)):
            raise ValueError("duplicate_allowed_node_status")
        if set(self.allowed_node_statuses) != {"active"}:
            raise ValueError("inactive_taxonomy_target_forbidden")
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["allowed_node_types"] = sorted(payload["allowed_node_types"])
        payload["allowed_node_statuses"] = sorted(payload["allowed_node_statuses"])
        return _canonical_hash(payload)

    @property
    def candidate_index_policy_hash(self) -> str:
        """只绑定会改变索引成员的策略字段，避免决议调参触发无效重建。"""

        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "allowed_node_types": sorted(self.allowed_node_types),
                "allowed_node_statuses": sorted(self.allowed_node_statuses),
            }
        )


class TaxonomyResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    status: Literal["candidate", "mapped", "unresolved", "legacy"]
    unresolved_kind: Literal["novel", "abstained", "unsupported", "conflicted"] | None = None
    method: Literal["approved_mapping", "policy_auto", "bootstrap", "evolve"]
    taxonomy_version_id: UUID
    primary_concept_id: UUID | None = None
    related_concept_ids: list[UUID] = Field(default_factory=list)
    candidates: list[TaxonomyCandidate] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    margin: float | None = Field(default=None, ge=0, le=1)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    reason: str = Field(min_length=1)
    input_hash: Sha256
    taxonomy_manifest_hash: Sha256
    policy_version: Sha256
    model_revision: str | None = Field(default=None, min_length=1, max_length=255)
    requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_resolution(self) -> TaxonomyResolution:
        if len(self.related_concept_ids) != len(set(self.related_concept_ids)):
            raise ValueError("duplicate_related_concept")
        if self.primary_concept_id in self.related_concept_ids:
            raise ValueError("primary_repeated_as_related")
        if len(self.requirement_unit_ids) != len(set(self.requirement_unit_ids)):
            raise ValueError("duplicate_requirement_unit")

        candidate_ids = [candidate.concept_id for candidate in self.candidates]
        candidate_keys = [candidate.stable_key for candidate in self.candidates]
        candidate_ranks = [candidate.rank for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("duplicate_candidate_concept")
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("duplicate_candidate_stable_key")
        if len(candidate_ranks) != len(set(candidate_ranks)):
            raise ValueError("duplicate_candidate_rank")
        if candidate_ranks and sorted(candidate_ranks) != list(range(1, len(candidate_ranks) + 1)):
            raise ValueError("candidate_rank_not_contiguous")
        if any(candidate.taxonomy_version_id != self.taxonomy_version_id for candidate in self.candidates):
            raise ValueError("candidate_taxonomy_version_mismatch")
        ranked_candidates = sorted(self.candidates, key=lambda candidate: candidate.rank)
        if any(
            current.score < following.score
            for current, following in zip(ranked_candidates, ranked_candidates[1:], strict=False)
        ):
            raise ValueError("candidate_score_rank_mismatch")

        if self.status == "unresolved":
            if self.unresolved_kind is None:
                raise ValueError("unresolved_kind_required")
            if self.primary_concept_id is not None or self.related_concept_ids:
                raise ValueError("unresolved_must_not_resolve")
            if self.method == "approved_mapping":
                raise ValueError("approved_mapping_cannot_be_unresolved")
            return self

        if self.unresolved_kind is not None:
            raise ValueError("resolved_unresolved_kind_forbidden")

        if self.status == "mapped":
            if self.method not in {"approved_mapping", "policy_auto"}:
                raise ValueError("mapped_method_invalid")
            if self.primary_concept_id is None:
                raise ValueError("mapped_primary_required")
            if self.confidence is None:
                raise ValueError("mapped_confidence_required")
            if self.method == "policy_auto":
                if self.primary_concept_id not in candidate_ids:
                    raise ValueError("policy_auto_primary_not_in_candidates")
                if self.primary_concept_id != ranked_candidates[0].concept_id:
                    raise ValueError("policy_auto_primary_must_be_rank_one")
                if ranked_candidates[0].scope_conflict:
                    raise ValueError("policy_auto_scope_conflict")
                if any(concept_id not in candidate_ids for concept_id in self.related_concept_ids):
                    raise ValueError("policy_auto_related_not_in_candidates")
                if self.margin is None:
                    raise ValueError("policy_auto_margin_required")
                if self.model_revision is None:
                    raise ValueError("policy_auto_model_revision_required")
                if not math.isclose(self.confidence, ranked_candidates[0].score, abs_tol=1e-9):
                    raise ValueError("policy_auto_confidence_not_top_score")
                expected_margin = ranked_candidates[0].score
                if len(ranked_candidates) > 1:
                    expected_margin -= ranked_candidates[1].score
                if not math.isclose(self.margin, expected_margin, abs_tol=1e-9):
                    raise ValueError("policy_auto_margin_mismatch")
            elif self.model_revision is not None:
                raise ValueError("approved_mapping_model_revision_forbidden")
            return self

        if self.status == "candidate":
            if self.method not in {"bootstrap", "evolve"}:
                raise ValueError("candidate_method_invalid")
            if self.primary_concept_id is not None or self.related_concept_ids:
                raise ValueError("candidate_must_not_resolve")
            if not self.candidates:
                raise ValueError("candidate_options_required")
            return self

        if self.method != "approved_mapping":
            raise ValueError("legacy_method_invalid")
        if self.primary_concept_id is None:
            raise ValueError("legacy_primary_required")
        return self


def bootstrap_proposal_id(evidence_hashes: Iterable[str]) -> str:
    """名称和展示路径不参与 proposal 身份，只使用排序后的来源证据。"""

    normalized = sorted(set(evidence_hashes))
    if not normalized:
        raise ValueError("bootstrap_evidence_required")
    if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in normalized):
        raise ValueError("invalid_bootstrap_evidence_hash")
    return f"bp_{_canonical_hash(normalized)}"
