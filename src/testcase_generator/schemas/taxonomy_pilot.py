"""真实 Taxonomy pilot 的冻结语料、运行台账和原始决议契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.testcase_generator.schemas.requirement_unit import RequirementUnitId
from src.testcase_generator.schemas.taxonomy import Sha256, StableKey
from src.testcase_generator.schemas.taxonomy_evaluation import ArtifactRef, RecordId
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolution

PilotCorpusSplit = Literal["bootstrap", "calibration", "test"]
PilotTransformationKind = Literal["chapter_reorder", "title_rewrite", "synonym", "multi_capability"]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, code: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)


class PilotSourceDocument(BaseModel):
    """操作者提供的原始文档位置；路径只用于冻结，不进入可共享产物。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    document_key: RecordId
    title: str = Field(min_length=1, max_length=500)
    document_id: UUID
    system_key: RecordId
    system_id: UUID
    split: PilotCorpusSplit
    source_path: str = Field(min_length=1, max_length=4_000)
    source_sha256: Sha256
    canonical_sha256: Sha256
    canonicalization_revision: str = Field(min_length=1, max_length=255)
    image_enrichment_revision: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_source_path(self) -> PilotSourceDocument:
        if not Path(self.source_path).expanduser().is_absolute():
            raise ValueError(f"pilot_source_path_must_be_absolute:{self.document_key}")
        return self


class PilotCorpusSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[3]
    corpus_id: RecordId
    created_at: datetime
    documents: list[PilotSourceDocument] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_corpus(self) -> PilotCorpusSpec:
        _require_aware(self.created_at, "pilot_corpus_created_at_timezone_required")
        keys = [item.document_key for item in self.documents]
        ids = [item.document_id for item in self.documents]
        hashes = [item.source_sha256 for item in self.documents]
        canonical_hashes = [item.canonical_sha256 for item in self.documents]
        paths = [str(Path(item.source_path).expanduser().resolve()) for item in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_pilot_document_key")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_pilot_document_id")
        if len(hashes) != len(set(hashes)):
            raise ValueError("pilot_document_content_hash_leakage")
        if len(canonical_hashes) != len(set(canonical_hashes)):
            raise ValueError("pilot_document_canonical_hash_leakage")
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate_pilot_source_path")

        systems: dict[str, tuple[UUID, set[str]]] = {}
        system_keys_by_id: dict[UUID, str] = {}
        for item in self.documents:
            system = systems.setdefault(item.system_key, (item.system_id, set()))
            if system[0] != item.system_id:
                raise ValueError(f"pilot_system_identity_conflict:{item.system_key}")
            existing_key = system_keys_by_id.setdefault(item.system_id, item.system_key)
            if existing_key != item.system_key:
                raise ValueError(f"pilot_system_id_alias_conflict:{item.system_id}")
            system[1].add(item.split)
        for system_key, (_, splits) in systems.items():
            if splits != {"bootstrap", "calibration", "test"}:
                raise ValueError(f"pilot_system_split_incomplete:{system_key}")
        return self

    @property
    def source_commitment_hash(self) -> str:
        return _source_commitment_hash(
            schema_version=self.schema_version,
            corpus_id=self.corpus_id,
            created_at=self.created_at,
            documents=[
                {
                    "document_key": item.document_key,
                    "title": item.title,
                    "document_id": str(item.document_id),
                    "system_key": item.system_key,
                    "system_id": str(item.system_id),
                    "split": item.split,
                    "source_sha256": item.source_sha256,
                    "canonical_sha256": item.canonical_sha256,
                    "canonicalization_revision": item.canonicalization_revision,
                    "image_enrichment_revision": item.image_enrichment_revision,
                }
                for item in self.documents
            ],
        )


class PilotFrozenDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    document_key: RecordId
    title: str = Field(min_length=1, max_length=500)
    document_id: UUID
    system_key: RecordId
    system_id: UUID
    split: PilotCorpusSplit
    raw_source: ArtifactRef
    source: ArtifactRef
    canonicalization_revision: str = Field(min_length=1, max_length=255)
    image_enrichment_revision: str = Field(min_length=1, max_length=255)


class PilotFrozenCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[3]
    corpus_id: RecordId
    created_at: datetime
    frozen_at: datetime
    source_commitment_hash: Sha256
    documents: list[PilotFrozenDocument] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_frozen_corpus(self) -> PilotFrozenCorpus:
        _require_aware(self.created_at, "pilot_corpus_created_at_timezone_required")
        _require_aware(self.frozen_at, "pilot_corpus_frozen_at_timezone_required")
        if self.frozen_at < self.created_at:
            raise ValueError("pilot_corpus_freeze_precedes_creation")
        keys = [item.document_key for item in self.documents]
        ids = [item.document_id for item in self.documents]
        raw_hashes = [item.raw_source.sha256 for item in self.documents]
        canonical_hashes = [item.source.sha256 for item in self.documents]
        paths = [path for item in self.documents for path in (item.raw_source.path, item.source.path)]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_frozen_pilot_document_key")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_frozen_pilot_document_id")
        if len(raw_hashes) != len(set(raw_hashes)):
            raise ValueError("frozen_pilot_document_content_hash_leakage")
        if len(canonical_hashes) != len(set(canonical_hashes)):
            raise ValueError("frozen_pilot_document_canonical_hash_leakage")
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate_frozen_pilot_source_path")
        systems: dict[str, tuple[UUID, set[str]]] = {}
        system_keys_by_id: dict[UUID, str] = {}
        for item in self.documents:
            system = systems.setdefault(item.system_key, (item.system_id, set()))
            if system[0] != item.system_id:
                raise ValueError(f"frozen_pilot_system_identity_conflict:{item.system_key}")
            existing_key = system_keys_by_id.setdefault(item.system_id, item.system_key)
            if existing_key != item.system_key:
                raise ValueError(f"frozen_pilot_system_id_alias_conflict:{item.system_id}")
            system[1].add(item.split)
        for system_key, (_, splits) in systems.items():
            if splits != {"bootstrap", "calibration", "test"}:
                raise ValueError(f"frozen_pilot_system_split_incomplete:{system_key}")
        expected = _source_commitment_hash(
            schema_version=self.schema_version,
            corpus_id=self.corpus_id,
            created_at=self.created_at,
            documents=[
                {
                    "document_key": item.document_key,
                    "title": item.title,
                    "document_id": str(item.document_id),
                    "system_key": item.system_key,
                    "system_id": str(item.system_id),
                    "split": item.split,
                    "source_sha256": item.raw_source.sha256,
                    "canonical_sha256": item.source.sha256,
                    "canonicalization_revision": item.canonicalization_revision,
                    "image_enrichment_revision": item.image_enrichment_revision,
                }
                for item in self.documents
            ],
        )
        if self.source_commitment_hash != expected:
            raise ValueError("pilot_source_commitment_mismatch")
        return self


class PilotRequirementExtractionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: ArtifactRef
    section_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    unit_count: int = Field(ge=0)
    atomic_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> PilotRequirementExtractionArtifact:
        if self.atomic_count > self.unit_count:
            raise ValueError("pilot_requirement_atomic_count_invalid")
        return self


class PilotRequirementExtractionCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    split: Literal["bootstrap", "calibration"]
    documents: dict[RecordId, PilotRequirementExtractionArtifact] = Field(min_length=1)


class PilotBootstrapIdentityDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_key: RecordId
    document_id: UUID
    system_key: RecordId
    system_id: UUID
    source: ArtifactRef
    requirement_units: ArtifactRef


class PilotBootstrapIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    artifact_kind: Literal["bootstrap_identity"]
    corpus_id: RecordId
    source_commitment_hash: Sha256
    bootstrap_policy_hash: Sha256
    resolution_policy_hash: Sha256
    runtime_manifest: ArtifactRef
    documents: list[PilotBootstrapIdentityDocument] = Field(min_length=1)
    prompt_revisions: dict[str, str] = Field(min_length=1)
    model_revisions: dict[str, str] = Field(min_length=1)
    bootstrap_hash: Sha256

    @model_validator(mode="after")
    def validate_identity(self) -> PilotBootstrapIdentity:
        document_keys = [item.document_key for item in self.documents]
        if document_keys != sorted(document_keys):
            raise ValueError("pilot_bootstrap_identity_documents_not_sorted")
        if len(document_keys) != len(set(document_keys)):
            raise ValueError("pilot_bootstrap_identity_document_duplicate")
        if any(not key.strip() or not value.strip() for key, value in self.prompt_revisions.items()):
            raise ValueError("pilot_bootstrap_identity_prompt_revision_empty")
        if any(not key.strip() or not value.strip() for key, value in self.model_revisions.items()):
            raise ValueError("pilot_bootstrap_identity_model_revision_empty")
        if self.bootstrap_hash != _canonical_hash(self.model_dump(mode="json", exclude={"bootstrap_hash"})):
            raise ValueError("pilot_bootstrap_identity_hash_mismatch")
        return self


class PilotBootstrapCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    bootstrap_hash: Sha256
    identity: ArtifactRef
    provisional_gold: ArtifactRef
    review_report: ArtifactRef
    results: dict[RecordId, ArtifactRef] = Field(min_length=1)
    output_manifests: dict[RecordId, ArtifactRef] = Field(min_length=1)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_system_sets(self) -> PilotBootstrapCompletionReceipt:
        systems = set(self.results)
        if systems != set(self.output_manifests) or systems != set(self.output_manifest_hashes):
            raise ValueError("pilot_bootstrap_receipt_systems_mismatch")
        return self


class PilotCalibrationResolutionCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    calibration_dataset_hash: Sha256
    dataset: ArtifactRef
    resolutions: ArtifactRef
    concept_refs: ArtifactRef
    predictions: ArtifactRef
    provisional_gold: ArtifactRef
    output_manifests: dict[RecordId, ArtifactRef] = Field(min_length=1)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_system_sets(self) -> PilotCalibrationResolutionCompletionReceipt:
        if set(self.output_manifests) != set(self.output_manifest_hashes):
            raise ValueError("pilot_calibration_receipt_systems_mismatch")
        return self


class PilotCalibrationPolicyCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    calibration_dataset_hash: Sha256
    frozen_policy_hash: Sha256
    minimum_precision: float = Field(ge=0, le=1)
    minimum_auto_decisions: int = Field(ge=1)
    frozen_policy: ArtifactRef
    independent_gold: ArtifactRef
    coverage_gold: ArtifactRef
    gold_attestation: ArtifactRef


