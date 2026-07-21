"""Taxonomy 跨 PRD 泛化评估与受控校准契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnitId
from src.testcase_generator.schemas.taxonomy import Sha256, StableKey
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy

RecordId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=160)]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, code: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    path: str = Field(min_length=1, max_length=2_000)
    sha256: Sha256


class TaxonomyDatasetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    document_key: RecordId
    document_id: UUID
    system_key: RecordId
    system_id: UUID
    split: Literal["train", "dev", "test"]
    source: ArtifactRef
    requirement_units: ArtifactRef


class TaxonomyDatasetManifest(BaseModel):
    """文档级 pilot corpus；可替换的 gold/预测 run 不参与语料身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    corpus_id: RecordId
    pilot_corpus: Literal[True]
    split_strategy: Literal["document_level"]
    test_locked: Literal[True]
    created_at: datetime
    documents: list[TaxonomyDatasetDocument] = Field(min_length=2)
    gold_artifact: ArtifactRef
    prediction_artifact: ArtifactRef
    transformation_artifact: ArtifactRef
    prompt_revisions: dict[str, str] = Field(min_length=1)
    model_revisions: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_isolation(self) -> TaxonomyDatasetManifest:
        _require_aware(self.created_at, "dataset_created_at_timezone_required")
        document_keys = [item.document_key for item in self.documents]
        if len(document_keys) != len(set(document_keys)):
            raise ValueError("duplicate_dataset_document_key")
        document_ids = [item.document_id for item in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("duplicate_dataset_document_id")

        source_hashes = [item.source.sha256 for item in self.documents]
        if len(source_hashes) != len(set(source_hashes)):
            raise ValueError("document_content_hash_leakage")
        source_paths = [item.source.path for item in self.documents]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("document_source_path_leakage")

        systems: dict[str, tuple[UUID, set[str]]] = {}
        system_keys_by_id: dict[UUID, str] = {}
        for item in self.documents:
            existing = systems.setdefault(item.system_key, (item.system_id, set()))
            if existing[0] != item.system_id:
                raise ValueError(f"system_identity_conflict:{item.system_key}")
            existing_key = system_keys_by_id.setdefault(item.system_id, item.system_key)
            if existing_key != item.system_key:
                raise ValueError(f"system_id_alias_conflict:{item.system_id}")
            existing[1].add(item.split)
        for system_key, (_, splits) in systems.items():
            if not {"dev", "test"} <= splits:
                raise ValueError(f"system_split_incomplete:{system_key}")

        if any(not key.strip() or not value.strip() for key, value in self.prompt_revisions.items()):
            raise ValueError("empty_prompt_revision")
        if any(not key.strip() or not value.strip() for key, value in self.model_revisions.items()):
            raise ValueError("empty_model_revision")
        return self

    @property
    def dataset_hash(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "corpus_id": self.corpus_id,
                "pilot_corpus": self.pilot_corpus,
                "split_strategy": self.split_strategy,
                "test_locked": self.test_locked,
                "created_at": self.created_at.isoformat(),
                "documents": [
                    item.model_dump(mode="json")
                    for item in sorted(self.documents, key=lambda document: document.document_key)
                ],
                "transformation_artifact": self.transformation_artifact.model_dump(mode="json"),
                "prompt_revisions": dict(sorted(self.prompt_revisions.items())),
                "model_revisions": dict(sorted(self.model_revisions.items())),
            }
        )


class TaxonomyGoldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    record_id: RecordId
    document_key: RecordId
    system_key: RecordId
    split: Literal["dev", "test"]
    requirement_unit_id: RequirementUnitId
    expected_disposition: Literal["reuse", "abstain", "new_node"]
    expected_primary_stable_key: StableKey | None = None
    acceptable_primary_stable_keys: list[StableKey] = Field(default_factory=list)
    expected_related_stable_keys: list[StableKey] = Field(default_factory=list)
    expected_new_node_stable_key: StableKey | None = None
    acceptable_new_node_stable_keys: list[StableKey] = Field(default_factory=list)
    expected_operation: (
        Literal[
            "add",
            "rename",
            "move",
            "split",
            "merge",
            "deprecate",
            "no_change",
            "alias",
        ]
        | None
    ) = None
    expected_path: list[StableKey] = Field(default_factory=list)
    acceptable_paths: list[list[StableKey]] = Field(default_factory=list)
    gold_evidence: list[str] = Field(min_length=1)
    eligible_for_auto: bool = True
    semantic_group_id: RecordId | None = None
    variant_kind: Literal[
        "original",
        "chapter_reorder",
        "title_rewrite",
        "synonym",
        "multi_capability",
    ] = "original"

    @model_validator(mode="after")
    def validate_gold(self) -> TaxonomyGoldRecord:
        for values, code in (
            (self.acceptable_primary_stable_keys, "duplicate_acceptable_primary"),
            (self.acceptable_new_node_stable_keys, "duplicate_acceptable_new_node"),
            (self.expected_related_stable_keys, "duplicate_expected_related"),
            (self.gold_evidence, "duplicate_gold_evidence"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(code)
        canonical_paths = [tuple(path) for path in self.acceptable_paths]
        if len(canonical_paths) != len(set(canonical_paths)):
            raise ValueError("duplicate_acceptable_path")
        if self.variant_kind != "original" and self.semantic_group_id is None:
            raise ValueError("variant_semantic_group_required")

        if self.expected_disposition == "reuse":
            if self.expected_primary_stable_key is None:
                raise ValueError("reuse_primary_required")
            if self.expected_new_node_stable_key is not None:
                raise ValueError("reuse_new_node_forbidden")
            if not self.expected_path or self.expected_path[-1] not in self.acceptable_primary_keys:
                raise ValueError("reuse_expected_path_invalid")
            if any(not path or path[-1] not in self.acceptable_primary_keys for path in self.acceptable_paths):
                raise ValueError("reuse_acceptable_path_invalid")
        elif self.expected_disposition == "new_node":
            if self.expected_new_node_stable_key is None:
                raise ValueError("new_node_key_required")
            if self.expected_primary_stable_key is not None:
                raise ValueError("new_node_existing_primary_forbidden")
            if self.expected_operation not in {"add", "split"}:
                raise ValueError("new_node_operation_required")
        elif self.expected_primary_stable_key is not None or self.expected_new_node_stable_key is not None:
            raise ValueError("abstain_target_forbidden")
        return self

    @property
    def acceptable_primary_keys(self) -> set[str]:
        values = set(self.acceptable_primary_stable_keys)
        if self.expected_primary_stable_key:
            values.add(self.expected_primary_stable_key)
        return values

    @property
    def acceptable_new_node_keys(self) -> set[str]:
        values = set(self.acceptable_new_node_stable_keys)
        if self.expected_new_node_stable_key:
            values.add(self.expected_new_node_stable_key)
        return values

    @property
    def semantic_expectation(self) -> tuple[object, ...]:
        paths = {tuple(self.expected_path)} if self.expected_path else set()
        paths.update(tuple(path) for path in self.acceptable_paths)
        return (
            self.expected_disposition,
            tuple(sorted(self.acceptable_primary_keys)),
            tuple(sorted(self.expected_related_stable_keys)),
            tuple(sorted(self.acceptable_new_node_keys)),
            self.expected_operation,
            tuple(sorted(paths)),
            self.eligible_for_auto,
        )


class TaxonomyGoldNode(BaseModel):
    """Bootstrap/evolve 节点级 gold，覆盖父节点而不把目录判断塞回 case gold。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    gold_node_key: RecordId
    system_key: RecordId
    node_type: Literal["domain", "module", "capability"]
    parent_gold_node_key: RecordId | None = None
    preferred_stable_key: StableKey
    acceptable_stable_keys: list[StableKey] = Field(default_factory=list)
    evidence_requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gold_node(self) -> TaxonomyGoldNode:
        if self.parent_gold_node_key == self.gold_node_key:
            raise ValueError("gold_node_self_parent")
        if len(self.acceptable_stable_keys) != len(set(self.acceptable_stable_keys)):
            raise ValueError("duplicate_gold_node_stable_key")
        if len(self.evidence_requirement_unit_ids) != len(set(self.evidence_requirement_unit_ids)):
            raise ValueError("duplicate_gold_node_evidence")
        return self

    @property
    def accepted_keys(self) -> set[str]:
        return {self.preferred_stable_key, *self.acceptable_stable_keys}


class TaxonomyGoldSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    corpus_id: RecordId
    dataset_hash: Sha256
    review_method: Literal["human_independent", "model_assisted_provisional"]
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_at: datetime
    records: list[TaxonomyGoldRecord] = Field(min_length=1)
    expected_nodes: list[TaxonomyGoldNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_gold_set(self) -> TaxonomyGoldSet:
        _require_aware(self.reviewed_at, "gold_reviewed_at_timezone_required")
        record_ids = [item.record_id for item in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate_gold_record_id")
        unit_keys = [(item.document_key, item.requirement_unit_id) for item in self.records]
        if len(unit_keys) != len(set(unit_keys)):
            raise ValueError("duplicate_gold_requirement_unit")
        semantic_groups: dict[str, list[TaxonomyGoldRecord]] = {}
        for record in self.records:
            if record.semantic_group_id:
                semantic_groups.setdefault(record.semantic_group_id, []).append(record)
        for group_id, records in semantic_groups.items():
            if any(item.variant_kind != "original" for item in records):
                originals = [item for item in records if item.variant_kind == "original"]
                if len(originals) != 1:
                    raise ValueError(f"semantic_group_original_count_invalid:{group_id}")
                if len({(item.system_key, item.split) for item in records}) != 1:
                    raise ValueError(f"semantic_group_scope_mismatch:{group_id}")
                if len({item.semantic_expectation for item in records}) != 1:
                    raise ValueError(f"semantic_group_gold_mismatch:{group_id}")
        node_keys = [(item.system_key, item.gold_node_key) for item in self.expected_nodes]
        if len(node_keys) != len(set(node_keys)):
            raise ValueError("duplicate_gold_node_key")
        nodes_by_system = {(item.system_key, item.gold_node_key): item for item in self.expected_nodes}
        for node in self.expected_nodes:
            if node.parent_gold_node_key and (node.system_key, node.parent_gold_node_key) not in nodes_by_system:
                raise ValueError(f"gold_node_parent_missing:{node.gold_node_key}")
            if node.parent_gold_node_key:
                parent = nodes_by_system[(node.system_key, node.parent_gold_node_key)]
                if parent.node_type == "capability":
                    raise ValueError(f"gold_capability_has_child:{parent.gold_node_key}")
        for node in self.expected_nodes:
            seen: set[str] = set()
            current: TaxonomyGoldNode | None = node
            while current is not None:
                if current.gold_node_key in seen:
                    raise ValueError(f"gold_node_cycle:{node.gold_node_key}")
                seen.add(current.gold_node_key)
                current = (
                    nodes_by_system.get((current.system_key, current.parent_gold_node_key))
                    if current.parent_gold_node_key
                    else None
                )
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["records"] = sorted(payload["records"], key=lambda item: item["record_id"])
        payload["expected_nodes"] = sorted(
            payload["expected_nodes"],
            key=lambda item: (item["system_key"], item["gold_node_key"]),
        )
        return _canonical_hash(payload)


class TaxonomyTransformationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    transformation_id: RecordId
    system_key: RecordId
    split: Literal["dev", "test"]
    semantic_group_id: RecordId
    source_record_id: RecordId
    variant_record_id: RecordId
    kind: Literal["chapter_reorder", "title_rewrite", "synonym", "multi_capability"]
    transformation_revision: str = Field(min_length=1, max_length=255)
    source_text_hash: Sha256
    variant_text_hash: Sha256

    @model_validator(mode="after")
    def validate_transformation(self) -> TaxonomyTransformationRecord:
        if self.source_record_id == self.variant_record_id:
            raise ValueError("transformation_self_reference")
        if self.source_text_hash == self.variant_text_hash and self.kind != "chapter_reorder":
            raise ValueError("transformation_text_unchanged")
        return self


class TaxonomyTransformationSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    corpus_id: RecordId
    records: list[TaxonomyTransformationRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_transformation_set(self) -> TaxonomyTransformationSet:
        identities = [item.transformation_id for item in self.records]
        variants = [item.variant_record_id for item in self.records]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_transformation_id")
        if len(variants) != len(set(variants)):
            raise ValueError("duplicate_transformation_variant")
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["records"] = sorted(payload["records"], key=lambda item: item["transformation_id"])
        return _canonical_hash(payload)


class TaxonomyPredictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    record_id: RecordId
    document_key: RecordId
    system_key: RecordId
    split: Literal["dev", "test"]
    requirement_unit_id: RequirementUnitId
    input_hash: Sha256
    outcome: Literal["candidate", "approved_mapping", "unresolved", "proposal", "error"]
    predicted_primary_stable_key: StableKey | None = None
    predicted_related_stable_keys: list[StableKey] = Field(default_factory=list)
    predicted_path: list[StableKey] = Field(default_factory=list)
    predicted_operation: (
        Literal[
            "add",
            "rename",
            "move",
            "split",
            "merge",
            "deprecate",
            "no_change",
            "alias",
        ]
        | None
    ) = None
    score: float | None = Field(default=None, ge=0, le=1)
    margin: float | None = Field(default=None, ge=0, le=1)
    scope_conflict: bool = False
    unresolved_kind: Literal["novel", "abstained", "unsupported", "conflicted"] | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=100)
    latency_ms: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    write_disposition: Literal["none", "draft"]

    @model_validator(mode="after")
    def validate_prediction(self) -> TaxonomyPredictionRecord:
        if len(self.predicted_related_stable_keys) != len(set(self.predicted_related_stable_keys)):
            raise ValueError("duplicate_predicted_related")
        if self.predicted_primary_stable_key in self.predicted_related_stable_keys:
            raise ValueError("predicted_primary_repeated_as_related")
        if self.outcome == "candidate":
            if self.predicted_primary_stable_key is None or self.score is None or self.margin is None:
                raise ValueError("candidate_score_and_target_required")
            if self.unresolved_kind or self.error_code or self.predicted_operation:
                raise ValueError("candidate_conflicting_payload")
            if self.write_disposition != "none":
                raise ValueError("candidate_write_forbidden")
        elif self.outcome == "approved_mapping":
            if self.predicted_primary_stable_key is None:
                raise ValueError("approved_mapping_target_required")
            if (
                self.unresolved_kind
                or self.error_code
                or self.predicted_operation
                or self.score is not None
                or self.margin is not None
                or self.scope_conflict
                or self.write_disposition != "none"
            ):
                raise ValueError("approved_mapping_conflicting_payload")
        elif self.outcome == "unresolved":
            if self.unresolved_kind is None:
                raise ValueError("prediction_unresolved_kind_required")
            self._require_no_resolution("unresolved")
        elif self.outcome == "error":
            if self.error_code is None:
                raise ValueError("prediction_error_code_required")
            self._require_no_resolution("error")
        else:
            if self.predicted_operation is None:
                raise ValueError("proposal_operation_required")
            if self.write_disposition != "draft":
                raise ValueError("proposal_must_remain_draft")
            if (
                self.error_code
                or self.unresolved_kind
                or self.predicted_primary_stable_key is not None
                or self.predicted_related_stable_keys
                or self.predicted_path
                or self.score is not None
                or self.margin is not None
                or self.scope_conflict
            ):
                raise ValueError("proposal_conflicting_payload")
        return self

    def _require_no_resolution(self, prefix: str) -> None:
        if (
            self.predicted_primary_stable_key is not None
            or self.predicted_related_stable_keys
            or self.predicted_path
            or self.predicted_operation is not None
            or self.score is not None
            or self.margin is not None
            or self.write_disposition != "none"
        ):
            raise ValueError(f"{prefix}_resolution_forbidden")


class TaxonomyProposedNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    system_key: RecordId
    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str = Field(min_length=1, max_length=255)
    parent_stable_key: StableKey | None = None
    aliases: list[str] = Field(default_factory=list)
    evidence_requirement_unit_ids: list[RequirementUnitId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_node(self) -> TaxonomyProposedNode:
        if self.parent_stable_key == self.stable_key:
            raise ValueError("proposed_node_self_parent")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_proposed_node_alias")
        if len(self.evidence_requirement_unit_ids) != len(set(self.evidence_requirement_unit_ids)):
            raise ValueError("duplicate_proposed_node_evidence")
        return self


class TaxonomyKnownNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    system_key: RecordId
    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    parent_stable_key: StableKey | None = None


class TaxonomyPredictionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    run_id: RecordId
    generated_at: datetime
    dataset_hash: Sha256
    policy_hash: Sha256
    frozen_policy_hash: Sha256 | None = None
    prompt_revisions: dict[str, str] = Field(min_length=1)
    model_revisions: dict[str, str] = Field(min_length=1)
    records: list[TaxonomyPredictionRecord] = Field(min_length=1)
    proposed_nodes: list[TaxonomyProposedNode] = Field(default_factory=list)
    known_nodes: list[TaxonomyKnownNode] = Field(default_factory=list)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(default_factory=dict)
    tree_diff: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_prediction_set(self) -> TaxonomyPredictionSet:
        _require_aware(self.generated_at, "prediction_generated_at_timezone_required")
        record_ids = [item.record_id for item in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("duplicate_prediction_record_id")
        if len({item.split for item in self.records}) != 1:
            raise ValueError("prediction_set_mixed_splits")
        known_keys = [(item.system_key, item.stable_key) for item in self.known_nodes]
        if len(known_keys) != len(set(known_keys)):
            raise ValueError("duplicate_known_taxonomy_node")
        artifact_systems = {
            *(item.system_key for item in self.records),
            *(item.system_key for item in self.proposed_nodes),
            *(item.system_key for item in self.known_nodes),
        }
        unexpected_manifest_systems = sorted(set(self.output_manifest_hashes) - artifact_systems)
        if unexpected_manifest_systems:
            raise ValueError(f"prediction_output_manifest_system_unknown:{','.join(unexpected_manifest_systems)}")
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["records"] = sorted(payload["records"], key=lambda item: item["record_id"])
        payload["proposed_nodes"] = sorted(
            payload["proposed_nodes"],
            key=lambda item: (item["system_key"], item["stable_key"], item["display_name"]),
        )
        payload["known_nodes"] = sorted(
            payload["known_nodes"],
            key=lambda item: (item["system_key"], item["stable_key"]),
        )
        return _canonical_hash(payload)


class TaxonomyCalibrationSystemMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system_key: RecordId
    record_count: int = Field(ge=1)
    eligible_record_count: int = Field(ge=1)
    auto_decision_count: int = Field(ge=1)
    eligible_auto_decision_count: int = Field(ge=1)
    correct_auto_decision_count: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    auto_coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> TaxonomyCalibrationSystemMetrics:
        if self.eligible_record_count > self.record_count:
            raise ValueError("calibration_system_eligible_count_invalid")
        if self.auto_decision_count > self.record_count:
            raise ValueError("calibration_system_auto_decision_count_invalid")
        if self.eligible_auto_decision_count > min(self.eligible_record_count, self.auto_decision_count):
            raise ValueError("calibration_system_eligible_auto_decision_count_invalid")
        if self.correct_auto_decision_count > self.eligible_auto_decision_count:
            raise ValueError("calibration_system_correct_count_invalid")
        if abs(self.precision - self.correct_auto_decision_count / self.auto_decision_count) > 1e-12:
            raise ValueError("calibration_system_precision_mismatch")
        if abs(self.auto_coverage - self.eligible_auto_decision_count / self.eligible_record_count) > 1e-12:
            raise ValueError("calibration_system_coverage_mismatch")
        return self


class TaxonomyFrozenPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    policy: TaxonomyResolutionPolicy
    policy_hash: Sha256
    calibrated_at: datetime
    calibration_split: Literal["dev"]
    calibration_dataset_hash: Sha256
    calibration_gold_hash: Sha256
    calibration_gold_review_method: Literal["human_independent", "model_assisted_provisional"]
    calibration_input_hash: Sha256
    observed_precision: float = Field(ge=0, le=1)
    observed_auto_coverage: float = Field(ge=0, le=1)
    calibration_system_metrics: list[TaxonomyCalibrationSystemMetrics] = Field(min_length=1)
    calibration_record_count: int = Field(ge=1)
    eligible_record_count: int = Field(ge=1)
    auto_decision_count: int = Field(ge=1)
    eligible_auto_decision_count: int = Field(ge=1)
    correct_auto_decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_frozen_policy(self) -> TaxonomyFrozenPolicy:
        _require_aware(self.calibrated_at, "policy_calibrated_at_timezone_required")
        if self.policy_hash != self.policy.canonical_hash:
            raise ValueError("frozen_policy_hash_mismatch")
        if self.eligible_record_count > self.calibration_record_count:
            raise ValueError("calibration_eligible_count_invalid")
        if self.auto_decision_count > self.calibration_record_count:
            raise ValueError("calibration_auto_decision_count_invalid")
        if self.eligible_auto_decision_count > min(self.eligible_record_count, self.auto_decision_count):
            raise ValueError("calibration_eligible_auto_decision_count_invalid")
        if self.correct_auto_decision_count > self.eligible_auto_decision_count:
            raise ValueError("calibration_correct_count_invalid")
        system_keys = [item.system_key for item in self.calibration_system_metrics]
        if len(system_keys) != len(set(system_keys)):
            raise ValueError("duplicate_calibration_system_metrics")
        if sum(item.record_count for item in self.calibration_system_metrics) != self.calibration_record_count:
            raise ValueError("calibration_system_record_count_mismatch")
        if sum(item.eligible_record_count for item in self.calibration_system_metrics) != self.eligible_record_count:
            raise ValueError("calibration_system_eligible_count_mismatch")
        if sum(item.auto_decision_count for item in self.calibration_system_metrics) != self.auto_decision_count:
            raise ValueError("calibration_system_auto_decision_count_mismatch")
        if (
            sum(item.eligible_auto_decision_count for item in self.calibration_system_metrics)
            != self.eligible_auto_decision_count
        ):
            raise ValueError("calibration_system_eligible_auto_decision_count_mismatch")
        if (
            sum(item.correct_auto_decision_count for item in self.calibration_system_metrics)
            != self.correct_auto_decision_count
        ):
            raise ValueError("calibration_system_correct_count_mismatch")
        if abs(self.observed_precision - min(item.precision for item in self.calibration_system_metrics)) > 1e-12:
            raise ValueError("calibration_observed_precision_mismatch")
        if (
            abs(self.observed_auto_coverage - min(item.auto_coverage for item in self.calibration_system_metrics))
            > 1e-12
        ):
            raise ValueError("calibration_observed_coverage_mismatch")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class TaxonomyEvaluationGate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_reuse_precision: float = Field(default=0.95, ge=0, le=1)
    minimum_expected_reuse_coverage: float | None = Field(default=None, ge=0, le=1)
    minimum_hierarchical_path_accuracy: float = Field(default=0.95, ge=0, le=1)
    minimum_semantic_stability: float = Field(default=0.95, ge=0, le=1)
    maximum_duplicate_node_rate: float = Field(default=0, ge=0, le=1)
    maximum_unsupported_node_rate: float = Field(default=0, ge=0, le=1)
    minimum_structural_invariant_rate: float = Field(default=1, ge=0, le=1)
    minimum_new_node_precision: float | None = Field(default=None, ge=0, le=1)
    minimum_new_node_recall: float | None = Field(default=None, ge=0, le=1)
    minimum_proposal_operation_type_accuracy: float | None = Field(default=None, ge=0, le=1)
    maximum_human_intervention_rate: float | None = Field(default=None, ge=0, le=1)
    maximum_operational_failure_rate: float = Field(default=0, ge=0, le=1)
    require_new_node_baseline: bool = True
    require_independent_gold: bool = True
    require_operational_thresholds: bool = True
    require_complete_corpus: bool = True

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class TaxonomyEvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_count: int = Field(ge=0)
    auto_mapped_count: int = Field(ge=0)
    correct_auto_mapped_count: int = Field(ge=0)
    exact_primary_precision: float | None = Field(default=None, ge=0, le=1)
    auto_coverage: float = Field(ge=0, le=1)
    expected_reuse_coverage: float | None = Field(default=None, ge=0, le=1)
    hierarchical_path_accuracy: float | None = Field(default=None, ge=0, le=1)
    abstention_precision: float | None = Field(default=None, ge=0, le=1)
    abstention_recall: float | None = Field(default=None, ge=0, le=1)
    new_node_precision: float | None = Field(default=None, ge=0, le=1)
    new_node_recall: float | None = Field(default=None, ge=0, le=1)
    proposal_operation_type_accuracy: float | None = Field(default=None, ge=0, le=1)
    duplicate_node_rate: float = Field(ge=0, le=1)
    unsupported_node_rate: float = Field(ge=0, le=1)
    semantic_stability_rate: float | None = Field(default=None, ge=0, le=1)
    stability_by_variant: dict[str, float] = Field(default_factory=dict)
    human_intervention_rate: float = Field(ge=0, le=1)
    operational_failure_rate: float = Field(ge=0, le=1)
    structural_invariant_rate: float = Field(ge=0, le=1)
    structural_violations: list[str] = Field(default_factory=list)


class TaxonomySystemEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system_key: RecordId
    split: Literal["dev", "test"]
    metrics: TaxonomyEvaluationMetrics
    gate_status: Literal["pass", "fail", "incomplete"]
    gate_findings: list[str] = Field(default_factory=list)


class TaxonomyEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    run_id: RecordId
    evaluated_at: datetime
    corpus_id: RecordId
    pilot_corpus: Literal[True] = True
    dataset_hash: Sha256
    gold_hash: Sha256
    prediction_hash: Sha256
    policy_hash: Sha256
    frozen_policy_hash: Sha256
    gate_hash: Sha256
    gold_review_method: Literal["human_independent", "model_assisted_provisional"]
    calibration_gold_review_method: Literal["human_independent", "model_assisted_provisional"]
    output_manifest_hashes: dict[RecordId, Sha256] = Field(default_factory=dict)
    system_results: list[TaxonomySystemEvaluation] = Field(min_length=1)
    overall_status: Literal["pass", "fail", "incomplete"]
    aggregate_metrics: None = None
    decisions: list[dict[str, object]] = Field(default_factory=list)
    errors: list[dict[str, object]] = Field(default_factory=list)
    abstentions: list[dict[str, object]] = Field(default_factory=list)
    tree_diff: list[dict[str, object]] = Field(default_factory=list)
    total_cost_usd: float = Field(ge=0)
    total_latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> TaxonomyEvaluationResult:
        _require_aware(self.evaluated_at, "evaluation_time_timezone_required")
        systems = [(item.system_key, item.split) for item in self.system_results]
        if len(systems) != len(set(systems)):
            raise ValueError("duplicate_system_evaluation")
        statuses = {item.gate_status for item in self.system_results}
        has_unbound_prediction = any(item.get("error_code") == "prediction_without_gold" for item in self.errors)
        expected_status = (
            "fail"
            if "fail" in statuses or has_unbound_prediction
            else "incomplete"
            if "incomplete" in statuses
            else "pass"
        )
        if self.overall_status != expected_status:
            raise ValueError("evaluation_overall_status_mismatch")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class TaxonomyCalibrationNodeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    stable_key: StableKey
    display_name: str
    node_type: Literal["domain", "module", "capability"]
    parent_stable_key: StableKey | None = None
    definition: str
    scope_note: str
    evidence_count: int = Field(ge=0)


class TaxonomyCalibrationPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    system_id: UUID
    system_key: RecordId
    draft_manifest_hash: Sha256
    evaluation_run_hash: Sha256
    dataset_hash: Sha256
    gold_hash: Sha256
    prediction_hash: Sha256
    policy_hash: Sha256
    frozen_policy_hash: Sha256
    gate_hash: Sha256
    gold_review_method: Literal["human_independent"]
    calibration_gold_review_method: Literal["human_independent"]
    gate_status: Literal["pass", "fail", "incomplete"]
    review_scope: Literal["top_level_boundary_exception_sample"]
    prepared_by: str = Field(min_length=1, max_length=100)
    prepared_at: datetime
    total_node_count: int = Field(ge=1)
    top_level_nodes: list[TaxonomyCalibrationNodeSummary]
    critical_boundaries: list[TaxonomyCalibrationNodeSummary]
    exceptions: list[str]
    tree_diff: list[dict[str, object]]
    samples: list[dict[str, object]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_package(self) -> TaxonomyCalibrationPackage:
        _require_aware(self.prepared_at, "calibration_package_time_timezone_required")
        if self.gate_status != "pass":
            raise ValueError("calibration_package_gate_not_passed")
        if not self.top_level_nodes:
            raise ValueError("calibration_top_level_required")
        if any(item.parent_stable_key is not None for item in self.top_level_nodes):
            raise ValueError("calibration_top_level_invalid")
        sample_ids = [item.get("record_id") for item in self.samples]
        if any(not isinstance(item, str) or not item for item in sample_ids):
            raise ValueError("calibration_sample_record_id_required")
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("duplicate_calibration_sample")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class TaxonomyCalibrationReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    review_id: RecordId
    package_hash: Sha256
    draft_manifest_hash: Sha256
    evaluation_run_hash: Sha256
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=100)
    reviewed_at: datetime
    findings: list[str] = Field(min_length=1)
    rollback_plan: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_review(self) -> TaxonomyCalibrationReview:
        _require_aware(self.reviewed_at, "calibration_review_time_timezone_required")
        if len(self.findings) != len(set(self.findings)):
            raise ValueError("duplicate_calibration_finding")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class TaxonomyActivationAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    activation_allowed: Literal[True]
    package_hash: Sha256
    review_hash: Sha256
    draft_manifest_hash: Sha256
    review_id: RecordId
    reviewer: str
    reviewed_at: datetime
    rollback_plan: str
