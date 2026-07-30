"""业务 taxonomy manifest 的强类型契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnitId

StableKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=160)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomySelector(BaseModel):
    """只允许能跨文案变化保持稳定的 Test Point 选择条件。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rule_id: str | None = Field(default=None, min_length=1, max_length=100)
    structural_key: str | None = Field(default=None, min_length=1, max_length=255)
    requirement_anchor: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_value(self) -> TaxonomySelector:
        value_count = sum(value is not None for value in (self.rule_id, self.structural_key, self.requirement_anchor))
        if value_count != 1:
            raise ValueError("selector_requires_exactly_one_value")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json", exclude_none=True))


class TaxonomySelectorFacts(BaseModel):
    """TestPoint 生成时冻结的稳定输入事实；分类输出不得反向充当事实。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    feature_fingerprint: Sha256
    rule_id: str | None = Field(default=None, min_length=1, max_length=100)
    structural_key: str | None = Field(default=None, min_length=1, max_length=255)
    requirement_anchors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_anchors(self) -> TaxonomySelectorFacts:
        if len(self.requirement_anchors) != len(set(self.requirement_anchors)):
            raise ValueError("duplicate_requirement_anchor")
        if any(not anchor.strip() for anchor in self.requirement_anchors):
            raise ValueError("empty_requirement_anchor")
        return self


class TaxonomyExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    text: str = Field(min_length=1)
    document_content_hash: Sha256
    requirement_unit_id: RequirementUnitId

    @property
    def identity(self) -> tuple[str, str]:
        return self.document_content_hash, self.requirement_unit_id


class TaxonomyNodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str = Field(min_length=1, max_length=255)
    parent_stable_key: StableKey | None = None
    aliases: list[str] = Field(default_factory=list)
    sort_order: int = Field(default=0, ge=0)
    node_status: Literal["active", "deprecated", "merged"] = "active"
    replacement_stable_key: StableKey | None = None
    definition: str | None = Field(default=None, min_length=1)
    scope_note: str | None = Field(default=None, min_length=1)
    in_scope_examples: list[TaxonomyExample] | None = None
    out_of_scope_examples: list[TaxonomyExample] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> TaxonomyNodeManifest:
        if self.node_status == "merged" and self.replacement_stable_key is None:
            raise ValueError("merged_replacement_required")
        if self.node_status == "active" and self.replacement_stable_key is not None:
            raise ValueError("active_replacement_forbidden")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_alias")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("empty_alias")
        in_scope = self.in_scope_examples or []
        out_of_scope = self.out_of_scope_examples or []
        in_scope_identities = [example.identity for example in in_scope]
        out_of_scope_identities = [example.identity for example in out_of_scope]
        if len(in_scope_identities) != len(set(in_scope_identities)):
            raise ValueError("duplicate_in_scope_example")
        if len(out_of_scope_identities) != len(set(out_of_scope_identities)):
            raise ValueError("duplicate_out_of_scope_example")
        if set(in_scope_identities) & set(out_of_scope_identities):
            raise ValueError("scope_example_conflict")
        return self


class TaxonomyMappingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: UUID
    document_content_hash: Sha256
    feature_fingerprint: Sha256
    scope: Literal["feature_default", "test_point_selector"]
    selector: TaxonomySelector | None = None
    target_stable_key: StableKey
    related_stable_keys: list[StableKey] = Field(default_factory=list)
    mapping_method: Literal["manual", "deterministic", "llm_assisted"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=100)
    reviewed_at: datetime | None = None
    supersedes_mapping_id: UUID | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> TaxonomyMappingManifest:
        if self.scope == "feature_default" and self.selector is not None:
            raise ValueError("feature_default_selector_forbidden")
        if self.scope == "test_point_selector" and self.selector is None:
            raise ValueError("test_point_selector_required")
        if self.review_status in {"approved", "rejected"} and not (self.reviewed_by and self.reviewed_at):
            raise ValueError("reviewed_mapping_metadata_required")
        if self.review_status == "pending" and (self.reviewed_by or self.reviewed_at):
            raise ValueError("pending_mapping_review_metadata_forbidden")
        if self.reviewed_at and (self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None):
            raise ValueError("reviewed_at_timezone_required")
        if self.supersedes_mapping_id and self.review_status != "approved":
            raise ValueError("supersedes_requires_approved")
        if len(self.related_stable_keys) != len(set(self.related_stable_keys)):
            raise ValueError("duplicate_related_concept")
        if self.target_stable_key in self.related_stable_keys:
            raise ValueError("target_repeated_as_related")
        return self

    @property
    def selector_hash(self) -> str:
        return self.selector.canonical_hash if self.selector else _canonical_hash({})

    @property
    def identity(self) -> tuple[UUID, str, str, str, str]:
        return (
            self.document_id,
            self.document_content_hash,
            self.feature_fingerprint,
            self.scope,
            self.selector_hash,
        )


class TaxonomyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1, 2]
    system_id: UUID
    version: int = Field(ge=1)
    change_note: str = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=100)
    nodes: list[TaxonomyNodeManifest] = Field(min_length=1)
    mappings: list[TaxonomyMappingManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_and_mappings(self) -> TaxonomyManifest:
        nodes_by_key = {node.stable_key: node for node in self.nodes}
        if len(nodes_by_key) != len(self.nodes):
            raise ValueError("duplicate_stable_key")

        for node in self.nodes:
            semantic_fields = (
                node.definition,
                node.scope_note,
                node.in_scope_examples,
                node.out_of_scope_examples,
            )
            if self.schema_version == 1:
                if any(value is not None for value in semantic_fields):
                    raise ValueError("v1_semantics_forbidden")
                continue
            if node.definition is None:
                raise ValueError(f"v2_node_definition_required:{node.stable_key}")
            if node.scope_note is None:
                raise ValueError(f"v2_node_scope_note_required:{node.stable_key}")
            if node.node_type == "capability" and node.node_status == "active" and not node.in_scope_examples:
                raise ValueError(f"v2_active_capability_in_scope_evidence_required:{node.stable_key}")

        self._validate_relation(nodes_by_key, "parent_stable_key", "parent")
        self._validate_relation(nodes_by_key, "replacement_stable_key", "replacement")

        mapping_identities: set[tuple[UUID, str, str, str, str]] = set()
        for mapping in self.mappings:
            target = nodes_by_key.get(mapping.target_stable_key)
            if target is None:
                raise ValueError(f"mapping_target_missing:{mapping.target_stable_key}")
            if target.node_status != "active":
                raise ValueError(f"mapping_target_not_active:{mapping.target_stable_key}")
            for related_key in mapping.related_stable_keys:
                related = nodes_by_key.get(related_key)
                if related is None:
                    raise ValueError(f"mapping_related_missing:{related_key}")
                if related.node_status != "active":
                    raise ValueError(f"mapping_related_not_active:{related_key}")
            if mapping.identity in mapping_identities:
                raise ValueError("duplicate_mapping_identity")
            if (
                mapping.review_status == "approved"
                and mapping.reviewed_by
                and mapping.reviewed_by.casefold() == self.created_by.casefold()
            ):
                raise ValueError("mapping_self_approval_forbidden")
            mapping_identities.add(mapping.identity)

        for node in self.nodes:
            if node.replacement_stable_key:
                replacement = nodes_by_key[node.replacement_stable_key]
                if replacement.node_status != "active":
                    raise ValueError(f"replacement_target_not_active:{node.replacement_stable_key}")
        return self

    @staticmethod
    def _validate_relation(
        nodes_by_key: dict[str, TaxonomyNodeManifest],
        field_name: Literal["parent_stable_key", "replacement_stable_key"],
        relation_name: str,
    ) -> None:
        edges: dict[str, str] = {}
        for key, node in nodes_by_key.items():
            target = getattr(node, field_name)
            if target is None:
                continue
            if target not in nodes_by_key:
                raise ValueError(f"{relation_name}_target_missing:{target}")
            if target == key:
                raise ValueError(f"{relation_name}_cycle:{key}")
            edges[key] = target

        for start in edges:
            seen: set[str] = set()
            current: str | None = start
            while current in edges:
                if current in seen:
                    raise ValueError(f"{relation_name}_cycle:{start}")
                seen.add(current)
                current = edges[current]


class TaxonomyCaseAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: UUID
    target_stable_key: StableKey | None = None
    related_stable_keys: list[StableKey] = Field(default_factory=list)
    assignment_source: Literal[
        "approved_mapping",
        "reviewed_override",
        "candidate_proposal",
        "unresolved",
    ]
    mapping_id: UUID | None = None
    reason: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    unresolved_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_assignment(self) -> TaxonomyCaseAssignment:
        if len(self.related_stable_keys) != len(set(self.related_stable_keys)):
            raise ValueError("duplicate_related_concept")
        if self.target_stable_key in self.related_stable_keys:
            raise ValueError("target_repeated_as_related")

        if self.assignment_source == "unresolved":
            if self.target_stable_key or self.related_stable_keys or self.mapping_id or self.confidence is not None:
                raise ValueError("unresolved_assignment_must_not_resolve")
            if not self.unresolved_reason:
                raise ValueError("unresolved_reason_required")
            return self

        if self.target_stable_key is None:
            raise ValueError("resolved_assignment_target_required")
        if self.assignment_source == "candidate_proposal" and self.confidence is not None:
            raise ValueError("uncalibrated_candidate_confidence_forbidden")
        if self.assignment_source != "candidate_proposal" and self.confidence is None:
            raise ValueError("approved_assignment_confidence_required")
        if self.unresolved_reason is not None:
            raise ValueError("resolved_assignment_unresolved_reason_forbidden")
        if self.assignment_source == "approved_mapping" and self.mapping_id is None:
            raise ValueError("approved_mapping_id_required")
        if self.assignment_source != "approved_mapping" and self.mapping_id is not None:
            raise ValueError("non_mapping_assignment_mapping_id_forbidden")
        return self


class TaxonomyAssignmentSet(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    batch_id: UUID
    taxonomy_version: int = Field(ge=1)
    manifest_hash: Sha256
    prepared_by: str = Field(min_length=1, max_length=100)
    prepared_at: datetime
    approval_status: Literal["draft", "approved"] = "draft"
    approved_by: str | None = Field(default=None, min_length=1, max_length=100)
    approved_at: datetime | None = None
    assignments: list[TaxonomyCaseAssignment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_assignment_set(self) -> TaxonomyAssignmentSet:
        if self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() is None:
            raise ValueError("prepared_at_timezone_required")
        if self.approved_at and (self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None):
            raise ValueError("approved_at_timezone_required")
        if self.approval_status == "approved" and not (self.approved_by and self.approved_at):
            raise ValueError("approved_assignment_metadata_required")
        if self.approval_status == "draft" and (self.approved_by or self.approved_at):
            raise ValueError("draft_assignment_approval_metadata_forbidden")
        if self.approved_at and self.approved_at < self.prepared_at:
            raise ValueError("approval_before_preparation")
        if (
            self.approval_status == "approved"
            and self.approved_by
            and self.approved_by.casefold() == self.prepared_by.casefold()
        ):
            raise ValueError("assignment_self_approval_forbidden")
        if self.approval_status == "approved" and any(
            assignment.assignment_source == "candidate_proposal" for assignment in self.assignments
        ):
            raise ValueError("approved_assignment_contains_candidate_proposal")
        case_ids = [assignment.case_id for assignment in self.assignments]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate_case_assignment")
        return self