class PilotSourceTransformationRecord(BaseModel):
    """预测前由人工按 source fact 冻结的语义不变关系。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    transformation_id: RecordId
    system_key: RecordId
    semantic_group_id: RecordId
    source_fact_id: RecordId
    variant_fact_id: RecordId
    kind: PilotTransformationKind
    transformation_revision: str = Field(min_length=1, max_length=255)
    source_quote_hash: Sha256
    variant_quote_hash: Sha256

    @model_validator(mode="after")
    def validate_transformation(self) -> PilotSourceTransformationRecord:
        if self.source_fact_id == self.variant_fact_id:
            raise ValueError("source_transformation_self_reference")
        if self.source_quote_hash == self.variant_quote_hash and self.kind != "chapter_reorder":
            raise ValueError("source_transformation_quote_unchanged")
        return self


class PilotSourceTransformationCommitment(BaseModel):
    """只绑定 source fact，不预知本次模型生成的 Requirement Unit 身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    corpus_id: RecordId
    source_commitment_hash: Sha256
    source_gold_sha256: Sha256
    projection_revision: str = Field(min_length=1, max_length=255)
    review_method: Literal["human_independent"] = "human_independent"
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_at: datetime
    records: list[PilotSourceTransformationRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_commitment(self) -> PilotSourceTransformationCommitment:
        _require_aware(self.reviewed_at, "source_transformation_review_time_timezone_required")
        identities = [item.transformation_id for item in self.records]
        variants = [item.variant_fact_id for item in self.records]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_source_transformation_id")
        if len(variants) != len(set(variants)):
            raise ValueError("duplicate_source_transformation_variant")
        source_facts = {item.source_fact_id for item in self.records}
        variant_facts = set(variants)
        if source_facts & variant_facts:
            raise ValueError("source_transformation_fact_role_conflict")
        groups: dict[str, tuple[str, str]] = {}
        source_groups: dict[str, tuple[str, str]] = {}
        for item in self.records:
            group = groups.setdefault(item.semantic_group_id, (item.system_key, item.source_fact_id))
            if group != (item.system_key, item.source_fact_id):
                raise ValueError(f"source_transformation_group_conflict:{item.semantic_group_id}")
            source_group = source_groups.setdefault(
                item.source_fact_id,
                (item.system_key, item.semantic_group_id),
            )
            if source_group != (item.system_key, item.semantic_group_id):
                raise ValueError(f"source_transformation_source_group_conflict:{item.source_fact_id}")
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["records"] = sorted(payload["records"], key=lambda item: item["transformation_id"])
        return _canonical_hash(payload)


class PilotLockedTestInputCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2, 3]
    source_gold_sha256: Sha256
    source_transformation_commitment_sha256: Sha256 | None = None
    evolution_policy_sha256: Sha256 | None = None
    gate_sha256: Sha256

    @model_validator(mode="after")
    def validate_commitment(self) -> PilotLockedTestInputCommitment:
        if self.schema_version == 1 and (
            self.source_transformation_commitment_sha256 is not None or self.evolution_policy_sha256 is not None
        ):
            raise ValueError("pilot_locked_test_v1_transformation_commitment_forbidden")
        if self.schema_version in {2, 3} and self.source_transformation_commitment_sha256 is None:
            raise ValueError("pilot_locked_test_v2_transformation_commitment_required")
        if self.schema_version == 2 and self.evolution_policy_sha256 is not None:
            raise ValueError("pilot_locked_test_v2_evolution_policy_forbidden")
        if self.schema_version == 3 and self.evolution_policy_sha256 is None:
            raise ValueError("pilot_locked_test_v3_evolution_policy_required")
        return self


class PilotLockedTestCompletionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1, 2, 3]
    test_dataset_hash: Sha256
    frozen_policy_hash: Sha256
    dataset: ArtifactRef
    requirement_extractions: dict[RecordId, PilotRequirementExtractionArtifact] = Field(min_length=1)
    resolutions: ArtifactRef
    concept_refs: ArtifactRef
    predictions: ArtifactRef
    source_gold: ArtifactRef
    source_transformation_commitment: ArtifactRef | None = None
    transformation_projection: ArtifactRef | None = None
    transformation_projection_revision: str | None = Field(default=None, min_length=1, max_length=255)
    evolution_policy: ArtifactRef | None = None
    evolutions: dict[RecordId, ArtifactRef] = Field(default_factory=dict)
    derived_gold: ArtifactRef
    source_coverage_metrics: ArtifactRef
    gate: ArtifactRef
    evaluation: ArtifactRef
    report: ArtifactRef
    output_manifests: dict[RecordId, ArtifactRef] = Field(min_length=1)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_system_sets(self) -> PilotLockedTestCompletionReceipt:
        systems = set(self.output_manifests)
        if systems != set(self.output_manifest_hashes):
            raise ValueError("pilot_locked_test_receipt_systems_mismatch")
        transformation_fields = (
            self.source_transformation_commitment,
            self.transformation_projection,
            self.transformation_projection_revision,
        )
        if self.schema_version == 1 and any(item is not None for item in transformation_fields):
            raise ValueError("pilot_locked_test_receipt_v1_transformation_fields_forbidden")
        if self.schema_version in {2, 3} and any(item is None for item in transformation_fields):
            raise ValueError("pilot_locked_test_receipt_v2_transformation_fields_required")
        if self.schema_version in {1, 2} and (self.evolution_policy is not None or self.evolutions):
            raise ValueError("pilot_locked_test_receipt_legacy_evolution_fields_forbidden")
        if self.schema_version == 3 and (self.evolution_policy is None or set(self.evolutions) != systems):
            raise ValueError("pilot_locked_test_receipt_v3_evolution_fields_required")
        return self


class PilotLockedTestFailureReceipt(BaseModel):
    """锁定测试终态失败收据；质量失败保留可重放证据，运行异常只暴露稳定类型。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1, 2, 3]
    failure_kind: Literal["source_coverage_quality_gate", "execution"]
    error_type: str = Field(min_length=1, max_length=255)
    test_dataset_hash: Sha256 | None = None
    frozen_policy_hash: Sha256 | None = None
    dataset: ArtifactRef | None = None
    requirement_extractions: dict[RecordId, PilotRequirementExtractionArtifact] = Field(default_factory=dict)
    resolutions: ArtifactRef | None = None
    concept_refs: ArtifactRef | None = None
    predictions: ArtifactRef | None = None
    source_gold: ArtifactRef | None = None
    source_transformation_commitment: ArtifactRef | None = None
    transformation_projection_revision: str | None = Field(default=None, min_length=1, max_length=255)
    evolution_policy: ArtifactRef | None = None
    evolutions: dict[RecordId, ArtifactRef] = Field(default_factory=dict)
    source_coverage_metrics: ArtifactRef | None = None
    gate: ArtifactRef | None = None
    report: ArtifactRef | None = None
    output_manifests: dict[RecordId, ArtifactRef] = Field(default_factory=dict)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_failure_evidence(self) -> PilotLockedTestFailureReceipt:
        quality_artifacts = (
            self.dataset,
            self.resolutions,
            self.concept_refs,
            self.predictions,
            self.source_gold,
            self.source_coverage_metrics,
            self.gate,
            self.report,
        )
        if self.failure_kind == "source_coverage_quality_gate":
            if (
                self.test_dataset_hash is None
                or self.frozen_policy_hash is None
                or not self.requirement_extractions
                or any(item is None for item in quality_artifacts)
                or not self.output_manifests
                or set(self.output_manifests) != set(self.output_manifest_hashes)
                or (
                    self.schema_version in {2, 3}
                    and (
                        self.source_transformation_commitment is None or self.transformation_projection_revision is None
                    )
                    or (
                        self.schema_version == 3
                        and (self.evolution_policy is None or set(self.evolutions) != set(self.output_manifests))
                    )
                )
            ):
                raise ValueError("pilot_locked_test_quality_failure_evidence_required")
            if (
                not self.findings
                or len(self.findings) != len(set(self.findings))
                or self.findings != sorted(self.findings)
            ):
                raise ValueError("pilot_locked_test_quality_failure_findings_invalid")
        elif (
            self.test_dataset_hash is not None
            or self.frozen_policy_hash is not None
            or self.requirement_extractions
            or any(item is not None for item in quality_artifacts)
            or self.output_manifests
            or self.output_manifest_hashes
            or self.findings
            or self.source_transformation_commitment is not None
            or self.transformation_projection_revision is not None
            or self.evolution_policy is not None
            or self.evolutions
        ):
            raise ValueError("pilot_locked_test_execution_failure_evidence_forbidden")
        if self.schema_version == 1 and (
            self.source_transformation_commitment is not None or self.transformation_projection_revision is not None
        ):
            raise ValueError("pilot_locked_test_failure_v1_transformation_fields_forbidden")
        if self.schema_version in {1, 2} and (self.evolution_policy is not None or self.evolutions):
            raise ValueError("pilot_locked_test_failure_legacy_evolution_fields_forbidden")
        return self


PilotEventType = Literal[
    "corpus_frozen",
    "requirement_extraction_started",
    "requirement_extraction_completed",
    "requirement_extraction_failed",
    "taxonomy_bootstrap_started",
    "taxonomy_bootstrap_completed",
    "taxonomy_bootstrap_failed",
    "calibration_resolution_started",
    "calibration_resolution_completed",
    "calibration_resolution_failed",
    "calibration_policy_freeze_started",
    "calibration_policy_freeze_completed",
    "calibration_policy_freeze_failed",
    "locked_test_started",
    "locked_test_completed",
    "locked_test_failed",
]


class PilotLedgerEvent(BaseModel):
    """本地追加式证据；哈希链能发现篡改，但不替代可信身份和远端审计。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    sequence: int = Field(ge=1)
    event_id: RecordId
    event_type: PilotEventType
    occurred_at: datetime
    corpus_id: RecordId
    source_commitment_hash: Sha256
    run_id: RecordId
    actor: str = Field(min_length=1, max_length=100)
    payload: dict[str, object] = Field(default_factory=dict)
    previous_event_hash: Sha256 | None = None
    event_hash: Sha256

    @model_validator(mode="after")
    def validate_event(self) -> PilotLedgerEvent:
        _require_aware(self.occurred_at, "pilot_event_time_timezone_required")
        if self.event_hash != pilot_ledger_event_hash(self):
            raise ValueError("pilot_ledger_event_hash_mismatch")
        return self


class PilotResolutionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    document_key: RecordId
    system_key: RecordId
    split: Literal["dev", "test"]
    requirement_unit_id: RequirementUnitId
    latency_ms: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    resolution: TaxonomyResolution


class PilotConceptRef(BaseModel):
    """把 concept UUID 同时绑定到系统与 stable key，防止同名 key 掩盖跨系统引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    system_key: RecordId
    stable_key: StableKey


class PilotConceptRefEntry(PilotConceptRef):
    concept_id: UUID


class PilotConceptRefSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    records: list[PilotConceptRefEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_records(self) -> PilotConceptRefSet:
        concept_ids = [item.concept_id for item in self.records]
        identities = [(item.system_key, item.stable_key) for item in self.records]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("pilot_concept_ref_id_duplicate")
        if len(identities) != len(set(identities)):
            raise ValueError("pilot_concept_ref_identity_duplicate")
        return self

    @property
    def by_concept_id(self) -> dict[UUID, PilotConceptRef]:
        return {
            item.concept_id: PilotConceptRef(system_key=item.system_key, stable_key=item.stable_key)
            for item in self.records
        }


class PilotTaxonomyExpectation(BaseModel):
    """锁定测试在预测前冻结的业务标签；不包含本次模型生成的 unit/record 身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

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
    eligible_for_auto: bool = True

    @model_validator(mode="after")
    def validate_expectation(self) -> PilotTaxonomyExpectation:
        for values, code in (
            (self.acceptable_primary_stable_keys, "pilot_expectation_duplicate_acceptable_primary"),
            (self.expected_related_stable_keys, "pilot_expectation_duplicate_related"),
            (self.acceptable_new_node_stable_keys, "pilot_expectation_duplicate_acceptable_new_node"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(code)
        canonical_paths = [tuple(path) for path in self.acceptable_paths]
        if len(canonical_paths) != len(set(canonical_paths)):
            raise ValueError("pilot_expectation_duplicate_acceptable_path")
        if self.expected_disposition == "reuse":
            if self.expected_primary_stable_key is None or self.expected_new_node_stable_key is not None:
                raise ValueError("pilot_expectation_reuse_target_invalid")
        elif self.expected_disposition == "new_node":
            if self.expected_new_node_stable_key is None or self.expected_primary_stable_key is not None:
                raise ValueError("pilot_expectation_new_node_target_invalid")
        elif self.expected_primary_stable_key is not None or self.expected_new_node_stable_key is not None:
            raise ValueError("pilot_expectation_abstain_target_forbidden")
        return self


class PilotCoverageGoldFact(BaseModel):
    """人工从一个源 chunk 识别出的原子事实；允许显式记录漏抽。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    fact_id: RecordId
    source_quote: str = Field(min_length=1)
    source_quote_hash: Sha256
    statement: str = Field(min_length=1)
    matched_requirement_unit_id: RequirementUnitId | None = None
    taxonomy_expectation: PilotTaxonomyExpectation | None = None

    @model_validator(mode="after")
    def validate_quote_hash(self) -> PilotCoverageGoldFact:
        if hashlib.sha256(self.source_quote.encode("utf-8")).hexdigest() != self.source_quote_hash:
            raise ValueError("pilot_coverage_gold_quote_hash_mismatch")
        return self


class PilotCoverageGoldRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    coverage_id: str = Field(pattern=r"^rc_[0-9a-f]{64}$")
    document_key: RecordId
    system_key: RecordId
    split: Literal["calibration", "test"]
    source_ref: str = Field(min_length=1, max_length=1_000)
    content_hash: Sha256
    expected_disposition: Literal[
        "requirements_present",
        "no_requirement",
        "excluded_non_spec",
        "empty_section",
    ]
    facts: list[PilotCoverageGoldFact] = Field(default_factory=list)
    review_note: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_disposition(self) -> PilotCoverageGoldRecord:
        fact_ids = [item.fact_id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("pilot_coverage_gold_fact_duplicate")
        matched_ids = [item.matched_requirement_unit_id for item in self.facts if item.matched_requirement_unit_id]
        if len(matched_ids) != len(set(matched_ids)):
            raise ValueError("pilot_coverage_gold_unit_match_duplicate")
        if self.expected_disposition == "requirements_present":
            if not self.facts:
                raise ValueError("pilot_coverage_gold_facts_required")
        elif self.facts:
            raise ValueError("pilot_coverage_gold_facts_forbidden")
        return self


class PilotCoverageGoldSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1, 2]
    corpus_id: RecordId
    dataset_hash: Sha256 | None = None
    source_commitment_hash: Sha256 | None = None
    review_method: Literal["human_independent"] = "human_independent"
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_at: datetime
    records: list[PilotCoverageGoldRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gold_set(self) -> PilotCoverageGoldSet:
        _require_aware(self.reviewed_at, "pilot_coverage_gold_review_time_timezone_required")
        coverage_ids = [item.coverage_id for item in self.records]
        if len(coverage_ids) != len(set(coverage_ids)):
            raise ValueError("pilot_coverage_gold_record_duplicate")
        facts_by_id: dict[str, dict[str, object]] = {}
        fact_documents: dict[str, str] = {}
        for record in self.records:
            for fact in record.facts:
                owner = fact_documents.setdefault(fact.fact_id, record.document_key)
                if owner != record.document_key:
                    raise ValueError("pilot_coverage_gold_fact_cross_document")
                payload = fact.model_dump(mode="json")
                existing = facts_by_id.setdefault(fact.fact_id, payload)
                if existing != payload:
                    raise ValueError("pilot_coverage_gold_fact_identity_conflict")
        if len({item.split for item in self.records}) != 1:
            raise ValueError("pilot_coverage_gold_mixed_splits")
        split = self.records[0].split
        if self.schema_version == 1:
            if self.dataset_hash is None or self.source_commitment_hash is not None:
                raise ValueError("pilot_coverage_gold_v1_dataset_binding_invalid")
        elif self.dataset_hash is not None or self.source_commitment_hash is None:
            raise ValueError("pilot_coverage_gold_v2_source_binding_invalid")
        if split == "calibration" and self.schema_version != 1:
            raise ValueError("pilot_coverage_gold_calibration_schema_invalid")
        if split == "test" and self.schema_version != 2:
            raise ValueError("pilot_coverage_gold_test_schema_invalid")
        if split == "calibration" and any(
            fact.taxonomy_expectation is not None for record in self.records for fact in record.facts
        ):
            raise ValueError("pilot_calibration_coverage_taxonomy_expectation_forbidden")
        if split == "test" and any(
            fact.taxonomy_expectation is None or fact.matched_requirement_unit_id is not None
            for record in self.records
            for fact in record.facts
        ):
            raise ValueError("pilot_locked_test_gold_must_be_hidden_from_extraction")
        return self

    @property
    def canonical_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["records"] = sorted(payload["records"], key=lambda item: item["coverage_id"])
        return _canonical_hash(payload)


class PilotGoldReviewAttestation(BaseModel):
    """把模型预标、独立人工 gold 与审核身份绑定；本地身份仍不等同可信签名。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    corpus_id: RecordId
    provisional_dataset_hash: Sha256
    independent_dataset_hash: Sha256
    provisional_gold_hash: Sha256
    independent_gold_hash: Sha256
    independent_coverage_dataset_hash: Sha256
    independent_coverage_gold_hash: Sha256
    provisional_reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_at: datetime
    coverage_reviewed_by: str = Field(min_length=1, max_length=100)
    coverage_reviewed_at: datetime
    review_method: Literal["human_independent"] = "human_independent"

    @model_validator(mode="after")
    def validate_attestation(self) -> PilotGoldReviewAttestation:
        _require_aware(self.reviewed_at, "pilot_gold_attestation_time_timezone_required")
        _require_aware(self.coverage_reviewed_at, "pilot_coverage_attestation_time_timezone_required")
        provisional_reviewer = self.provisional_reviewed_by.casefold()
        if provisional_reviewer in {self.reviewed_by.casefold(), self.coverage_reviewed_by.casefold()}:
            raise ValueError("pilot_gold_reviewer_not_independent")
        if self.provisional_gold_hash == self.independent_gold_hash:
            raise ValueError("pilot_gold_attestation_artifacts_not_distinct")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class PilotResolutionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal[1]
    run_id: RecordId
    generated_at: datetime
    dataset_hash: Sha256
    policy_hash: Sha256
    frozen_policy_hash: Sha256 | None = None
    prompt_revisions: dict[str, str] = Field(min_length=1)
    model_revisions: dict[str, str] = Field(min_length=1)
    taxonomy_version_ids: dict[RecordId, UUID] = Field(min_length=1)
    output_manifest_hashes: dict[RecordId, Sha256] = Field(min_length=1)
    records: list[PilotResolutionRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_resolution_set(self) -> PilotResolutionSet:
        _require_aware(self.generated_at, "pilot_resolution_time_timezone_required")
        identities = [(item.document_key, item.requirement_unit_id) for item in self.records]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate_pilot_resolution_unit")
        splits = {item.split for item in self.records}
        if len(splits) != 1:
            raise ValueError("pilot_resolution_mixed_splits")
        systems = {item.system_key for item in self.records}
        if set(self.taxonomy_version_ids) != systems:
            raise ValueError("pilot_resolution_taxonomy_versions_incomplete")
        if set(self.output_manifest_hashes) != systems:
            raise ValueError("pilot_resolution_manifest_hashes_incomplete")
        if any(not key.strip() or not value.strip() for key, value in self.prompt_revisions.items()):
            raise ValueError("pilot_resolution_prompt_revision_empty")
        if any(not key.strip() or not value.strip() for key, value in self.model_revisions.items()):
            raise ValueError("pilot_resolution_model_revision_empty")
        if splits == {"test"} and self.frozen_policy_hash is None:
            raise ValueError("pilot_test_resolution_frozen_policy_required")
        if splits == {"dev"} and self.frozen_policy_hash is not None:
            raise ValueError("pilot_dev_resolution_frozen_policy_forbidden")
        return self


def pilot_ledger_event_hash(event: PilotLedgerEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"event_hash"})
    return _canonical_hash(payload)


def build_pilot_ledger_event(
    *,
    sequence: int,
    event_id: str,
    event_type: PilotEventType,
    occurred_at: datetime,
    corpus_id: str,
    source_commitment_hash: str,
    run_id: str,
    actor: str,
    payload: dict[str, object],
    previous_event_hash: str | None,
) -> PilotLedgerEvent:
    draft = PilotLedgerEvent.model_construct(
        schema_version=1,
        sequence=sequence,
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        corpus_id=corpus_id,
        source_commitment_hash=source_commitment_hash,
        run_id=run_id,
        actor=actor,
        payload=payload,
        previous_event_hash=previous_event_hash,
        event_hash="0" * 64,
    )
    return PilotLedgerEvent.model_validate(
        {**draft.model_dump(mode="json", exclude={"event_hash"}), "event_hash": pilot_ledger_event_hash(draft)}
    )


def _source_commitment_hash(
    *,
    schema_version: int,
    corpus_id: str,
    created_at: datetime,
    documents: list[dict[str, object]],
) -> str:
    return _canonical_hash(
        {
            "schema_version": schema_version,
            "corpus_id": corpus_id,
            "created_at": created_at.isoformat(),
            "documents": sorted(documents, key=lambda item: str(item["document_key"])),
        }
    )
