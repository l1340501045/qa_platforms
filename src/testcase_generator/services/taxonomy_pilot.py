"""Taxonomy 真实 pilot 的离线冻结、追加式台账与机械投影。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from src.knowledge_base.services.parsers.markdown_parser import (
    MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
    MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
    canonicalize_markdown,
)
from src.testcase_generator.schemas.requirement_unit import RequirementUnit
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest, TaxonomyNodeManifest
from src.testcase_generator.schemas.taxonomy_evaluation import (
    ArtifactRef,
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
    TaxonomyEvaluationResult,
    TaxonomyFrozenPolicy,
    TaxonomyGoldNode,
    TaxonomyGoldRecord,
    TaxonomyGoldSet,
    TaxonomyKnownNode,
    TaxonomyPredictionRecord,
    TaxonomyPredictionSet,
    TaxonomyProposedNode,
    TaxonomyTransformationRecord,
    TaxonomyTransformationSet,
)
from src.testcase_generator.schemas.taxonomy_pilot import (
    PilotBootstrapCompletionReceipt,
    PilotBootstrapIdentity,
    PilotBootstrapIdentityDocument,
    PilotCalibrationPolicyCompletionReceipt,
    PilotCalibrationResolutionCompletionReceipt,
    PilotConceptRef,
    PilotConceptRefSet,
    PilotCorpusSpec,
    PilotCoverageGoldFact,
    PilotCoverageGoldSet,
    PilotEventType,
    PilotFrozenCorpus,
    PilotFrozenDocument,
    PilotGoldReviewAttestation,
    PilotLedgerEvent,
    PilotLockedTestCompletionReceipt,
    PilotLockedTestFailureReceipt,
    PilotLockedTestInputCommitment,
    PilotRequirementExtractionArtifact,
    PilotRequirementExtractionCompletionReceipt,
    PilotResolutionSet,
    PilotSourceTransformationCommitment,
    build_pilot_ledger_event,
)
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy
from src.testcase_generator.services.requirement_unit_service import (
    RequirementChunkCoverage,
    RequirementUnitExtractionResult,
)
from src.testcase_generator.services.taxonomy_bootstrap import (
    TaxonomyBootstrapPolicy,
    TaxonomyBootstrapResult,
)
from src.testcase_generator.services.taxonomy_evaluation import (
    calibrate_resolution_policy,
    evaluate_taxonomy_generalization,
    load_prediction_output_manifests,
    load_requirement_unit_index,
    render_taxonomy_evaluation_report,
    validate_evaluation_artifact_hashes,
)
from src.testcase_generator.services.taxonomy_evolution import (
    TaxonomyEvolutionOperation,
    TaxonomyEvolutionPolicy,
    TaxonomyEvolutionResult,
    validate_taxonomy_evolution_result_replay,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash
from src.testcase_generator.stages.parse.node import extract_document_inventory_sections


class PilotArtifactError(RuntimeError):
    pass


class LockedTestAlreadyConsumedError(PilotArtifactError):
    pass


PILOT_TRANSFORMATION_PROJECTION_REVISION = "source-fact-unit-projection-v1"
PILOT_MINIMUM_SEMANTIC_STABILITY = 0.95
_LOCKED_TEST_DATASET_SCHEMA_BY_RECEIPT_SCHEMA = {1: 2, 2: 3, 3: 3}


def validate_pilot_locked_test_gate(gate: TaxonomyEvaluationGate) -> None:
    if not gate.require_independent_gold:
        raise PilotArtifactError("pilot_locked_test_independent_gold_required")
    if not gate.require_complete_corpus:
        raise PilotArtifactError("pilot_locked_test_complete_corpus_required")
    if not gate.require_reuse_baseline:
        raise PilotArtifactError("pilot_locked_test_reuse_baseline_required")
    if not gate.require_new_node_baseline:
        raise PilotArtifactError("pilot_locked_test_new_node_baseline_required")
    if not gate.require_operational_thresholds:
        raise PilotArtifactError("pilot_locked_test_operational_thresholds_required")
    operational_thresholds = (
        (
            gate.minimum_expected_reuse_coverage,
            "pilot_locked_test_reuse_coverage_threshold_required",
        ),
        (
            gate.minimum_new_node_precision,
            "pilot_locked_test_new_node_precision_threshold_required",
        ),
        (
            gate.minimum_new_node_recall,
            "pilot_locked_test_new_node_recall_threshold_required",
        ),
        (
            gate.minimum_proposal_operation_type_accuracy,
            "pilot_locked_test_operation_type_threshold_required",
        ),
        (
            gate.maximum_human_intervention_rate,
            "pilot_locked_test_human_intervention_threshold_required",
        ),
    )
    for value, error in operational_thresholds:
        if value is None:
            raise PilotArtifactError(error)
    if gate.minimum_reuse_precision < 0.95:
        raise PilotArtifactError("pilot_locked_test_reuse_precision_gate_too_low")
    if gate.minimum_hierarchical_path_accuracy < 0.95:
        raise PilotArtifactError("pilot_locked_test_path_accuracy_gate_too_low")
    if gate.minimum_semantic_stability < PILOT_MINIMUM_SEMANTIC_STABILITY:
        raise PilotArtifactError("pilot_locked_test_semantic_stability_gate_too_low")
    if gate.maximum_duplicate_node_rate > 0:
        raise PilotArtifactError("pilot_locked_test_duplicate_node_gate_too_weak")
    if gate.maximum_unsupported_node_rate > 0:
        raise PilotArtifactError("pilot_locked_test_unsupported_node_gate_too_weak")
    if gate.minimum_structural_invariant_rate < 1:
        raise PilotArtifactError("pilot_locked_test_structural_invariant_gate_too_low")
    if gate.maximum_operational_failure_rate > 0:
        raise PilotArtifactError("pilot_locked_test_operational_failure_gate_too_weak")


_STAGE_TERMINALS: dict[PilotEventType, frozenset[PilotEventType]] = {
    "requirement_extraction_started": frozenset({"requirement_extraction_completed", "requirement_extraction_failed"}),
    "taxonomy_bootstrap_started": frozenset({"taxonomy_bootstrap_completed", "taxonomy_bootstrap_failed"}),
    "calibration_resolution_started": frozenset({"calibration_resolution_completed", "calibration_resolution_failed"}),
    "calibration_policy_freeze_started": frozenset(
        {"calibration_policy_freeze_completed", "calibration_policy_freeze_failed"}
    ),
    "locked_test_started": frozenset({"locked_test_completed", "locked_test_failed"}),
}
_TERMINAL_START = {terminal: started for started, terminals in _STAGE_TERMINALS.items() for terminal in terminals}
_SINGLETON_STAGE_COMPLETIONS: dict[PilotEventType, PilotEventType] = {
    "taxonomy_bootstrap_started": "taxonomy_bootstrap_completed",
    "calibration_resolution_started": "calibration_resolution_completed",
    "calibration_policy_freeze_started": "calibration_policy_freeze_completed",
}


class PilotRunLedger:
    """进程安全的本地 JSONL 哈希链；用于 pilot 证据，不宣称不可篡改。"""

    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(f"{path.name}.lock")

    def read_events(self) -> list[PilotLedgerEvent]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            try:
                content = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
                return self._parse(content)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        *,
        event_type: PilotEventType,
        corpus: PilotFrozenCorpus,
        run_id: str,
        actor: str,
        payload: dict[str, object] | None = None,
        occurred_at: datetime | None = None,
    ) -> PilotLedgerEvent:
        run_id = run_id.strip()
        actor = actor.strip()
        event_payload = payload or {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                content = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
                events = self._parse(content)
                resolved_occurred_at = occurred_at or datetime.now(timezone.utc)
                self._validate_transition(
                    events,
                    event_type=event_type,
                    run_id=run_id,
                    payload=event_payload,
                    corpus_id=corpus.corpus_id,
                    source_commitment_hash=corpus.source_commitment_hash,
                    occurred_at=resolved_occurred_at,
                )
                self._validate_completion_receipt(event_type, event_payload)

                previous = events[-1] if events else None
                event = build_pilot_ledger_event(
                    sequence=len(events) + 1,
                    event_id=f"evt-{uuid4().hex}",
                    event_type=event_type,
                    occurred_at=resolved_occurred_at,
                    corpus_id=corpus.corpus_id,
                    source_commitment_hash=corpus.source_commitment_hash,
                    run_id=run_id,
                    actor=actor,
                    payload=event_payload,
                    previous_event_hash=previous.event_hash if previous else None,
                )
                prefix = content if not content or content.endswith("\n") else content + "\n"
                updated = (
                    prefix
                    + json.dumps(
                        event.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                temporary = self.path.parent / f".{self.path.name}.tmp-{uuid4().hex}"
                try:
                    with temporary.open("x", encoding="utf-8") as handle:
                        handle.write(updated)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.path)
                    directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                finally:
                    temporary.unlink(missing_ok=True)
                return event
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _parse(content: str) -> list[PilotLedgerEvent]:
        events: list[PilotLedgerEvent] = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                event = PilotLedgerEvent.model_validate_json(raw_line)
            except Exception as exc:  # noqa: BLE001 - 对外只暴露固定审计错误
                raise PilotArtifactError(f"pilot_ledger_event_invalid:{line_number}") from exc
            expected_sequence = len(events) + 1
            expected_previous = events[-1].event_hash if events else None
            if event.sequence != expected_sequence:
                raise PilotArtifactError(f"pilot_ledger_sequence_invalid:{line_number}")
            if event.previous_event_hash != expected_previous:
                raise PilotArtifactError(f"pilot_ledger_chain_invalid:{line_number}")
            PilotRunLedger._validate_transition(
                events,
                event_type=event.event_type,
                run_id=event.run_id,
                payload=event.payload,
                corpus_id=event.corpus_id,
                source_commitment_hash=event.source_commitment_hash,
                occurred_at=event.occurred_at,
            )
            PilotRunLedger._validate_completion_receipt(event.event_type, event.payload)
            events.append(event)
        return events

    @staticmethod
    def _validate_transition(
        events: list[PilotLedgerEvent],
        *,
        event_type: PilotEventType,
        run_id: str,
        payload: dict[str, object],
        corpus_id: str,
        source_commitment_hash: str,
        occurred_at: datetime,
    ) -> None:
        if event_type == "corpus_frozen":
            if events:
                raise PilotArtifactError("pilot_ledger_duplicate_corpus_event")
        elif not events or events[0].event_type != "corpus_frozen":
            raise PilotArtifactError("pilot_ledger_corpus_event_missing")
        if events and any(
            event.corpus_id != corpus_id or event.source_commitment_hash != source_commitment_hash for event in events
        ):
            raise PilotArtifactError("pilot_ledger_corpus_mismatch")
        if event_type in _STAGE_TERMINALS and any(event.run_id == run_id for event in events):
            raise PilotArtifactError(f"pilot_run_id_already_used:{run_id}")
        singleton_completion = _SINGLETON_STAGE_COMPLETIONS.get(event_type)
        if singleton_completion is not None and any(event.event_type == singleton_completion for event in events):
            raise PilotArtifactError(f"pilot_stage_already_completed:{event_type}")
        if event_type.startswith("requirement_extraction_"):
            split = payload.get("split")
            if split not in {"bootstrap", "calibration"}:
                raise PilotArtifactError("pilot_requirement_split_invalid")
            if event_type in {"requirement_extraction_started", "requirement_extraction_completed"} and any(
                event.event_type == "requirement_extraction_completed" and event.payload.get("split") == split
                for event in events
            ):
                raise PilotArtifactError(f"pilot_requirement_split_already_completed:{split}")
        if event_type in _TERMINAL_START:
            started_type = _TERMINAL_START[event_type]
            matching_start = [event for event in events if event.run_id == run_id and event.event_type == started_type]
            if len(matching_start) != 1:
                raise PilotArtifactError(f"pilot_stage_terminal_without_start:{run_id}")
            if event_type.startswith("requirement_extraction_") and matching_start[0].payload.get(
                "split"
            ) != payload.get("split"):
                raise PilotArtifactError(f"pilot_requirement_terminal_split_mismatch:{run_id}")
            if any(event.run_id == run_id and event.event_type in _STAGE_TERMINALS[started_type] for event in events):
                raise PilotArtifactError(f"pilot_stage_already_terminal:{run_id}")
        if event_type == "locked_test_started" and any(event.event_type == "locked_test_started" for event in events):
            raise LockedTestAlreadyConsumedError("locked_test_already_consumed")
        if events and occurred_at < events[-1].occurred_at:
            raise PilotArtifactError("pilot_ledger_time_regression")

    @staticmethod
    def _validate_completion_receipt(event_type: PilotEventType, payload: dict[str, object]) -> None:
        receipt_model = cast(
            type[BaseModel] | None,
            {
                "requirement_extraction_completed": PilotRequirementExtractionCompletionReceipt,
                "taxonomy_bootstrap_completed": PilotBootstrapCompletionReceipt,
                "calibration_resolution_completed": PilotCalibrationResolutionCompletionReceipt,
                "calibration_policy_freeze_completed": PilotCalibrationPolicyCompletionReceipt,
                "locked_test_completed": PilotLockedTestCompletionReceipt,
                "locked_test_failed": PilotLockedTestFailureReceipt,
            }.get(event_type),
        )
        if receipt_model is None:
            return
        try:
            receipt_model.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - 台账边界统一转为稳定错误码
            raise PilotArtifactError(f"pilot_completion_receipt_invalid:{event_type}") from exc


def freeze_pilot_corpus(
    *,
    spec: PilotCorpusSpec,
    output_dir: Path,
    actor: str,
    run_id: str,
    frozen_at: datetime | None = None,
) -> PilotFrozenCorpus:
    """把外部 PRD 复制为只读快照；目标目录必须全新，避免覆盖历史 run。"""

    actor = actor.strip()
    if not actor:
        raise ValueError("pilot_actor_required")
    if output_dir.exists():
        raise PilotArtifactError("pilot_output_already_exists")

    resolved_time = frozen_at or datetime.now(timezone.utc)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.parent / f".{output_dir.name}.tmp-{uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        frozen_documents: list[PilotFrozenDocument] = []
        for document in sorted(spec.documents, key=lambda item: item.document_key):
            source_path = Path(document.source_path).expanduser().resolve()
            if not source_path.is_file():
                raise PilotArtifactError(f"pilot_source_not_found:{document.document_key}")
            if _file_hash(source_path) != document.source_sha256:
                raise PilotArtifactError(f"pilot_source_hash_mismatch:{document.document_key}")

            raw_text = source_path.read_text(encoding="utf-8")
            canonical = canonicalize_markdown(raw_text)
            if document.canonicalization_revision != MARKDOWN_CANONICAL_SNAPSHOT_REVISION:
                raise PilotArtifactError(f"pilot_canonicalization_revision_mismatch:{document.document_key}")
            if document.image_enrichment_revision != MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION:
                raise PilotArtifactError(f"pilot_image_enrichment_revision_mismatch:{document.document_key}")
            if canonical.canonical_sha256 != document.canonical_sha256:
                raise PilotArtifactError(f"pilot_canonical_snapshot_hash_mismatch:{document.document_key}")

            scope = "locked-test" if document.split == "test" else document.split
            raw_relative_path = Path("sources") / scope / f"{document.document_key}.md"
            raw_target_path = temporary / raw_relative_path
            raw_target_path.parent.mkdir(parents=True, exist_ok=True)
            with source_path.open("rb") as source, raw_target_path.open("xb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            if _file_hash(raw_target_path) != document.source_sha256:
                raise PilotArtifactError(f"pilot_snapshot_hash_mismatch:{document.document_key}")

            relative_path = Path("snapshots") / scope / f"{document.document_key}.md"
            target_path = temporary / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("x", encoding="utf-8") as target:
                target.write(canonical.content)
                target.flush()
                os.fsync(target.fileno())
            if _file_hash(target_path) != document.canonical_sha256:
                raise PilotArtifactError(f"pilot_canonical_snapshot_hash_mismatch:{document.document_key}")
            mode = 0o400 if document.split == "test" else 0o600
            raw_target_path.chmod(mode)
            target_path.chmod(mode)
            frozen_documents.append(
                PilotFrozenDocument(
                    document_key=document.document_key,
                    title=document.title,
                    document_id=document.document_id,
                    system_key=document.system_key,
                    system_id=document.system_id,
                    split=document.split,
                    raw_source={"path": str(raw_relative_path), "sha256": document.source_sha256},
                    source={"path": str(relative_path), "sha256": document.canonical_sha256},
                    canonicalization_revision=document.canonicalization_revision,
                    image_enrichment_revision=document.image_enrichment_revision,
                )
            )

        corpus = PilotFrozenCorpus(
            schema_version=spec.schema_version,
            corpus_id=spec.corpus_id,
            created_at=spec.created_at,
            frozen_at=resolved_time,
            source_commitment_hash=spec.source_commitment_hash,
            documents=frozen_documents,
        )
        _write_json_once(temporary / "frozen-corpus.json", corpus)
        PilotRunLedger(temporary / "run-ledger.jsonl").append(
            event_type="corpus_frozen",
            corpus=corpus,
            run_id=run_id,
            actor=actor,
            payload={
                "document_count": len(corpus.documents),
                "bootstrap_count": sum(item.split == "bootstrap" for item in corpus.documents),
                "calibration_count": sum(item.split == "calibration" for item in corpus.documents),
                "locked_test_count": sum(item.split == "test" for item in corpus.documents),
            },
            occurred_at=resolved_time,
        )
        temporary.replace(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return corpus


def load_frozen_corpus(root: Path) -> PilotFrozenCorpus:
    corpus = PilotFrozenCorpus.model_validate_json((root / "frozen-corpus.json").read_text(encoding="utf-8"))
    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    if (
        not events
        or events[0].event_type != "corpus_frozen"
        or events[0].corpus_id != corpus.corpus_id
        or events[0].source_commitment_hash != corpus.source_commitment_hash
        or events[0].occurred_at != corpus.frozen_at
    ):
        raise PilotArtifactError("pilot_frozen_corpus_ledger_binding_invalid")
    return corpus


def load_split_snapshots(
    *,
    corpus: PilotFrozenCorpus,
    root: Path,
    split: str,
    allow_locked_test: bool = False,
    reader: Callable[[Path], str] | None = None,
) -> dict[str, str]:
    """只读取请求 split；test 必须显式解锁，防止 dev 代码路径误看测试输入。"""

    if split not in {"bootstrap", "calibration", "test"}:
        raise ValueError("pilot_split_invalid")
    if split == "test" and not allow_locked_test:
        raise PilotArtifactError("locked_test_read_not_authorized")
    read_text = reader or (lambda path: path.read_text(encoding="utf-8"))
    snapshots: dict[str, str] = {}
    for document in sorted(corpus.documents, key=lambda item: item.document_key):
        if document.split != split:
            continue
        path = _resolve_artifact(root, document.source.path)
        if _file_hash(path) != document.source.sha256:
            raise PilotArtifactError(f"pilot_snapshot_hash_mismatch:{document.document_key}")
        text = read_text(path)
        snapshots[document.document_key] = text
    return snapshots


def _inventory_section_count(*, document: PilotFrozenDocument, snapshot: str) -> int:
    return len(
        extract_document_inventory_sections(
            document_id=document.document_id,
            title=document.title,
            content=snapshot,
            doc_type="prd",
        )
    )


def verify_pilot_requirement_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    splits: set[str] | None = None,
) -> dict[str, Path]:
    """按完成事件核验不可变 run 产物；只接触请求的 split，test 不做语义解析。"""

    selected_splits = splits or {"bootstrap", "calibration"}
    if not selected_splits or not selected_splits <= {"bootstrap", "calibration"}:
        raise ValueError("pilot_requirement_splits_invalid")
    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    verified: dict[str, Path] = {}
    for split in sorted(selected_splits):
        snapshots = load_split_snapshots(corpus=corpus, root=root, split=split)
        completions = [
            event
            for event in events
            if event.event_type == "requirement_extraction_completed" and event.payload.get("split") == split
        ]
        if len(completions) != 1:
            raise PilotArtifactError(f"pilot_requirement_completion_event_invalid:{split}")
        try:
            receipt = PilotRequirementExtractionCompletionReceipt.model_validate(completions[0].payload)
        except Exception:  # noqa: BLE001 - 台账完成事件必须使用同一强类型契约
            raise PilotArtifactError(f"pilot_requirement_completion_payload_invalid:{split}")
        if receipt.split != split:
            raise PilotArtifactError(f"pilot_requirement_completion_payload_invalid:{split}")

        expected_documents = {item.document_key for item in corpus.documents if item.split == split}
        if set(receipt.documents) != expected_documents:
            raise PilotArtifactError(f"pilot_requirement_completion_documents_invalid:{split}")
        run_root = (root / "runs" / "requirement-extraction" / completions[0].run_id).resolve()
        for document_key in sorted(expected_documents):
            summary = receipt.documents[document_key]
            expected_hash = summary.artifact.sha256
            artifact_path = summary.artifact.path
            if Path(artifact_path).is_absolute():
                raise PilotArtifactError(f"pilot_requirement_completion_path_invalid:{document_key}")
            path = _resolve_artifact(root, artifact_path)
            if path.parent != run_root or path.name != f"{document_key}.json":
                raise PilotArtifactError(f"pilot_requirement_completion_path_invalid:{document_key}")
            if not path.is_file() or _file_hash(path) != expected_hash:
                raise PilotArtifactError(f"pilot_requirement_artifact_hash_mismatch:{document_key}")
            try:
                extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - completion 必须绑定真实强类型产物
                raise PilotArtifactError(f"pilot_requirement_artifact_schema_invalid:{document_key}") from exc
            frozen_document = next(item for item in corpus.documents if item.document_key == document_key)
            section_count = _inventory_section_count(
                document=frozen_document,
                snapshot=snapshots[document_key],
            )
            if extraction.document_id != frozen_document.document_id:
                raise PilotArtifactError(f"pilot_requirement_document_mismatch:{document_key}")
            if extraction.document_content_hash != frozen_document.source.sha256:
                raise PilotArtifactError(f"pilot_requirement_hash_mismatch:{document_key}")
            if (
                summary.section_count != section_count
                or summary.chunk_count != extraction.chunk_count
                or summary.unit_count != len(extraction.units)
                or summary.atomic_count != sum(unit.scope_status == "atomic" for unit in extraction.units)
                or summary.issue_count != len(extraction.issues)
            ):
                raise PilotArtifactError(f"pilot_requirement_completion_summary_mismatch:{document_key}")
            verified[document_key] = path
    return verified


@dataclass(frozen=True)
class VerifiedPilotBootstrap:
    event: PilotLedgerEvent
    receipt: PilotBootstrapCompletionReceipt
    identity: PilotBootstrapIdentity
    results: dict[str, TaxonomyBootstrapResult]
    manifests: dict[str, TaxonomyManifest]
    provisional_gold: TaxonomyGoldSet


def verify_pilot_bootstrap_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
) -> VerifiedPilotBootstrap:
    """重放 bootstrap completion 引用的全部产物，而不是只相信事件名称。"""

    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    completions = [event for event in events if event.event_type == "taxonomy_bootstrap_completed"]
    if len(completions) != 1:
        raise PilotArtifactError("pilot_bootstrap_completion_event_invalid")
    event = completions[0]
    try:
        receipt = PilotBootstrapCompletionReceipt.model_validate(event.payload)
    except Exception as exc:  # noqa: BLE001 - 统一对外错误码
        raise PilotArtifactError("pilot_bootstrap_completion_payload_invalid") from exc

    expected_systems = {item.system_key for item in corpus.documents if item.split == "bootstrap"}
    if set(receipt.results) != expected_systems:
        raise PilotArtifactError("pilot_bootstrap_completion_systems_invalid")
    run_root = (root / "runs" / "taxonomy-bootstrap" / event.run_id).resolve()

    identity_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.identity,
        expected_path=run_root / "artifacts" / "bootstrap-identity.json",
        code="pilot_bootstrap_identity_artifact_invalid",
    )
    provisional_gold_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.provisional_gold,
        expected_path=run_root / "reviews" / "dev-gold-provisional.json",
        code="pilot_bootstrap_provisional_gold_artifact_invalid",
    )
    _verify_exact_artifact(
        root=root,
        artifact=receipt.review_report,
        expected_path=run_root / "reviews" / "BOOTSTRAP-REVIEW.md",
        code="pilot_bootstrap_review_artifact_invalid",
    )

    try:
        identity = PilotBootstrapIdentity.model_validate_json(identity_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bootstrap 身份必须整体可解析
        raise PilotArtifactError("pilot_bootstrap_artifact_schema_invalid") from exc
    if (
        identity.corpus_id != corpus.corpus_id
        or identity.source_commitment_hash != corpus.source_commitment_hash
        or identity.bootstrap_hash != receipt.bootstrap_hash
    ):
        raise PilotArtifactError("pilot_bootstrap_identity_binding_invalid")

    requirement_paths = verify_pilot_requirement_artifacts(
        root=root,
        corpus=corpus,
        splits={"bootstrap"},
    )
    runtime_path = _verify_exact_artifact(
        root=root,
        artifact=identity.runtime_manifest,
        expected_path=root / "runtime" / "model-bundle.json",
        code="pilot_bootstrap_runtime_artifact_invalid",
    )
    bootstrap_policy_path = run_root / "policies" / "bootstrap-policy.json"
    resolution_policy_path = run_root / "policies" / "base-resolution-policy.json"
    try:
        bootstrap_policy = TaxonomyBootstrapPolicy.model_validate_json(
            bootstrap_policy_path.read_text(encoding="utf-8")
        )
        resolution_policy = TaxonomyResolutionPolicy.model_validate_json(
            resolution_policy_path.read_text(encoding="utf-8")
        )
    except Exception as exc:  # noqa: BLE001 - identity 必须绑定实际策略产物
        raise PilotArtifactError("pilot_bootstrap_policy_artifact_invalid") from exc
    if (
        identity.bootstrap_policy_hash != bootstrap_policy.canonical_hash
        or identity.resolution_policy_hash != resolution_policy.canonical_hash
        or identity.runtime_manifest.sha256 != _file_hash(runtime_path)
    ):
        raise PilotArtifactError("pilot_bootstrap_policy_binding_invalid")
    expected_identity_documents = [
        PilotBootstrapIdentityDocument(
            document_key=document.document_key,
            document_id=document.document_id,
            system_key=document.system_key,
            system_id=document.system_id,
            source=document.source,
            requirement_units=ArtifactRef(
                path=str(requirement_paths[document.document_key].relative_to(root)),
                sha256=_file_hash(requirement_paths[document.document_key]),
            ),
        )
        for document in sorted(corpus.documents, key=lambda item: item.document_key)
        if document.split == "bootstrap"
    ]
    if identity.documents != expected_identity_documents:
        raise PilotArtifactError("pilot_bootstrap_document_binding_invalid")

    results: dict[str, TaxonomyBootstrapResult] = {}
    manifests: dict[str, TaxonomyManifest] = {}
    system_ids = {item.system_key: item.system_id for item in corpus.documents if item.split == "bootstrap"}
    for system_key in sorted(expected_systems):
        result_path = _verify_exact_artifact(
            root=root,
            artifact=receipt.results[system_key],
            expected_path=run_root / "raw" / f"{system_key}.json",
            code=f"pilot_bootstrap_result_artifact_invalid:{system_key}",
        )
        manifest_path = _verify_exact_artifact(
            root=root,
            artifact=receipt.output_manifests[system_key],
            expected_path=run_root / "manifests" / f"{system_key}.json",
            code=f"pilot_bootstrap_manifest_artifact_invalid:{system_key}",
        )
        try:
            result = TaxonomyBootstrapResult.model_validate_json(result_path.read_text(encoding="utf-8"))
            manifest = TaxonomyManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - completed 必须绑定真实强类型输出
            raise PilotArtifactError("pilot_bootstrap_artifact_schema_invalid") from exc
        if result.draft_manifest is None or result.draft_manifest_hash is None:
            raise PilotArtifactError(f"pilot_bootstrap_result_incomplete:{system_key}")
        expected_manifest_hash = manifest_hash(manifest)
        if (
            manifest.system_id != system_ids[system_key]
            or result.draft_manifest != manifest
            or result.draft_manifest_hash != expected_manifest_hash
            or receipt.output_manifest_hashes[system_key] != expected_manifest_hash
        ):
            raise PilotArtifactError(f"pilot_bootstrap_manifest_binding_invalid:{system_key}")
        results[system_key] = result
        manifests[system_key] = manifest

    try:
        provisional_gold = TaxonomyGoldSet.model_validate_json(provisional_gold_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - completed 必须绑定真实 gold 契约
        raise PilotArtifactError("pilot_bootstrap_artifact_schema_invalid") from exc
    if (
        provisional_gold.corpus_id != corpus.corpus_id
        or provisional_gold.dataset_hash != receipt.bootstrap_hash
        or provisional_gold.review_method != "model_assisted_provisional"
    ):
        raise PilotArtifactError("pilot_bootstrap_provisional_gold_binding_invalid")

    return VerifiedPilotBootstrap(
        event=event,
        receipt=receipt,
        identity=identity,
        results=results,
        manifests=manifests,
        provisional_gold=provisional_gold,
    )


@dataclass(frozen=True)
class VerifiedPilotCalibration:
    event: PilotLedgerEvent
    receipt: PilotCalibrationResolutionCompletionReceipt
    dataset: TaxonomyDatasetManifest
    resolutions: PilotResolutionSet
    predictions: TaxonomyPredictionSet
    provisional_gold: TaxonomyGoldSet


def verify_pilot_calibration_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    bootstrap: VerifiedPilotBootstrap | None = None,
) -> VerifiedPilotCalibration:
    """重算 calibration 的数据集身份和 resolution→prediction 机械投影。"""

    verified_bootstrap = bootstrap or verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    completions = [event for event in events if event.event_type == "calibration_resolution_completed"]
    if len(completions) != 1:
        raise PilotArtifactError("pilot_calibration_completion_event_invalid")
    event = completions[0]
    try:
        receipt = PilotCalibrationResolutionCompletionReceipt.model_validate(event.payload)
    except Exception as exc:  # noqa: BLE001 - 台账对外统一稳定错误
        raise PilotArtifactError("pilot_calibration_completion_payload_invalid") from exc
    run_root = (root / "runs" / "calibration-resolution" / event.run_id).resolve()
    dataset_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.dataset,
        expected_path=root / f"calibration-dataset-{event.run_id}.json",
        code="pilot_calibration_dataset_artifact_invalid",
    )
    resolution_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.resolutions,
        expected_path=run_root / "raw" / "resolutions.json",
        code="pilot_calibration_resolution_artifact_invalid",
    )
    concept_ref_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.concept_refs,
        expected_path=run_root / "artifacts" / "concept-refs.json",
        code="pilot_calibration_concept_ref_artifact_invalid",
    )
    prediction_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.predictions,
        expected_path=run_root / "predictions" / "predictions.json",
        code="pilot_calibration_prediction_artifact_invalid",
    )
    provisional_gold_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.provisional_gold,
        expected_path=run_root / "reviews" / "calibration-gold-provisional.json",
        code="pilot_calibration_provisional_gold_artifact_invalid",
    )
    try:
        dataset = TaxonomyDatasetManifest.model_validate_json(dataset_path.read_text(encoding="utf-8"))
        resolutions = PilotResolutionSet.model_validate_json(resolution_path.read_text(encoding="utf-8"))
        concept_refs = PilotConceptRefSet.model_validate_json(concept_ref_path.read_text(encoding="utf-8"))
        predictions = TaxonomyPredictionSet.model_validate_json(prediction_path.read_text(encoding="utf-8"))
        provisional_gold = TaxonomyGoldSet.model_validate_json(provisional_gold_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - completed 必须绑定完整强类型产物
        raise PilotArtifactError("pilot_calibration_artifact_schema_invalid") from exc

    expected_documents = {item.document_key: item for item in corpus.documents if item.split == "calibration"}
    expected_systems = {item.system_key for item in expected_documents.values()}
    runtime_path = root / "runtime" / "model-bundle.json"
    expected_upstream_hashes = {
        "bootstrap_event": verified_bootstrap.event.event_hash,
        "bootstrap_identity": verified_bootstrap.receipt.bootstrap_hash,
        "runtime_manifest": _file_hash(runtime_path),
        **{
            f"output_manifest.{system_key}": manifest_hash(manifest)
            for system_key, manifest in sorted(verified_bootstrap.manifests.items())
        },
    }
    if (
        dataset.schema_version != 2
        or dataset.corpus_id != corpus.corpus_id
        or dataset.evaluation_split != "dev"
        or dataset.source_commitment_hash != corpus.source_commitment_hash
        or dataset.upstream_artifact_hashes != expected_upstream_hashes
        or dataset.dataset_hash != receipt.calibration_dataset_hash
        or {item.document_key for item in dataset.documents} != set(expected_documents)
    ):
        raise PilotArtifactError("pilot_calibration_dataset_binding_invalid")

    requirement_paths = verify_pilot_requirement_artifacts(
        root=root,
        corpus=corpus,
        splits={"calibration"},
    )
    expected_unit_keys: set[tuple[str, str]] = set()
    for document_key, path in requirement_paths.items():
        extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        expected_unit_keys.update((document_key, unit.unit_id) for unit in extraction.units)
    resolution_unit_keys = {(item.document_key, item.requirement_unit_id) for item in resolutions.records}
    prediction_unit_keys = {(item.document_key, item.requirement_unit_id) for item in predictions.records}
    if resolution_unit_keys != expected_unit_keys or prediction_unit_keys != expected_unit_keys:
        raise PilotArtifactError("pilot_calibration_prediction_unit_coverage_invalid")
    dataset_documents = {item.document_key: item for item in dataset.documents}
    for document_key, document in expected_documents.items():
        dataset_document = dataset_documents[document_key]
        expected_requirement_ref = ArtifactRef(
            path=str(requirement_paths[document_key].relative_to(root)),
            sha256=_file_hash(requirement_paths[document_key]),
        )
        if (
            dataset_document.document_id != document.document_id
            or dataset_document.system_key != document.system_key
            or dataset_document.system_id != document.system_id
            or dataset_document.split != "dev"
            or dataset_document.source != document.source
            or dataset_document.requirement_units != expected_requirement_ref
        ):
            raise PilotArtifactError(f"pilot_calibration_document_binding_invalid:{document_key}")

    if (
        receipt.output_manifest_hashes != verified_bootstrap.receipt.output_manifest_hashes
        or receipt.output_manifests != verified_bootstrap.receipt.output_manifests
    ):
        raise PilotArtifactError("pilot_calibration_manifest_binding_invalid")

    try:
        validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=dataset_path)
        load_requirement_unit_index(dataset=dataset, manifest_path=dataset_path, document_splits={"dev"})
        loaded_manifests = load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=dataset_path,
            predictions=predictions,
        )
    except Exception as exc:  # noqa: BLE001 - evaluator 与 runner 必须共享同一 artifact 解释
        raise PilotArtifactError("pilot_calibration_evaluation_bundle_invalid") from exc
    if loaded_manifests != verified_bootstrap.manifests:
        raise PilotArtifactError("pilot_calibration_manifest_binding_invalid")

    if (
        resolutions.dataset_hash != dataset.dataset_hash
        or predictions.dataset_hash != dataset.dataset_hash
        or provisional_gold.dataset_hash != dataset.dataset_hash
        or provisional_gold.corpus_id != corpus.corpus_id
        or provisional_gold.review_method != "model_assisted_provisional"
        or {item.system_key for item in resolutions.records} != expected_systems
        or {item.system_key for item in predictions.records} != expected_systems
        or {item.split for item in resolutions.records} != {"dev"}
        or {item.split for item in predictions.records} != {"dev"}
        or resolutions.prompt_revisions != dataset.prompt_revisions
        or resolutions.model_revisions != dataset.model_revisions
        or predictions.prompt_revisions != dataset.prompt_revisions
        or predictions.model_revisions != dataset.model_revisions
        or resolutions.output_manifest_hashes != receipt.output_manifest_hashes
        or predictions.output_manifest_hashes != receipt.output_manifest_hashes
        or predictions.output_manifest_artifacts != receipt.output_manifests
    ):
        raise PilotArtifactError("pilot_calibration_artifact_binding_invalid")

    projected = project_resolution_predictions(
        resolutions=resolutions,
        concept_refs=concept_refs.by_concept_id,
        manifests=verified_bootstrap.manifests,
        manifest_artifacts=receipt.output_manifests,
    )
    if projected != predictions:
        raise PilotArtifactError("pilot_calibration_prediction_projection_mismatch")

    return VerifiedPilotCalibration(
        event=event,
        receipt=receipt,
        dataset=dataset,
        resolutions=resolutions,
        predictions=predictions,
        provisional_gold=provisional_gold,
    )


def verify_pilot_calibration_unit_gold(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    calibration: VerifiedPilotCalibration,
    provisional_gold: TaxonomyGoldSet,
    independent_gold: TaxonomyGoldSet,
) -> dict[tuple[str, str], RequirementUnit]:
    """Unit gold 只评价已发现 unit，但必须完整覆盖 calibration 提取产物。"""

    paths = verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"calibration"})
    expected_units: dict[tuple[str, str], RequirementUnit] = {}
    documents = {item.document_key: item for item in corpus.documents if item.split == "calibration"}
    for document_key, document in documents.items():
        extraction = RequirementUnitExtractionResult.model_validate_json(
            paths[document_key].read_text(encoding="utf-8")
        )
        for unit in extraction.units:
            expected_units[(document_key, unit.unit_id)] = unit

    expected_keys = set(expected_units)
    for gold in (provisional_gold, independent_gold):
        actual_keys = {(item.document_key, item.requirement_unit_id) for item in gold.records}
        if actual_keys != expected_keys:
            raise PilotArtifactError("pilot_calibration_gold_unit_coverage_invalid")
        for record in gold.records:
            bound_document = documents.get(record.document_key)
            unit = expected_units[(record.document_key, record.requirement_unit_id)]
            if (
                bound_document is None
                or record.system_key != bound_document.system_key
                or record.split != "dev"
                or unit.source_ref not in record.gold_evidence
            ):
                raise PilotArtifactError("pilot_calibration_gold_unit_binding_invalid")

    if (
        provisional_gold.canonical_hash != calibration.provisional_gold.canonical_hash
        or provisional_gold.dataset_hash != calibration.dataset.dataset_hash
        or independent_gold.dataset_hash != calibration.dataset.dataset_hash
        or provisional_gold.corpus_id != corpus.corpus_id
        or independent_gold.corpus_id != corpus.corpus_id
        or provisional_gold.review_method != "model_assisted_provisional"
        or independent_gold.review_method != "human_independent"
    ):
        raise PilotArtifactError("pilot_calibration_gold_binding_invalid")
    return expected_units


@dataclass(frozen=True)
class PilotCoverageVerificationMetrics:
    coverage_record_count: int
    expected_fact_count: int
    matched_fact_count: int
    extracted_unit_count: int
    matched_extracted_unit_count: int

    @property
    def extraction_recall(self) -> float:
        return self.matched_fact_count / self.expected_fact_count if self.expected_fact_count else 1.0

    @property
    def extraction_precision(self) -> float:
        return self.matched_extracted_unit_count / self.extracted_unit_count if self.extracted_unit_count else 1.0


class PilotSourceCoverageError(PilotArtifactError):
    def __init__(self, metrics: PilotCoverageVerificationMetrics, findings: list[str]):
        self.metrics = metrics
        self.findings = findings
        super().__init__("pilot_locked_test_source_coverage_gate_failed")


def _is_valid_fact_overlap(coverages: list[RequirementChunkCoverage]) -> bool:
    """同一事实只能在同一 section 的连续重叠窗口中复用身份。"""

    if len(coverages) <= 1:
        return True
    group_keys = {(item.source_ref, item.heading, item.section_kind, item.chunk_count) for item in coverages}
    indices = sorted(item.chunk_index for item in coverages)
    return (
        len(group_keys) == 1
        and coverages[0].chunk_count > 1
        and len(indices) == len(set(indices))
        and indices == list(range(indices[0], indices[-1] + 1))
    )


def render_locked_test_source_coverage_failure(
    metrics: PilotCoverageVerificationMetrics,
    findings: list[str],
) -> str:
    """确定性渲染质量失败报告，供 runner 与离线重放共享。"""

    return "\n".join(
        [
            "# Locked Test 来源覆盖门禁失败",
            "",
            "> 这是质量门禁失败，不是基础设施异常；锁定测试机会已经消费。",
            "",
            f"- Extraction recall: `{metrics.extraction_recall:.3f}`",
            f"- Extraction precision: `{metrics.extraction_precision:.3f}`",
            f"- Expected facts: `{metrics.expected_fact_count}`",
            f"- Matched facts: `{metrics.matched_fact_count}`",
            f"- Extracted units: `{metrics.extracted_unit_count}`",
            "",
            "## Findings",
            "",
            *[f"- `{finding}`" for finding in findings],
        ]
    )


def verify_pilot_calibration_coverage_gold(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    calibration: VerifiedPilotCalibration,
    coverage_gold: PilotCoverageGoldSet,
) -> PilotCoverageVerificationMetrics:
    """独立 coverage gold 必须逐 chunk 覆盖源分母，并显式标出每个原子事实。"""

    if (
        coverage_gold.schema_version != 1
        or coverage_gold.source_commitment_hash is not None
        or {record.split for record in coverage_gold.records} != {"calibration"}
        or coverage_gold.corpus_id != corpus.corpus_id
        or coverage_gold.dataset_hash != calibration.dataset.dataset_hash
        or coverage_gold.review_method != "human_independent"
    ):
        raise PilotArtifactError("pilot_calibration_coverage_gold_binding_invalid")
    paths = verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"calibration"})
    documents = {item.document_key: item for item in corpus.documents if item.split == "calibration"}
    snapshots = load_split_snapshots(corpus=corpus, root=root, split="calibration")
    expected_coverage: dict[
        str,
        tuple[str, RequirementChunkCoverage, dict[str, RequirementUnit]],
    ] = {}
    document_units: dict[str, dict[str, RequirementUnit]] = {}
    for document_key, path in paths.items():
        extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        units = {unit.unit_id: unit for unit in extraction.units}
        document_units[document_key] = units
        for coverage in extraction.coverage:
            if coverage.coverage_id in expected_coverage:
                raise PilotArtifactError(f"pilot_calibration_coverage_duplicate:{coverage.coverage_id}")
            expected_coverage[coverage.coverage_id] = (document_key, coverage, units)

    records = {item.coverage_id: item for item in coverage_gold.records}
    if set(records) != set(expected_coverage):
        raise PilotArtifactError("pilot_calibration_coverage_gold_incomplete")
    disposition_map = {
        "requirements_extracted": "requirements_present",
        "no_requirement": "no_requirement",
        "excluded_non_spec": "excluded_non_spec",
        "empty_section": "empty_section",
    }
    fact_occurrences: dict[
        str,
        list[tuple[str, PilotCoverageGoldFact, RequirementChunkCoverage]],
    ] = {}
    for coverage_id, (document_key, coverage, _) in expected_coverage.items():
        record = records[coverage_id]
        document = documents[document_key]
        actual_disposition = disposition_map.get(coverage.disposition)
        if (
            record.document_key != document_key
            or record.system_key != document.system_key
            or record.split != "calibration"
            or record.source_ref != coverage.source_ref
            or record.content_hash != coverage.content_hash
        ):
            raise PilotArtifactError(f"pilot_calibration_coverage_gold_record_invalid:{coverage_id}")
        disposition_matches = (
            actual_disposition in {"requirements_present", "no_requirement"}
            if record.expected_disposition == "requirements_present"
            else record.expected_disposition == actual_disposition
        )
        if not disposition_matches:
            raise PilotArtifactError(f"pilot_calibration_coverage_gold_record_invalid:{coverage_id}")
        for fact in record.facts:
            fact_occurrences.setdefault(fact.fact_id, []).append((document_key, fact, coverage))

    matched_fact_ids: set[str] = set()
    matched_extracted_unit_ids: set[str] = set()
    matched_unit_facts: dict[str, str] = {}
    for fact_id in sorted(fact_occurrences):
        occurrences = fact_occurrences[fact_id]
        document_key = occurrences[0][0]
        fact = occurrences[0][1]
        if not _is_valid_fact_overlap([occurrence[2] for occurrence in occurrences]):
            raise PilotArtifactError(f"pilot_calibration_coverage_fact_overlap_invalid:{fact_id}")
        matched_unit_id = fact.matched_requirement_unit_id
        candidate_unit_ids = {
            unit_id
            for occurrence_document_key, _, coverage in occurrences
            if occurrence_document_key == document_key
            for unit_id in coverage.requirement_unit_ids
        }
        unit = document_units[document_key].get(matched_unit_id) if matched_unit_id is not None else None
        if (
            any(occurrence[0] != document_key for occurrence in occurrences)
            or unit is None
            or matched_unit_id not in candidate_unit_ids
            or fact.source_quote not in snapshots[document_key]
            or fact.source_quote != unit.source_quote
            or fact.source_quote_hash != unit.source_quote_hash
        ):
            raise PilotArtifactError(f"pilot_calibration_coverage_fact_binding_invalid:{fact_id}")
        previous_fact = matched_unit_facts.get(unit.unit_id)
        if previous_fact is not None and previous_fact != fact_id:
            raise PilotArtifactError(f"pilot_calibration_coverage_fact_binding_invalid:{fact_id}")
        matched_unit_facts[unit.unit_id] = fact_id
        matched_fact_ids.add(fact_id)
        matched_extracted_unit_ids.add(unit.unit_id)

    expected_fact_ids = set(fact_occurrences)
    extracted_unit_ids = {unit_id for units in document_units.values() for unit_id in units}
    if matched_fact_ids != expected_fact_ids or matched_extracted_unit_ids != extracted_unit_ids:
        raise PilotArtifactError("pilot_calibration_coverage_fact_binding_invalid:global")
    return PilotCoverageVerificationMetrics(
        coverage_record_count=len(records),
        expected_fact_count=len(expected_fact_ids),
        matched_fact_count=len(matched_fact_ids),
        extracted_unit_count=len(extracted_unit_ids),
        matched_extracted_unit_count=len(matched_extracted_unit_ids),
    )


def _verify_pilot_gold_attestation(
    *,
    corpus: PilotFrozenCorpus,
    provisional_gold: TaxonomyGoldSet,
    independent_gold: TaxonomyGoldSet,
    coverage_gold: PilotCoverageGoldSet,
    attestation: PilotGoldReviewAttestation,
) -> None:
    if (
        provisional_gold.corpus_id != corpus.corpus_id
        or independent_gold.corpus_id != corpus.corpus_id
        or coverage_gold.corpus_id != corpus.corpus_id
        or attestation.corpus_id != corpus.corpus_id
    ):
        raise PilotArtifactError("pilot_independent_gold_corpus_mismatch")
    if provisional_gold.review_method != "model_assisted_provisional":
        raise PilotArtifactError("pilot_provisional_gold_required")
    if independent_gold.review_method != "human_independent":
        raise PilotArtifactError("pilot_independent_gold_required")
    if (
        provisional_gold.reviewed_at >= independent_gold.reviewed_at
        or provisional_gold.reviewed_at >= coverage_gold.reviewed_at
    ):
        raise PilotArtifactError("pilot_independent_gold_review_order_invalid")
    if (
        attestation.provisional_dataset_hash != provisional_gold.dataset_hash
        or attestation.independent_dataset_hash != independent_gold.dataset_hash
        or attestation.provisional_gold_hash != provisional_gold.canonical_hash
        or attestation.independent_gold_hash != independent_gold.canonical_hash
        or attestation.independent_coverage_dataset_hash != coverage_gold.dataset_hash
        or attestation.independent_coverage_gold_hash != coverage_gold.canonical_hash
        or attestation.provisional_reviewed_by != provisional_gold.reviewed_by
        or attestation.reviewed_by != independent_gold.reviewed_by
        or attestation.reviewed_at != independent_gold.reviewed_at
        or attestation.coverage_reviewed_by != coverage_gold.reviewed_by
        or attestation.coverage_reviewed_at != coverage_gold.reviewed_at
    ):
        raise PilotArtifactError("pilot_independent_gold_attestation_mismatch")


def build_pilot_frozen_policy(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    provisional_gold: TaxonomyGoldSet,
    independent_gold: TaxonomyGoldSet,
    coverage_gold: PilotCoverageGoldSet,
    attestation: PilotGoldReviewAttestation,
    calibrated_at: datetime,
    minimum_precision: float,
    minimum_auto_decisions: int = 1,
) -> TaxonomyFrozenPolicy:
    """重放全部 calibration 证据后冻结 v2 策略；不接受调用方手工填统计值。"""

    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    calibration = verify_pilot_calibration_artifacts(
        root=root,
        corpus=corpus,
        bootstrap=bootstrap,
    )
    verify_pilot_calibration_unit_gold(
        root=root,
        corpus=corpus,
        calibration=calibration,
        provisional_gold=provisional_gold,
        independent_gold=independent_gold,
    )
    coverage_metrics = verify_pilot_calibration_coverage_gold(
        root=root,
        corpus=corpus,
        calibration=calibration,
        coverage_gold=coverage_gold,
    )
    _verify_pilot_gold_attestation(
        corpus=corpus,
        provisional_gold=provisional_gold,
        independent_gold=independent_gold,
        coverage_gold=coverage_gold,
        attestation=attestation,
    )
    if calibrated_at < max(independent_gold.reviewed_at, coverage_gold.reviewed_at):
        raise PilotArtifactError("pilot_frozen_policy_precedes_gold_review")

    dataset_path = _resolve_artifact(root, calibration.receipt.dataset.path)
    try:
        requirement_units = load_requirement_unit_index(
            dataset=calibration.dataset,
            manifest_path=dataset_path,
            document_splits={"dev"},
        )
        base_policy_path = (
            root
            / "runs"
            / "calibration-resolution"
            / calibration.event.run_id
            / "policies"
            / "base-resolution-policy.json"
        )
        base_policy = TaxonomyResolutionPolicy.model_validate_json(base_policy_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 校准必须绑定 runner 固定的输入
        raise PilotArtifactError("pilot_calibration_policy_input_invalid") from exc
    if base_policy.canonical_hash != calibration.resolutions.policy_hash:
        raise PilotArtifactError("pilot_calibration_policy_input_invalid")

    calibrated = calibrate_resolution_policy(
        dataset=calibration.dataset,
        gold=independent_gold,
        predictions=calibration.predictions,
        requirement_units=requirement_units,
        base_policy=base_policy,
        calibrated_at=calibrated_at,
        minimum_precision=minimum_precision,
        minimum_auto_decisions=minimum_auto_decisions,
        allow_post_prediction_gold_review=True,
    )
    calibration_input_hash = hashlib.sha256(
        json.dumps(
            {
                "base_calibration_input_hash": calibrated.calibration_input_hash,
                "source_commitment_hash": corpus.source_commitment_hash,
                "coverage_gold_hash": coverage_gold.canonical_hash,
                "gold_attestation_hash": attestation.canonical_hash,
                "prediction_hash": calibration.predictions.canonical_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return TaxonomyFrozenPolicy.model_validate(
        {
            **calibrated.model_dump(mode="json"),
            "schema_version": 2,
            "calibration_input_hash": calibration_input_hash,
            "calibration_coverage_gold_hash": coverage_gold.canonical_hash,
            "calibration_coverage_gold_review_method": coverage_gold.review_method,
            "calibration_gold_attestation_hash": attestation.canonical_hash,
            "calibration_prediction_hash": calibration.predictions.canonical_hash,
            "calibration_source_commitment_hash": corpus.source_commitment_hash,
            "calibration_coverage_record_count": coverage_metrics.coverage_record_count,
            "expected_requirement_fact_count": coverage_metrics.expected_fact_count,
            "matched_requirement_fact_count": coverage_metrics.matched_fact_count,
            "extracted_requirement_unit_count": coverage_metrics.extracted_unit_count,
            "matched_extracted_requirement_unit_count": coverage_metrics.matched_extracted_unit_count,
            "observed_requirement_extraction_recall": coverage_metrics.extraction_recall,
            "observed_requirement_extraction_precision": coverage_metrics.extraction_precision,
        }
    )


@dataclass(frozen=True)
class VerifiedPilotPolicyFreeze:
    event: PilotLedgerEvent
    receipt: PilotCalibrationPolicyCompletionReceipt
    frozen_policy: TaxonomyFrozenPolicy
    independent_gold: TaxonomyGoldSet
    coverage_gold: PilotCoverageGoldSet
    attestation: PilotGoldReviewAttestation


def verify_pilot_policy_freeze_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
) -> VerifiedPilotPolicyFreeze:
    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    completions = [event for event in events if event.event_type == "calibration_policy_freeze_completed"]
    if len(completions) != 1:
        raise PilotArtifactError("pilot_policy_freeze_completion_event_invalid")
    event = completions[0]
    try:
        receipt = PilotCalibrationPolicyCompletionReceipt.model_validate(event.payload)
    except Exception as exc:  # noqa: BLE001 - 台账边界统一转为稳定错误码
        raise PilotArtifactError("pilot_policy_freeze_completion_payload_invalid") from exc
    run_root = (root / "runs" / "calibration-policy" / event.run_id).resolve()
    frozen_policy_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.frozen_policy,
        expected_path=run_root / "policies" / "frozen-policy.json",
        code="pilot_frozen_policy_artifact_invalid",
    )
    independent_gold_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.independent_gold,
        expected_path=run_root / "reviews" / "calibration-gold-independent.json",
        code="pilot_independent_gold_artifact_invalid",
    )
    coverage_gold_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.coverage_gold,
        expected_path=run_root / "reviews" / "calibration-coverage-gold-independent.json",
        code="pilot_coverage_gold_artifact_invalid",
    )
    attestation_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.gold_attestation,
        expected_path=run_root / "reviews" / "gold-attestation.json",
        code="pilot_gold_attestation_artifact_invalid",
    )
    try:
        frozen_policy = TaxonomyFrozenPolicy.model_validate_json(frozen_policy_path.read_text(encoding="utf-8"))
        independent_gold = TaxonomyGoldSet.model_validate_json(independent_gold_path.read_text(encoding="utf-8"))
        coverage_gold = PilotCoverageGoldSet.model_validate_json(coverage_gold_path.read_text(encoding="utf-8"))
        attestation = PilotGoldReviewAttestation.model_validate_json(attestation_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - completed 必须绑定强类型产物
        raise PilotArtifactError("pilot_policy_freeze_artifact_schema_invalid") from exc
    calibration = verify_pilot_calibration_artifacts(root=root, corpus=corpus)
    rebuilt = build_pilot_frozen_policy(
        root=root,
        corpus=corpus,
        provisional_gold=calibration.provisional_gold,
        independent_gold=independent_gold,
        coverage_gold=coverage_gold,
        attestation=attestation,
        calibrated_at=frozen_policy.calibrated_at,
        minimum_precision=receipt.minimum_precision,
        minimum_auto_decisions=receipt.minimum_auto_decisions,
    )
    if (
        receipt.calibration_dataset_hash != calibration.dataset.dataset_hash
        or receipt.frozen_policy_hash != frozen_policy.canonical_hash
        or rebuilt != frozen_policy
    ):
        raise PilotArtifactError("pilot_frozen_policy_binding_invalid")
    return VerifiedPilotPolicyFreeze(
        event=event,
        receipt=receipt,
        frozen_policy=frozen_policy,
        independent_gold=independent_gold,
        coverage_gold=coverage_gold,
        attestation=attestation,
    )


def _derive_locked_test_gold_records(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    extractions: Mapping[str, RequirementUnitExtractionResult],
    source_gold: PilotCoverageGoldSet,
) -> tuple[list[TaxonomyGoldRecord], PilotCoverageVerificationMetrics, dict[str, str]]:
    """把预测前冻结、预测落盘后揭盲的 source-fact 标签机械匹配到 test extraction。"""

    if (
        source_gold.schema_version != 2
        or source_gold.corpus_id != corpus.corpus_id
        or source_gold.source_commitment_hash != corpus.source_commitment_hash
        or source_gold.dataset_hash is not None
        or {item.split for item in source_gold.records} != {"test"}
    ):
        raise PilotArtifactError("pilot_locked_test_source_gold_binding_invalid")
    documents = {item.document_key: item for item in corpus.documents if item.split == "test"}
    if set(extractions) != set(documents):
        raise PilotArtifactError("pilot_locked_test_extraction_documents_invalid")
    snapshots = load_split_snapshots(
        corpus=corpus,
        root=root,
        split="test",
        allow_locked_test=True,
    )
    expected_coverage: dict[str, tuple[str, RequirementChunkCoverage, dict[str, RequirementUnit]]] = {}
    document_units: dict[str, dict[str, RequirementUnit]] = {}
    for document_key, extraction in extractions.items():
        document = documents[document_key]
        if extraction.document_id != document.document_id or extraction.document_content_hash != document.source.sha256:
            raise PilotArtifactError(f"pilot_locked_test_extraction_binding_invalid:{document_key}")
        units = {unit.unit_id: unit for unit in extraction.units}
        document_units[document_key] = units
        for coverage in extraction.coverage:
            if coverage.coverage_id in expected_coverage:
                raise PilotArtifactError(f"pilot_locked_test_coverage_duplicate:{coverage.coverage_id}")
            expected_coverage[coverage.coverage_id] = (document_key, coverage, units)

    source_records = {item.coverage_id: item for item in source_gold.records}
    if set(source_records) != set(expected_coverage):
        raise PilotArtifactError("pilot_locked_test_source_gold_incomplete")
    disposition_map = {
        "requirements_extracted": "requirements_present",
        "no_requirement": "no_requirement",
        "excluded_non_spec": "excluded_non_spec",
        "empty_section": "empty_section",
    }
    gold_records: list[TaxonomyGoldRecord] = []
    matched_fact_units: dict[str, str] = {}
    matched_unit_facts: dict[str, str] = {}
    fact_occurrences: dict[
        str,
        list[
            tuple[
                str,
                PilotCoverageGoldFact,
                RequirementChunkCoverage,
                list[RequirementUnit],
            ]
        ],
    ] = {}
    covered_unit_ids: set[str] = set()
    findings: list[str] = []
    for coverage_id, (document_key, coverage, units) in expected_coverage.items():
        source_record = source_records[coverage_id]
        document = documents[document_key]
        if (
            source_record.document_key != document_key
            or source_record.system_key != document.system_key
            or source_record.source_ref != coverage.source_ref
            or source_record.content_hash != coverage.content_hash
        ):
            raise PilotArtifactError(f"pilot_locked_test_source_gold_record_invalid:{coverage_id}")
        actual_disposition = disposition_map.get(coverage.disposition)
        disposition_matches = (
            actual_disposition in {"requirements_present", "no_requirement"}
            if source_record.expected_disposition == "requirements_present"
            else source_record.expected_disposition == actual_disposition
        )
        if not disposition_matches:
            findings.append(f"source_disposition_mismatch:{coverage_id}")
        coverage_units = [units[unit_id] for unit_id in coverage.requirement_unit_ids]
        covered_unit_ids.update(unit.unit_id for unit in coverage_units)
        for fact in source_record.facts:
            expectation = fact.taxonomy_expectation
            if expectation is None or fact.source_quote not in snapshots[document_key]:
                raise PilotArtifactError(f"pilot_locked_test_source_gold_fact_invalid:{fact.fact_id}")
            fact_occurrences.setdefault(fact.fact_id, []).append((document_key, fact, coverage, coverage_units))

    for fact_id in sorted(fact_occurrences):
        occurrences = fact_occurrences[fact_id]
        document_key = occurrences[0][0]
        fact = occurrences[0][1]
        if not _is_valid_fact_overlap([occurrence[2] for occurrence in occurrences]):
            raise PilotArtifactError(f"pilot_locked_test_source_gold_fact_overlap_invalid:{fact_id}")
        candidates = {
            unit.unit_id: unit
            for occurrence_document_key, occurrence_fact, _, coverage_units in occurrences
            if occurrence_document_key == document_key
            for unit in coverage_units
            if unit.source_quote == occurrence_fact.source_quote
            and unit.source_quote_hash == occurrence_fact.source_quote_hash
        }
        if any(occurrence[0] != document_key for occurrence in occurrences):
            raise PilotArtifactError(f"pilot_locked_test_source_gold_fact_conflict:{fact_id}")
        if len(candidates) != 1:
            findings.append(f"source_fact_match_count:{fact_id}:{len(candidates)}")
            continue
        unit = next(iter(candidates.values()))
        previous_fact = matched_unit_facts.get(unit.unit_id)
        if previous_fact is not None and previous_fact != fact_id:
            raise PilotArtifactError(f"pilot_locked_test_source_gold_unit_duplicate:{unit.unit_id}")
        matched_fact_units[fact_id] = unit.unit_id
        matched_unit_facts[unit.unit_id] = fact_id
        document = documents[document_key]
        expectation = fact.taxonomy_expectation
        if expectation is None:
            raise PilotArtifactError(f"pilot_locked_test_source_gold_fact_invalid:{fact_id}")
        gold_records.append(
            TaxonomyGoldRecord(
                record_id=pilot_record_id(document_key, unit.unit_id),
                document_key=document_key,
                system_key=document.system_key,
                split="test",
                requirement_unit_id=unit.unit_id,
                gold_evidence=[unit.source_ref],
                **expectation.model_dump(mode="python"),
            )
        )
    expected_fact_ids = set(fact_occurrences)
    all_unit_ids = {unit_id for units in document_units.values() for unit_id in units}
    matched_unit_ids = set(matched_fact_units.values())
    metrics = PilotCoverageVerificationMetrics(
        coverage_record_count=len(source_records),
        expected_fact_count=len(expected_fact_ids),
        matched_fact_count=len(matched_fact_units),
        extracted_unit_count=len(all_unit_ids),
        matched_extracted_unit_count=len(matched_unit_ids),
    )
    if (
        matched_unit_ids != all_unit_ids
        or set(matched_fact_units) != expected_fact_ids
        or covered_unit_ids != all_unit_ids
    ):
        findings.append("source_fact_unit_coverage_mismatch")
    if findings:
        raise PilotSourceCoverageError(metrics, sorted(set(findings)))
    if not gold_records:
        raise PilotArtifactError("pilot_locked_test_gold_empty")
    return gold_records, metrics, matched_fact_units


def derive_locked_test_gold(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    dataset: TaxonomyDatasetManifest,
    extractions: Mapping[str, RequirementUnitExtractionResult],
    source_gold: PilotCoverageGoldSet,
) -> tuple[TaxonomyGoldSet, PilotCoverageVerificationMetrics]:
    """预测落盘后才把隐藏的 source-fact 标签绑定到当前 test dataset。"""

    if (
        dataset.schema_version != 2
        or dataset.evaluation_split != "test"
        or dataset.source_commitment_hash != corpus.source_commitment_hash
    ):
        raise PilotArtifactError("pilot_locked_test_source_gold_binding_invalid")
    gold_records, metrics, _ = _derive_locked_test_gold_records(
        root=root,
        corpus=corpus,
        extractions=extractions,
        source_gold=source_gold,
    )
    return (
        TaxonomyGoldSet(
            schema_version=1,
            corpus_id=corpus.corpus_id,
            dataset_hash=dataset.dataset_hash,
            review_method="human_independent",
            reviewed_by=source_gold.reviewed_by,
            reviewed_at=source_gold.reviewed_at,
            records=gold_records,
        ),
        metrics,
    )


def _source_transformation_facts(
    *,
    corpus: PilotFrozenCorpus,
    source_gold: PilotCoverageGoldSet,
    source_transformations: PilotSourceTransformationCommitment,
) -> dict[str, tuple[str, PilotCoverageGoldFact]]:
    if (
        source_transformations.corpus_id != corpus.corpus_id
        or source_transformations.source_commitment_hash != corpus.source_commitment_hash
        or source_transformations.projection_revision != PILOT_TRANSFORMATION_PROJECTION_REVISION
    ):
        raise PilotArtifactError("pilot_source_transformation_commitment_binding_invalid")
    if source_transformations.reviewed_at < source_gold.reviewed_at:
        raise PilotArtifactError("pilot_source_transformation_review_precedes_source_gold")
    facts: dict[str, tuple[str, PilotCoverageGoldFact]] = {}
    for record in source_gold.records:
        for fact in record.facts:
            facts.setdefault(fact.fact_id, (record.system_key, fact))
    for transformation in source_transformations.records:
        source_entry = facts.get(transformation.source_fact_id)
        variant_entry = facts.get(transformation.variant_fact_id)
        if source_entry is None or variant_entry is None:
            raise PilotArtifactError(f"pilot_source_transformation_fact_missing:{transformation.transformation_id}")
        source_system, source_fact = source_entry
        variant_system, variant_fact = variant_entry
        if source_system != transformation.system_key or variant_system != transformation.system_key:
            raise PilotArtifactError(f"pilot_source_transformation_system_mismatch:{transformation.transformation_id}")
        if (
            source_fact.source_quote_hash != transformation.source_quote_hash
            or variant_fact.source_quote_hash != transformation.variant_quote_hash
        ):
            raise PilotArtifactError(f"pilot_source_transformation_quote_mismatch:{transformation.transformation_id}")
        if (
            source_fact.taxonomy_expectation is None
            or variant_fact.taxonomy_expectation is None
            or source_fact.taxonomy_expectation != variant_fact.taxonomy_expectation
        ):
            raise PilotArtifactError(
                f"pilot_source_transformation_expectation_mismatch:{transformation.transformation_id}"
            )
    return facts


def derive_locked_test_evidence(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    dataset: TaxonomyDatasetManifest,
    extractions: Mapping[str, RequirementUnitExtractionResult],
    source_gold: PilotCoverageGoldSet,
    source_transformations: PilotSourceTransformationCommitment,
) -> tuple[TaxonomyGoldSet, PilotCoverageVerificationMetrics, TaxonomyTransformationSet]:
    """揭盲后将 source-fact gold 和变形承诺机械投影到本次唯一 extraction。"""

    if (
        dataset.schema_version != 3
        or dataset.evaluation_split != "test"
        or dataset.source_commitment_hash != corpus.source_commitment_hash
        or dataset.source_transformation_commitment_artifact is None
        or dataset.transformation_projection_revision != PILOT_TRANSFORMATION_PROJECTION_REVISION
    ):
        raise PilotArtifactError("pilot_locked_test_transformation_dataset_binding_invalid")
    _source_transformation_facts(
        corpus=corpus,
        source_gold=source_gold,
        source_transformations=source_transformations,
    )
    gold_records, metrics, matched_fact_units = _derive_locked_test_gold_records(
        root=root,
        corpus=corpus,
        extractions=extractions,
        source_gold=source_gold,
    )
    units_by_id = {unit.unit_id: unit for extraction in extractions.values() for unit in extraction.units}
    records_by_unit = {record.requirement_unit_id: record for record in gold_records}
    semantic_updates: dict[str, tuple[str, str]] = {}
    projected: list[TaxonomyTransformationRecord] = []
    for transformation in sorted(
        source_transformations.records,
        key=lambda item: item.transformation_id,
    ):
        source_unit_id = matched_fact_units[transformation.source_fact_id]
        variant_unit_id = matched_fact_units[transformation.variant_fact_id]
        source_record = records_by_unit[source_unit_id]
        variant_record = records_by_unit[variant_unit_id]
        source_unit = units_by_id[source_unit_id]
        variant_unit = units_by_id[variant_unit_id]
        source_update = (transformation.semantic_group_id, "original")
        previous_source = semantic_updates.setdefault(source_unit_id, source_update)
        if previous_source != source_update:
            raise PilotArtifactError(f"pilot_source_transformation_source_conflict:{transformation.transformation_id}")
        semantic_updates[variant_unit_id] = (
            transformation.semantic_group_id,
            transformation.kind,
        )
        projected.append(
            TaxonomyTransformationRecord(
                transformation_id=transformation.transformation_id,
                system_key=transformation.system_key,
                split="test",
                semantic_group_id=transformation.semantic_group_id,
                source_record_id=source_record.record_id,
                variant_record_id=variant_record.record_id,
                kind=transformation.kind,
                transformation_revision=transformation.transformation_revision,
                source_text_hash=hashlib.sha256(source_unit.statement.encode("utf-8")).hexdigest(),
                variant_text_hash=hashlib.sha256(variant_unit.statement.encode("utf-8")).hexdigest(),
            )
        )
    transformed_gold_records = [
        record.model_copy(
            update={
                "semantic_group_id": semantic_updates[record.requirement_unit_id][0],
                "variant_kind": semantic_updates[record.requirement_unit_id][1],
            }
        )
        if record.requirement_unit_id in semantic_updates
        else record
        for record in gold_records
    ]
    gold = TaxonomyGoldSet(
        schema_version=1,
        corpus_id=corpus.corpus_id,
        dataset_hash=dataset.dataset_hash,
        review_method="human_independent",
        reviewed_by=source_gold.reviewed_by,
        reviewed_at=source_gold.reviewed_at,
        records=transformed_gold_records,
    )
    transformations = TaxonomyTransformationSet(
        schema_version=2,
        corpus_id=corpus.corpus_id,
        dataset_hash=dataset.dataset_hash,
        source_transformation_commitment_hash=dataset.source_transformation_commitment_artifact.sha256,
        projection_revision=PILOT_TRANSFORMATION_PROJECTION_REVISION,
        records=projected,
    )
    return gold, metrics, transformations


def reserve_locked_test(
    *,
    ledger: PilotRunLedger,
    corpus: PilotFrozenCorpus,
    run_id: str,
    actor: str,
    input_commitment: PilotLockedTestInputCommitment,
    occurred_at: datetime | None = None,
) -> PilotLedgerEvent:
    """在读取 test unit/运行模型前抢占唯一 test 尝试；失败或崩溃也视为已消费。"""

    events = ledger.read_events()
    required_events = {
        "bootstrap_requirement_extraction": any(
            event.event_type == "requirement_extraction_completed" and event.payload.get("split") == "bootstrap"
            for event in events
        ),
        "calibration_requirement_extraction": any(
            event.event_type == "requirement_extraction_completed" and event.payload.get("split") == "calibration"
            for event in events
        ),
        "taxonomy_bootstrap": any(event.event_type == "taxonomy_bootstrap_completed" for event in events),
        "calibration_resolution": any(event.event_type == "calibration_resolution_completed" for event in events),
        "calibration_policy_freeze": any(event.event_type == "calibration_policy_freeze_completed" for event in events),
    }
    missing = sorted(name for name, present in required_events.items() if not present)
    if missing:
        raise PilotArtifactError("pilot_locked_test_prerequisites_missing:" + ",".join(missing))
    verify_pilot_requirement_artifacts(
        root=ledger.path.parent,
        corpus=corpus,
        splits={"bootstrap", "calibration"},
    )
    policy_freeze = verify_pilot_policy_freeze_artifacts(root=ledger.path.parent, corpus=corpus)
    frozen_policy = policy_freeze.frozen_policy
    resolved_occurred_at = occurred_at or datetime.now(timezone.utc)
    if resolved_occurred_at < frozen_policy.calibrated_at:
        raise PilotArtifactError("pilot_locked_test_precedes_policy_freeze")

    return ledger.append(
        event_type="locked_test_started",
        corpus=corpus,
        run_id=run_id,
        actor=actor,
        payload={
            "frozen_policy_hash": frozen_policy.canonical_hash,
            "policy_hash": frozen_policy.policy_hash,
            "calibration_dataset_hash": frozen_policy.calibration_dataset_hash,
            "calibration_gold_hash": frozen_policy.calibration_gold_hash,
            "calibration_coverage_gold_hash": frozen_policy.calibration_coverage_gold_hash,
            "gold_attestation_hash": frozen_policy.calibration_gold_attestation_hash,
            "policy_freeze_event_hash": policy_freeze.event.event_hash,
            "input_commitment": input_commitment.model_dump(mode="json"),
        },
        occurred_at=resolved_occurred_at,
    )


def _verify_locked_test_start_binding(
    *,
    start_event: PilotLedgerEvent,
    commitment: PilotLockedTestInputCommitment,
    policy_freeze: VerifiedPilotPolicyFreeze,
) -> None:
    frozen_policy = policy_freeze.frozen_policy
    expected_payload = {
        "frozen_policy_hash": frozen_policy.canonical_hash,
        "policy_hash": frozen_policy.policy_hash,
        "calibration_dataset_hash": frozen_policy.calibration_dataset_hash,
        "calibration_gold_hash": frozen_policy.calibration_gold_hash,
        "calibration_coverage_gold_hash": frozen_policy.calibration_coverage_gold_hash,
        "gold_attestation_hash": frozen_policy.calibration_gold_attestation_hash,
        "policy_freeze_event_hash": policy_freeze.event.event_hash,
        "input_commitment": commitment.model_dump(mode="json"),
    }
    if start_event.payload != expected_payload or start_event.occurred_at < frozen_policy.calibrated_at:
        raise PilotArtifactError("pilot_locked_test_start_binding_invalid")


def _verify_locked_test_requirement_extractions(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    run_id: str,
    summaries: Mapping[str, PilotRequirementExtractionArtifact],
) -> tuple[dict[str, RequirementUnitExtractionResult], dict[str, ArtifactRef]]:
    expected_documents = {item.document_key: item for item in corpus.documents if item.split == "test"}
    if set(summaries) != set(expected_documents):
        raise PilotArtifactError("pilot_locked_test_requirement_receipt_incomplete")
    snapshots = load_split_snapshots(
        corpus=corpus,
        root=root,
        split="test",
        allow_locked_test=True,
    )
    run_root = (root / "runs" / "locked-test" / run_id).resolve()
    extractions: dict[str, RequirementUnitExtractionResult] = {}
    artifact_refs: dict[str, ArtifactRef] = {}
    for document_key, document in expected_documents.items():
        summary = summaries[document_key]
        path = _verify_exact_artifact(
            root=root,
            artifact=summary.artifact,
            expected_path=run_root / "requirements" / f"{document_key}.json",
            code=f"pilot_locked_test_requirement_artifact_invalid:{document_key}",
        )
        try:
            extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
            section_count = _inventory_section_count(
                document=document,
                snapshot=snapshots[document_key],
            )
        except Exception as exc:  # noqa: BLE001 - test extraction 必须强类型且可按冻结快照重放
            raise PilotArtifactError(f"pilot_locked_test_requirement_schema_invalid:{document_key}") from exc
        if (
            extraction.document_id != document.document_id
            or extraction.document_content_hash != document.source.sha256
            or summary.section_count != section_count
            or summary.chunk_count != extraction.chunk_count
            or summary.unit_count != len(extraction.units)
            or summary.atomic_count != sum(unit.scope_status == "atomic" for unit in extraction.units)
            or summary.issue_count != len(extraction.issues)
        ):
            raise PilotArtifactError(f"pilot_locked_test_requirement_binding_invalid:{document_key}")
        extractions[document_key] = extraction
        artifact_refs[document_key] = ArtifactRef(path=str(path.relative_to(root)), sha256=_file_hash(path))
    return extractions, artifact_refs


def _load_locked_test_evolution_artifacts(
    *,
    root: Path,
    run_root: Path,
    receipt: PilotLockedTestCompletionReceipt | PilotLockedTestFailureReceipt,
    bootstrap: VerifiedPilotBootstrap,
) -> tuple[
    TaxonomyEvolutionPolicy | None,
    dict[str, TaxonomyEvolutionResult] | None,
    dict[str, TaxonomyManifest],
]:
    if receipt.schema_version < 3:
        return None, None, bootstrap.manifests
    if receipt.evolution_policy is None or set(receipt.evolutions) != set(bootstrap.manifests):
        raise PilotArtifactError("pilot_locked_test_evolution_evidence_missing")
    policy_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.evolution_policy,
        expected_path=run_root / "policies" / "evolution-policy.json",
        code="pilot_locked_test_evolution_policy_artifact_invalid",
    )
    evolution_paths = {
        system_key: _verify_exact_artifact(
            root=root,
            artifact=receipt.evolutions[system_key],
            expected_path=run_root / "raw" / "evolutions" / f"{system_key}.json",
            code=f"pilot_locked_test_evolution_artifact_invalid:{system_key}",
        )
        for system_key in sorted(bootstrap.manifests)
    }
    output_manifest_paths = {
        system_key: _verify_exact_artifact(
            root=root,
            artifact=receipt.output_manifests[system_key],
            expected_path=run_root / "manifests" / f"{system_key}.json",
            code=f"pilot_locked_test_output_manifest_artifact_invalid:{system_key}",
        )
        for system_key in sorted(bootstrap.manifests)
    }
    try:
        policy = TaxonomyEvolutionPolicy.model_validate_json(policy_path.read_text(encoding="utf-8"))
        evolutions = {
            system_key: TaxonomyEvolutionResult.model_validate_json(path.read_text(encoding="utf-8"))
            for system_key, path in evolution_paths.items()
        }
        output_manifests = {
            system_key: TaxonomyManifest.model_validate_json(path.read_text(encoding="utf-8"))
            for system_key, path in output_manifest_paths.items()
        }
    except Exception as exc:  # noqa: BLE001 - 回执绑定的 evolve 证据必须严格可重放
        raise PilotArtifactError("pilot_locked_test_evolution_artifact_schema_invalid") from exc
    return policy, evolutions, output_manifests


def _verify_locked_test_prediction_binding(
    *,
    corpus: PilotFrozenCorpus,
    bootstrap: VerifiedPilotBootstrap,
    extractions: Mapping[str, RequirementUnitExtractionResult],
    test_dataset_hash: str,
    frozen_policy: TaxonomyFrozenPolicy,
    resolutions: PilotResolutionSet,
    concept_refs: PilotConceptRefSet,
    predictions: TaxonomyPredictionSet,
    output_manifests: Mapping[str, ArtifactRef],
    output_manifest_hashes: Mapping[str, str],
    evolution_policy: TaxonomyEvolutionPolicy | None = None,
    evolution_results: Mapping[str, TaxonomyEvolutionResult] | None = None,
    output_manifest_models: Mapping[str, TaxonomyManifest] | None = None,
) -> None:
    expected_documents = {item.document_key: item for item in corpus.documents if item.split == "test"}
    expected_units = {
        (document_key, unit.unit_id): expected_documents[document_key].system_key
        for document_key, extraction in extractions.items()
        for unit in extraction.units
    }
    resolution_units = {(item.document_key, item.requirement_unit_id) for item in resolutions.records}
    prediction_units = {(item.document_key, item.requirement_unit_id) for item in predictions.records}
    if resolution_units != set(expected_units) or prediction_units != set(expected_units):
        raise PilotArtifactError("pilot_locked_test_prediction_unit_coverage_invalid")
    for resolution_record in resolutions.records:
        identity = (resolution_record.document_key, resolution_record.requirement_unit_id)
        if (
            resolution_record.system_key != expected_units[identity]
            or resolution_record.split != "test"
            or resolution_record.resolution.requirement_unit_ids != [resolution_record.requirement_unit_id]
        ):
            raise PilotArtifactError(
                f"pilot_locked_test_resolution_unit_binding_invalid:{resolution_record.requirement_unit_id}"
            )
    for prediction_record in predictions.records:
        identity = (prediction_record.document_key, prediction_record.requirement_unit_id)
        if (
            prediction_record.system_key != expected_units[identity]
            or prediction_record.split != "test"
            or prediction_record.record_id
            != pilot_record_id(prediction_record.document_key, prediction_record.requirement_unit_id)
        ):
            raise PilotArtifactError(
                f"pilot_locked_test_prediction_unit_binding_invalid:{prediction_record.requirement_unit_id}"
            )
    if (
        resolutions.output_manifest_hashes != bootstrap.receipt.output_manifest_hashes
        or resolutions.dataset_hash != test_dataset_hash
        or predictions.dataset_hash != test_dataset_hash
        or resolutions.policy_hash != frozen_policy.policy_hash
        or predictions.policy_hash != frozen_policy.policy_hash
        or resolutions.frozen_policy_hash != frozen_policy.canonical_hash
        or predictions.frozen_policy_hash != frozen_policy.canonical_hash
    ):
        raise PilotArtifactError("pilot_locked_test_prediction_binding_invalid")
    if evolution_results is None:
        if (
            evolution_policy is not None
            or output_manifest_models is not None
            or dict(output_manifests) != bootstrap.receipt.output_manifests
            or dict(output_manifest_hashes) != bootstrap.receipt.output_manifest_hashes
        ):
            raise PilotArtifactError("pilot_locked_test_prediction_binding_invalid")
        resolved_output_manifests = bootstrap.manifests
    else:
        if evolution_policy is None or output_manifest_models is None:
            raise PilotArtifactError("pilot_locked_test_evolution_evidence_missing")
        requirement_units = {unit.unit_id: unit for extraction in extractions.values() for unit in extraction.units}
        rebuilt_manifests = build_evolution_draft_manifests(
            active_manifests=bootstrap.manifests,
            evolution_results=evolution_results,
            requirement_units=requirement_units,
        )
        if rebuilt_manifests != dict(output_manifest_models):
            raise PilotArtifactError("pilot_locked_test_evolution_manifest_projection_mismatch")
        if (
            predictions.output_manifest_artifacts != dict(output_manifests)
            or predictions.output_manifest_hashes != dict(output_manifest_hashes)
            or {system_key: manifest_hash(manifest) for system_key, manifest in output_manifest_models.items()}
            != dict(output_manifest_hashes)
        ):
            raise PilotArtifactError("pilot_locked_test_evolution_manifest_binding_invalid")
        for system_key, evolution in evolution_results.items():
            if (
                evolution.policy_version != evolution_policy.canonical_hash
                or predictions.prompt_revisions.get("taxonomy_evolution") != evolution.prompt_revision
                or predictions.model_revisions.get("taxonomy_evolution") != evolution.model_revision
            ):
                raise PilotArtifactError(f"pilot_locked_test_evolution_binding_invalid:{system_key}")
            novel_units = [
                requirement_units[item.requirement_unit_id]
                for item in resolutions.records
                if item.system_key == system_key
                and item.resolution.status == "unresolved"
                and item.resolution.unresolved_kind == "novel"
            ]
            try:
                validate_taxonomy_evolution_result_replay(
                    active_manifest=bootstrap.manifests[system_key],
                    requirement_units=novel_units,
                    policy=evolution_policy,
                    result=evolution,
                    impact_snapshot={},
                )
            except ValueError as exc:
                raise PilotArtifactError(f"pilot_locked_test_evolution_replay_invalid:{system_key}") from exc
        resolved_output_manifests = dict(output_manifest_models)
    projected = project_resolution_predictions(
        resolutions=resolutions,
        concept_refs=concept_refs.by_concept_id,
        manifests=bootstrap.manifests,
        manifest_artifacts=output_manifests,
        evolution_results=evolution_results,
        output_manifests=resolved_output_manifests if evolution_results is not None else None,
    )
    if projected != predictions:
        raise PilotArtifactError("pilot_locked_test_prediction_projection_mismatch")


@dataclass(frozen=True)
class VerifiedPilotLockedTestFailure:
    start_event: PilotLedgerEvent
    failure_event: PilotLedgerEvent
    receipt: PilotLockedTestFailureReceipt
    source_coverage_metrics: PilotCoverageVerificationMetrics | None


def verify_pilot_locked_test_failure_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
) -> VerifiedPilotLockedTestFailure:
    """校验唯一失败终态；来源覆盖失败必须能从冻结输入和提取产物重放。"""

    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    starts = [event for event in events if event.event_type == "locked_test_started"]
    failures = [event for event in events if event.event_type == "locked_test_failed"]
    completions = [event for event in events if event.event_type == "locked_test_completed"]
    if (
        len(starts) != 1
        or len(failures) != 1
        or completions
        or starts[0].run_id != failures[0].run_id
        or starts[0].sequence >= failures[0].sequence
    ):
        raise PilotArtifactError("pilot_locked_test_failure_event_invalid")
    start_event = starts[0]
    failure_event = failures[0]
    try:
        commitment = PilotLockedTestInputCommitment.model_validate(start_event.payload["input_commitment"])
        receipt = PilotLockedTestFailureReceipt.model_validate(failure_event.payload)
    except Exception as exc:  # noqa: BLE001 - 台账失败终态也必须可强类型重放
        raise PilotArtifactError("pilot_locked_test_failure_payload_invalid") from exc
    if receipt.schema_version != commitment.schema_version:
        raise PilotArtifactError("pilot_locked_test_failure_commitment_schema_mismatch")
    policy_freeze = verify_pilot_policy_freeze_artifacts(root=root, corpus=corpus)
    _verify_locked_test_start_binding(
        start_event=start_event,
        commitment=commitment,
        policy_freeze=policy_freeze,
    )
    if receipt.failure_kind == "execution":
        return VerifiedPilotLockedTestFailure(
            start_event=start_event,
            failure_event=failure_event,
            receipt=receipt,
            source_coverage_metrics=None,
        )

    run_root = (root / "runs" / "locked-test" / failure_event.run_id).resolve()
    if (
        receipt.test_dataset_hash is None
        or receipt.frozen_policy_hash is None
        or receipt.dataset is None
        or receipt.resolutions is None
        or receipt.concept_refs is None
        or receipt.predictions is None
        or receipt.source_gold is None
        or receipt.source_coverage_metrics is None
        or receipt.gate is None
        or receipt.report is None
        or (
            receipt.schema_version >= 2
            and (receipt.source_transformation_commitment is None or receipt.transformation_projection_revision is None)
        )
    ):
        raise PilotArtifactError("pilot_locked_test_quality_failure_evidence_missing")
    dataset_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.dataset,
        expected_path=root / f"locked-test-dataset-{failure_event.run_id}.json",
        code="pilot_locked_test_failure_dataset_artifact_invalid",
    )
    resolution_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.resolutions,
        expected_path=run_root / "raw" / "resolutions.json",
        code="pilot_locked_test_failure_resolution_artifact_invalid",
    )
    concept_ref_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.concept_refs,
        expected_path=run_root / "artifacts" / "concept-refs.json",
        code="pilot_locked_test_failure_concept_ref_artifact_invalid",
    )
    prediction_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.predictions,
        expected_path=run_root / "predictions" / "predictions.json",
        code="pilot_locked_test_failure_prediction_artifact_invalid",
    )
    source_gold_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.source_gold,
        expected_path=run_root / "reviews" / "test-source-gold.json",
        code="pilot_locked_test_failure_source_gold_artifact_invalid",
    )
    source_transformation_path: Path | None = None
    if receipt.schema_version >= 2:
        assert receipt.source_transformation_commitment is not None
        source_transformation_path = _verify_exact_artifact(
            root=root,
            artifact=receipt.source_transformation_commitment,
            expected_path=run_root / "reviews" / "source-transformations.json",
            code="pilot_locked_test_failure_source_transformation_artifact_invalid",
        )
    metrics_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.source_coverage_metrics,
        expected_path=run_root / "evaluation" / "source-coverage-metrics.json",
        code="pilot_locked_test_failure_coverage_metrics_artifact_invalid",
    )
    gate_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.gate,
        expected_path=run_root / "evaluation" / "gate.json",
        code="pilot_locked_test_failure_gate_artifact_invalid",
    )
    report_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.report,
        expected_path=run_root / "evaluation" / "SOURCE-COVERAGE-FAILURE.md",
        code="pilot_locked_test_failure_report_artifact_invalid",
    )
    if (
        receipt.source_gold.sha256 != commitment.source_gold_sha256
        or receipt.gate.sha256 != commitment.gate_sha256
        or (
            receipt.schema_version >= 2
            and (
                receipt.source_transformation_commitment is None
                or receipt.source_transformation_commitment.sha256 != commitment.source_transformation_commitment_sha256
            )
        )
        or (
            receipt.schema_version == 3
            and (
                receipt.evolution_policy is None
                or receipt.evolution_policy.sha256 != commitment.evolution_policy_sha256
            )
        )
    ):
        raise PilotArtifactError("pilot_locked_test_failure_commitment_mismatch")
    try:
        dataset = TaxonomyDatasetManifest.model_validate_json(dataset_path.read_text(encoding="utf-8"))
        resolutions = PilotResolutionSet.model_validate_json(resolution_path.read_text(encoding="utf-8"))
        concept_refs = PilotConceptRefSet.model_validate_json(concept_ref_path.read_text(encoding="utf-8"))
        predictions = TaxonomyPredictionSet.model_validate_json(prediction_path.read_text(encoding="utf-8"))
        source_gold = PilotCoverageGoldSet.model_validate_json(source_gold_path.read_text(encoding="utf-8"))
        source_transformations = (
            PilotSourceTransformationCommitment.model_validate_json(
                source_transformation_path.read_text(encoding="utf-8")
            )
            if source_transformation_path is not None
            else None
        )
        gate = TaxonomyEvaluationGate.model_validate_json(gate_path.read_text(encoding="utf-8"))
        if receipt.schema_version >= 2:
            validate_pilot_locked_test_gate(gate)
        metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        expected_metric_keys = {
            "coverage_record_count",
            "expected_fact_count",
            "matched_fact_count",
            "extracted_unit_count",
            "matched_extracted_unit_count",
        }
        if not isinstance(metrics_payload, dict) or set(metrics_payload) != expected_metric_keys:
            raise ValueError("pilot_locked_test_failure_metrics_shape_invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in metrics_payload.values()
        ):
            raise ValueError("pilot_locked_test_failure_metrics_value_invalid")
        metrics = PilotCoverageVerificationMetrics(**metrics_payload)
    except Exception as exc:  # noqa: BLE001 - 失败证据也必须是严格 artifact
        raise PilotArtifactError("pilot_locked_test_failure_artifact_schema_invalid") from exc
    if source_gold.reviewed_at > start_event.occurred_at:
        raise PilotArtifactError("pilot_locked_test_gold_not_frozen_before_reservation")
    if source_transformations is not None:
        if (
            source_transformations.reviewed_at > start_event.occurred_at
            or source_transformations.source_gold_sha256 != commitment.source_gold_sha256
        ):
            raise PilotArtifactError("pilot_locked_test_transformation_commitment_not_frozen")
        _source_transformation_facts(
            corpus=corpus,
            source_gold=source_gold,
            source_transformations=source_transformations,
        )
    extractions, _ = _verify_locked_test_requirement_extractions(
        root=root,
        corpus=corpus,
        run_id=failure_event.run_id,
        summaries=receipt.requirement_extractions,
    )
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    evolution_policy, evolution_results, output_manifest_models = _load_locked_test_evolution_artifacts(
        root=root,
        run_root=run_root,
        receipt=receipt,
        bootstrap=bootstrap,
    )
    expected_documents = {item.document_key: item for item in corpus.documents if item.split == "test"}
    expected_upstream = {
        "bootstrap_event": bootstrap.event.event_hash,
        "bootstrap_identity": bootstrap.receipt.bootstrap_hash,
        "policy_freeze_event": policy_freeze.event.event_hash,
        "calibration_dataset": policy_freeze.frozen_policy.calibration_dataset_hash,
        "frozen_policy": policy_freeze.frozen_policy.canonical_hash,
        "runtime_manifest": _file_hash(root / "runtime" / "model-bundle.json"),
        **{
            f"output_manifest.{system_key}": value
            for system_key, value in sorted(bootstrap.receipt.output_manifest_hashes.items())
        },
        **(
            {"evolution_policy": receipt.evolution_policy.sha256}
            if receipt.schema_version == 3 and receipt.evolution_policy is not None
            else {}
        ),
    }
    expected_gold_placeholder = ArtifactRef(
        path=str((run_root / "reviews" / "test-gold-derived.json").relative_to(root)),
        sha256="0" * 64,
    )
    expected_projection_placeholder = ArtifactRef(
        path=str((run_root / "evaluation" / "transformation-projection.json").relative_to(root)),
        sha256="0" * 64,
    )
    if receipt.frozen_policy_hash != policy_freeze.frozen_policy.canonical_hash:
        raise PilotArtifactError("pilot_locked_test_failure_policy_binding_invalid")
    if (
        dataset.schema_version != _LOCKED_TEST_DATASET_SCHEMA_BY_RECEIPT_SCHEMA[receipt.schema_version]
        or dataset.evaluation_split != "test"
        or dataset.corpus_id != corpus.corpus_id
        or dataset.source_commitment_hash != corpus.source_commitment_hash
        or dataset.upstream_artifact_hashes != expected_upstream
        or dataset.created_at != corpus.frozen_at
        or dataset.dataset_hash != receipt.test_dataset_hash
        or dataset.gold_artifact != expected_gold_placeholder
        or dataset.prediction_artifact != receipt.predictions
        or dataset.prompt_revisions != resolutions.prompt_revisions
        or dataset.prompt_revisions != predictions.prompt_revisions
        or dataset.model_revisions != resolutions.model_revisions
        or dataset.model_revisions != predictions.model_revisions
        or {item.document_key for item in dataset.documents} != set(expected_documents)
        or (
            receipt.schema_version >= 2
            and (
                dataset.source_transformation_commitment_artifact != receipt.source_transformation_commitment
                or dataset.transformation_projection_artifact != expected_projection_placeholder
                or dataset.transformation_projection_revision != receipt.transformation_projection_revision
            )
        )
    ):
        raise PilotArtifactError("pilot_locked_test_failure_dataset_binding_invalid")
    if receipt.schema_version == 1:
        assert dataset.transformation_artifact is not None
        _verify_exact_artifact(
            root=root,
            artifact=dataset.transformation_artifact,
            expected_path=run_root / "evaluation" / "transformations.json",
            code="pilot_locked_test_failure_transformation_artifact_invalid",
        )
    extraction_refs = {
        document_key: summary.artifact for document_key, summary in receipt.requirement_extractions.items()
    }
    dataset_documents = {item.document_key: item for item in dataset.documents}
    for document_key, document in expected_documents.items():
        dataset_document = dataset_documents[document_key]
        if (
            dataset_document.document_id != document.document_id
            or dataset_document.system_key != document.system_key
            or dataset_document.system_id != document.system_id
            or dataset_document.split != "test"
            or dataset_document.source != document.source
            or dataset_document.requirement_units != extraction_refs[document_key]
        ):
            raise PilotArtifactError(f"pilot_locked_test_failure_dataset_binding_invalid:{document_key}")
    _verify_locked_test_prediction_binding(
        corpus=corpus,
        bootstrap=bootstrap,
        extractions=extractions,
        test_dataset_hash=receipt.test_dataset_hash,
        frozen_policy=policy_freeze.frozen_policy,
        resolutions=resolutions,
        concept_refs=concept_refs,
        predictions=predictions,
        output_manifests=receipt.output_manifests,
        output_manifest_hashes=receipt.output_manifest_hashes,
        evolution_policy=evolution_policy,
        evolution_results=evolution_results,
        output_manifest_models=output_manifest_models if evolution_results is not None else None,
    )
    try:
        _derive_locked_test_gold_records(
            root=root,
            corpus=corpus,
            extractions=extractions,
            source_gold=source_gold,
        )
    except PilotSourceCoverageError as exc:
        replayed_error = exc
    else:
        raise PilotArtifactError("pilot_locked_test_failure_not_reproducible")
    if replayed_error.metrics != metrics or replayed_error.findings != receipt.findings:
        raise PilotArtifactError("pilot_locked_test_failure_projection_mismatch")
    expected_report = render_locked_test_source_coverage_failure(metrics, receipt.findings)
    if report_path.read_text(encoding="utf-8").rstrip("\n") != expected_report.rstrip("\n"):
        raise PilotArtifactError("pilot_locked_test_failure_report_projection_mismatch")
    return VerifiedPilotLockedTestFailure(
        start_event=start_event,
        failure_event=failure_event,
        receipt=receipt,
        source_coverage_metrics=metrics,
    )


@dataclass(frozen=True)
class VerifiedPilotLockedTest:
    start_event: PilotLedgerEvent
    completion_event: PilotLedgerEvent
    receipt: PilotLockedTestCompletionReceipt
    dataset: TaxonomyDatasetManifest
    predictions: TaxonomyPredictionSet
    source_gold: PilotCoverageGoldSet
    derived_gold: TaxonomyGoldSet
    evaluation: TaxonomyEvaluationResult


def verify_pilot_locked_test_artifacts(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
) -> VerifiedPilotLockedTest:
    """重放唯一 locked test 的输入 commitment、机械投影、source gold 和评估结果。"""

    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    starts = [event for event in events if event.event_type == "locked_test_started"]
    completions = [event for event in events if event.event_type == "locked_test_completed"]
    failures = [event for event in events if event.event_type == "locked_test_failed"]
    if (
        len(starts) != 1
        or len(completions) != 1
        or failures
        or starts[0].run_id != completions[0].run_id
        or starts[0].sequence >= completions[0].sequence
    ):
        raise PilotArtifactError("pilot_locked_test_completion_event_invalid")
    start_event = starts[0]
    completion_event = completions[0]
    try:
        commitment = PilotLockedTestInputCommitment.model_validate(start_event.payload["input_commitment"])
        receipt = PilotLockedTestCompletionReceipt.model_validate(completion_event.payload)
    except Exception as exc:  # noqa: BLE001 - 台账必须可强类型重放
        raise PilotArtifactError("pilot_locked_test_completion_payload_invalid") from exc
    if receipt.schema_version != commitment.schema_version:
        raise PilotArtifactError("pilot_locked_test_completion_commitment_schema_mismatch")
    run_root = (root / "runs" / "locked-test" / completion_event.run_id).resolve()
    dataset_path = _verify_exact_artifact(
        root=root,
        artifact=receipt.dataset,
        expected_path=root / f"locked-test-dataset-{completion_event.run_id}.json",
        code="pilot_locked_test_dataset_artifact_invalid",
    )
    artifact_specs = [
        (receipt.resolutions, run_root / "raw" / "resolutions.json", "resolution"),
        (receipt.concept_refs, run_root / "artifacts" / "concept-refs.json", "concept_ref"),
        (receipt.predictions, run_root / "predictions" / "predictions.json", "prediction"),
        (receipt.source_gold, run_root / "reviews" / "test-source-gold.json", "source_gold"),
        (receipt.derived_gold, run_root / "reviews" / "test-gold-derived.json", "derived_gold"),
        (
            receipt.source_coverage_metrics,
            run_root / "evaluation" / "source-coverage-metrics.json",
            "coverage_metrics",
        ),
        (receipt.gate, run_root / "evaluation" / "gate.json", "gate"),
        (receipt.evaluation, run_root / "evaluation" / "evaluation.json", "evaluation"),
        (receipt.report, run_root / "evaluation" / "REPORT.md", "report"),
    ]
    if receipt.schema_version >= 2:
        assert receipt.source_transformation_commitment is not None
        assert receipt.transformation_projection is not None
        artifact_specs.extend(
            (
                (
                    receipt.source_transformation_commitment,
                    run_root / "reviews" / "source-transformations.json",
                    "source_transformation",
                ),
                (
                    receipt.transformation_projection,
                    run_root / "evaluation" / "transformation-projection.json",
                    "transformation_projection",
                ),
            )
        )
    paths = {
        name: _verify_exact_artifact(
            root=root,
            artifact=artifact,
            expected_path=expected_path,
            code=f"pilot_locked_test_{name}_artifact_invalid",
        )
        for artifact, expected_path, name in artifact_specs
    }
    if (
        receipt.source_gold.sha256 != commitment.source_gold_sha256
        or receipt.gate.sha256 != commitment.gate_sha256
        or (
            receipt.schema_version >= 2
            and (
                receipt.source_transformation_commitment is None
                or receipt.source_transformation_commitment.sha256 != commitment.source_transformation_commitment_sha256
            )
        )
        or (
            receipt.schema_version == 3
            and (
                receipt.evolution_policy is None
                or receipt.evolution_policy.sha256 != commitment.evolution_policy_sha256
            )
        )
    ):
        raise PilotArtifactError("pilot_locked_test_commitment_mismatch")
    try:
        dataset = TaxonomyDatasetManifest.model_validate_json(dataset_path.read_text(encoding="utf-8"))
        resolutions = PilotResolutionSet.model_validate_json(paths["resolution"].read_text(encoding="utf-8"))
        concept_refs = PilotConceptRefSet.model_validate_json(paths["concept_ref"].read_text(encoding="utf-8"))
        predictions = TaxonomyPredictionSet.model_validate_json(paths["prediction"].read_text(encoding="utf-8"))
        source_gold = PilotCoverageGoldSet.model_validate_json(paths["source_gold"].read_text(encoding="utf-8"))
        source_transformations = (
            PilotSourceTransformationCommitment.model_validate_json(
                paths["source_transformation"].read_text(encoding="utf-8")
            )
            if receipt.schema_version >= 2
            else None
        )
        derived_gold = TaxonomyGoldSet.model_validate_json(paths["derived_gold"].read_text(encoding="utf-8"))
        gate = TaxonomyEvaluationGate.model_validate_json(paths["gate"].read_text(encoding="utf-8"))
        if receipt.schema_version >= 2:
            validate_pilot_locked_test_gate(gate)
        evaluation = TaxonomyEvaluationResult.model_validate_json(paths["evaluation"].read_text(encoding="utf-8"))
        coverage_metrics_payload = json.loads(paths["coverage_metrics"].read_text(encoding="utf-8"))
        transformations = TaxonomyTransformationSet.model_validate_json(
            _resolve_artifact(root, dataset.resolved_transformation_artifact.path).read_text(encoding="utf-8")
        )
    except Exception as exc:  # noqa: BLE001 - completed 必须绑定完整强类型产物
        raise PilotArtifactError("pilot_locked_test_artifact_schema_invalid") from exc

    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    evolution_policy, evolution_results, output_manifest_models = _load_locked_test_evolution_artifacts(
        root=root,
        run_root=run_root,
        receipt=receipt,
        bootstrap=bootstrap,
    )
    policy_freeze = verify_pilot_policy_freeze_artifacts(root=root, corpus=corpus)
    _verify_locked_test_start_binding(
        start_event=start_event,
        commitment=commitment,
        policy_freeze=policy_freeze,
    )
    if source_gold.reviewed_at > start_event.occurred_at:
        raise PilotArtifactError("pilot_locked_test_gold_not_frozen_before_reservation")
    if source_transformations is not None and (
        source_transformations.reviewed_at > start_event.occurred_at
        or source_transformations.source_gold_sha256 != commitment.source_gold_sha256
    ):
        raise PilotArtifactError("pilot_locked_test_transformation_commitment_not_frozen")
    expected_documents = {item.document_key: item for item in corpus.documents if item.split == "test"}
    expected_upstream = {
        "bootstrap_event": bootstrap.event.event_hash,
        "bootstrap_identity": bootstrap.receipt.bootstrap_hash,
        "policy_freeze_event": policy_freeze.event.event_hash,
        "calibration_dataset": policy_freeze.frozen_policy.calibration_dataset_hash,
        "frozen_policy": policy_freeze.frozen_policy.canonical_hash,
        "runtime_manifest": _file_hash(root / "runtime" / "model-bundle.json"),
        **{
            f"output_manifest.{system_key}": value
            for system_key, value in sorted(bootstrap.receipt.output_manifest_hashes.items())
        },
        **(
            {"evolution_policy": receipt.evolution_policy.sha256}
            if receipt.schema_version == 3 and receipt.evolution_policy is not None
            else {}
        ),
    }
    if (
        dataset.schema_version != _LOCKED_TEST_DATASET_SCHEMA_BY_RECEIPT_SCHEMA[receipt.schema_version]
        or dataset.evaluation_split != "test"
        or dataset.corpus_id != corpus.corpus_id
        or dataset.source_commitment_hash != corpus.source_commitment_hash
        or dataset.upstream_artifact_hashes != expected_upstream
        or dataset.created_at != corpus.frozen_at
        or dataset.dataset_hash != receipt.test_dataset_hash
        or receipt.frozen_policy_hash != policy_freeze.frozen_policy.canonical_hash
        or dataset.prompt_revisions != resolutions.prompt_revisions
        or dataset.prompt_revisions != predictions.prompt_revisions
        or dataset.model_revisions != resolutions.model_revisions
        or dataset.model_revisions != predictions.model_revisions
        or {item.document_key for item in dataset.documents} != set(expected_documents)
        or (
            receipt.schema_version >= 2
            and (
                dataset.source_transformation_commitment_artifact != receipt.source_transformation_commitment
                or dataset.transformation_projection_artifact != receipt.transformation_projection
                or dataset.transformation_projection_revision != receipt.transformation_projection_revision
            )
        )
    ):
        raise PilotArtifactError("pilot_locked_test_dataset_binding_invalid")

    extractions, extraction_refs = _verify_locked_test_requirement_extractions(
        root=root,
        corpus=corpus,
        run_id=completion_event.run_id,
        summaries=receipt.requirement_extractions,
    )
    dataset_documents = {item.document_key: item for item in dataset.documents}
    for document_key, document in expected_documents.items():
        dataset_document = dataset_documents[document_key]
        if (
            dataset_document.document_id != document.document_id
            or dataset_document.system_key != document.system_key
            or dataset_document.system_id != document.system_id
            or dataset_document.source != document.source
            or dataset_document.requirement_units != extraction_refs[document_key]
        ):
            raise PilotArtifactError(f"pilot_locked_test_requirement_binding_invalid:{document_key}")

    _verify_locked_test_prediction_binding(
        corpus=corpus,
        bootstrap=bootstrap,
        extractions=extractions,
        test_dataset_hash=dataset.dataset_hash,
        frozen_policy=policy_freeze.frozen_policy,
        resolutions=resolutions,
        concept_refs=concept_refs,
        predictions=predictions,
        output_manifests=receipt.output_manifests,
        output_manifest_hashes=receipt.output_manifest_hashes,
        evolution_policy=evolution_policy,
        evolution_results=evolution_results,
        output_manifest_models=output_manifest_models if evolution_results is not None else None,
    )

    if source_transformations is None:
        rebuilt_gold, coverage_metrics = derive_locked_test_gold(
            root=root,
            corpus=corpus,
            dataset=dataset,
            extractions=extractions,
            source_gold=source_gold,
        )
        rebuilt_transformations = transformations
    else:
        rebuilt_gold, coverage_metrics, rebuilt_transformations = derive_locked_test_evidence(
            root=root,
            corpus=corpus,
            dataset=dataset,
            extractions=extractions,
            source_gold=source_gold,
            source_transformations=source_transformations,
        )
    if (
        rebuilt_gold != derived_gold
        or rebuilt_transformations != transformations
        or coverage_metrics_payload
        != {
            **asdict(coverage_metrics),
        }
    ):
        raise PilotArtifactError("pilot_locked_test_gold_projection_mismatch")
    try:
        validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=dataset_path)
        requirement_units = load_requirement_unit_index(
            dataset=dataset,
            manifest_path=dataset_path,
            document_splits={"test"},
        )
        output_manifests = load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=dataset_path,
            predictions=predictions,
        )
        rebuilt_evaluation = evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=derived_gold,
            predictions=predictions,
            output_manifests=output_manifests,
            requirement_units=requirement_units,
            transformations=transformations,
            frozen_policy=policy_freeze.frozen_policy,
            gate=gate,
            evaluated_at=evaluation.evaluated_at,
        )
    except Exception as exc:  # noqa: BLE001 - evaluator 必须能按相同输入重放
        raise PilotArtifactError("pilot_locked_test_evaluation_replay_invalid") from exc
    if rebuilt_evaluation != evaluation or paths["report"].read_text(encoding="utf-8").rstrip(
        "\n"
    ) != render_taxonomy_evaluation_report(evaluation).rstrip("\n"):
        raise PilotArtifactError("pilot_locked_test_evaluation_projection_mismatch")
    return VerifiedPilotLockedTest(
        start_event=start_event,
        completion_event=completion_event,
        receipt=receipt,
        dataset=dataset,
        predictions=predictions,
        source_gold=source_gold,
        derived_gold=derived_gold,
        evaluation=evaluation,
    )


def pilot_record_id(document_key: str, requirement_unit_id: str) -> str:
    digest = hashlib.sha256(f"{document_key}\0{requirement_unit_id}".encode("utf-8")).hexdigest()
    return f"rec-{digest}"


def build_provisional_bootstrap_gold(
    *,
    corpus_id: str,
    dataset_hash: str,
    bootstrap_results: Mapping[str, TaxonomyBootstrapResult],
    requirement_units: Mapping[str, RequirementUnitExtractionResult],
    documents: Mapping[str, PilotFrozenDocument],
    reviewed_by: str,
    reviewed_at: datetime,
) -> TaxonomyGoldSet:
    """从 bootstrap 草案生成待人工逐 unit 校正的预标；永远标记 provisional。"""

    unit_systems: dict[str, str] = {}
    for document_key, extraction in requirement_units.items():
        document = documents.get(document_key)
        if document is None:
            raise PilotArtifactError(f"pilot_requirement_document_unknown:{document_key}")
        if extraction.document_id != document.document_id:
            raise PilotArtifactError(f"pilot_requirement_document_mismatch:{document_key}")
        if extraction.document_content_hash != document.source.sha256:
            raise PilotArtifactError(f"pilot_requirement_hash_mismatch:{document_key}")
        for unit in extraction.units:
            if (
                unit.system_id != document.system_id
                or unit.document_id != document.document_id
                or unit.document_content_hash != document.source.sha256
            ):
                raise PilotArtifactError(f"pilot_requirement_unit_identity_mismatch:{unit.unit_id}")
            if unit.unit_id in unit_systems:
                raise PilotArtifactError(f"pilot_requirement_unit_duplicate:{unit.unit_id}")
            unit_systems[unit.unit_id] = document.system_key

    assignments: dict[str, tuple[str, str]] = {}
    paths_by_system: dict[str, dict[str, list[str]]] = {}
    expected_nodes: list[TaxonomyGoldNode] = []
    for system_key, result in bootstrap_results.items():
        manifest = result.draft_manifest
        if manifest is None:
            continue
        paths_by_system[system_key] = _manifest_paths(manifest)
        for bootstrap_assignment in result.assignments:
            source_system = unit_systems.get(bootstrap_assignment.requirement_unit_id)
            if source_system is None:
                raise PilotArtifactError(
                    f"pilot_bootstrap_assignment_unit_unknown:{bootstrap_assignment.requirement_unit_id}"
                )
            if source_system != system_key:
                raise PilotArtifactError(
                    f"pilot_bootstrap_assignment_cross_system:{bootstrap_assignment.requirement_unit_id}"
                )
            if bootstrap_assignment.target_stable_key not in paths_by_system[system_key]:
                raise PilotArtifactError(
                    f"pilot_bootstrap_assignment_target_unknown:{bootstrap_assignment.requirement_unit_id}"
                )
            if bootstrap_assignment.requirement_unit_id in assignments:
                raise PilotArtifactError(
                    f"pilot_bootstrap_assignment_duplicate:{bootstrap_assignment.requirement_unit_id}"
                )
            assignments[bootstrap_assignment.requirement_unit_id] = (
                system_key,
                bootstrap_assignment.target_stable_key,
            )
        for node in manifest.nodes:
            evidence_ids = sorted({example.requirement_unit_id for example in (node.in_scope_examples or [])})
            if any(unit_systems.get(unit_id) != system_key for unit_id in evidence_ids):
                raise PilotArtifactError(f"pilot_bootstrap_node_evidence_invalid:{node.stable_key}")
            expected_nodes.append(
                TaxonomyGoldNode(
                    gold_node_key=node.stable_key,
                    system_key=system_key,
                    node_type=node.node_type,
                    parent_gold_node_key=node.parent_stable_key,
                    preferred_stable_key=node.stable_key,
                    evidence_requirement_unit_ids=evidence_ids,
                )
            )

    records: list[TaxonomyGoldRecord] = []
    for document_key, extraction in sorted(requirement_units.items()):
        document = documents[document_key]
        if document.split != "bootstrap":
            continue
        for unit in extraction.units:
            resolved_assignment = assignments.get(unit.unit_id)
            if resolved_assignment is None:
                records.append(
                    TaxonomyGoldRecord(
                        record_id=pilot_record_id(document_key, unit.unit_id),
                        document_key=document_key,
                        system_key=document.system_key,
                        split="dev",
                        requirement_unit_id=unit.unit_id,
                        expected_disposition="abstain",
                        gold_evidence=[unit.source_ref],
                        eligible_for_auto=False,
                    )
                )
                continue
            system_key, stable_key = resolved_assignment
            if system_key != document.system_key:
                raise PilotArtifactError(f"pilot_bootstrap_assignment_cross_system:{unit.unit_id}")
            records.append(
                TaxonomyGoldRecord(
                    record_id=pilot_record_id(document_key, unit.unit_id),
                    document_key=document_key,
                    system_key=document.system_key,
                    split="dev",
                    requirement_unit_id=unit.unit_id,
                    expected_disposition="reuse",
                    expected_primary_stable_key=stable_key,
                    expected_path=paths_by_system[system_key][stable_key],
                    gold_evidence=[unit.source_ref],
                    eligible_for_auto=unit.scope_status == "atomic",
                )
            )
    if not records:
        raise PilotArtifactError("pilot_bootstrap_gold_empty")
    return TaxonomyGoldSet(
        schema_version=1,
        corpus_id=corpus_id,
        dataset_hash=dataset_hash,
        review_method="model_assisted_provisional",
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        records=records,
        expected_nodes=expected_nodes,
    )


def build_evolution_draft_manifests(
    *,
    active_manifests: Mapping[str, TaxonomyManifest],
    evolution_results: Mapping[str, TaxonomyEvolutionResult],
    requirement_units: Mapping[str, RequirementUnit],
) -> dict[str, TaxonomyManifest]:
    """从受校验的 evolve change set 机械生成仅供评估的完整 draft manifest。"""

    if set(evolution_results) != set(active_manifests):
        raise PilotArtifactError("pilot_evolution_systems_mismatch")
    if any(unit_id != unit.unit_id for unit_id, unit in requirement_units.items()):
        raise PilotArtifactError("pilot_evolution_requirement_unit_index_invalid")

    draft_manifests: dict[str, TaxonomyManifest] = {}
    for system_key, active_manifest in sorted(active_manifests.items()):
        evolution = evolution_results[system_key]
        active_hash = manifest_hash(active_manifest)
        if evolution.active_manifest_hash != active_hash:
            raise PilotArtifactError(f"pilot_evolution_manifest_mismatch:{system_key}")

        next_sort_order: dict[str | None, int] = {}
        for active_node in active_manifest.nodes:
            next_sort_order[active_node.parent_stable_key] = max(
                next_sort_order.get(active_node.parent_stable_key, 0),
                active_node.sort_order + 1,
            )
        materialized_nodes: list[TaxonomyNodeManifest] = []
        for operation in sorted(evolution.operations, key=lambda item: item.operation_id):
            evidence_by_unit = {item.requirement_unit_id: item for item in operation.evidence}
            if len(evidence_by_unit) != len(operation.evidence) or set(evidence_by_unit) != set(
                operation.requirement_unit_ids
            ):
                raise PilotArtifactError(f"pilot_evolution_operation_evidence_mismatch:{operation.operation_id}")
            for unit_id, example in evidence_by_unit.items():
                unit = requirement_units.get(unit_id)
                if unit is None or unit.system_id != active_manifest.system_id:
                    raise PilotArtifactError(f"pilot_evolution_requirement_unit_unknown:{unit_id}")
                if example.text != unit.source_quote or example.document_content_hash != unit.document_content_hash:
                    raise PilotArtifactError(f"pilot_evolution_requirement_evidence_mismatch:{unit_id}")
            for proposed_node in sorted(operation.proposed_nodes, key=lambda item: item.stable_key):
                parent_key = proposed_node.parent_stable_key
                sort_order = next_sort_order.get(parent_key, 0)
                next_sort_order[parent_key] = sort_order + 1
                try:
                    node_examples = [evidence_by_unit[unit_id] for unit_id in proposed_node.requirement_unit_ids]
                except KeyError as exc:
                    raise PilotArtifactError(
                        f"pilot_evolution_node_evidence_mismatch:{proposed_node.stable_key}"
                    ) from exc
                materialized_nodes.append(
                    TaxonomyNodeManifest(
                        stable_key=proposed_node.stable_key,
                        node_type=proposed_node.node_type,
                        display_name=proposed_node.display_name,
                        parent_stable_key=proposed_node.parent_stable_key,
                        aliases=proposed_node.aliases,
                        sort_order=sort_order,
                        node_status="active",
                        definition=proposed_node.definition,
                        scope_note=proposed_node.scope_note,
                        in_scope_examples=node_examples,
                        out_of_scope_examples=[],
                    )
                )
        if not materialized_nodes:
            draft_manifests[system_key] = active_manifest
            continue
        try:
            draft_manifests[system_key] = TaxonomyManifest(
                schema_version=2,
                system_id=active_manifest.system_id,
                version=active_manifest.version + 1,
                change_note=f"locked-test evolve draft {evolution.proposal_hash or evolution.input_hash}",
                created_by="taxonomy-pilot-evolve",
                nodes=[*active_manifest.nodes, *materialized_nodes],
                mappings=active_manifest.mappings,
            )
        except Exception as exc:  # noqa: BLE001 - 完整 draft manifest 必须 fail closed
            raise PilotArtifactError(f"pilot_evolution_output_manifest_invalid:{system_key}") from exc
    return draft_manifests


def _evolution_prediction_input_hash(
    *,
    resolution_input_hash: str,
    evolution_input_hash: str,
    operation_id: str | None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "resolution_input_hash": resolution_input_hash,
                "evolution_input_hash": evolution_input_hash,
                "operation_id": operation_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def project_resolution_predictions(
    *,
    resolutions: PilotResolutionSet,
    concept_refs: Mapping[UUID, PilotConceptRef],
    manifests: Mapping[str, TaxonomyManifest],
    manifest_artifacts: Mapping[str, ArtifactRef],
    evolution_results: Mapping[str, TaxonomyEvolutionResult] | None = None,
    output_manifests: Mapping[str, TaxonomyManifest] | None = None,
) -> TaxonomyPredictionSet:
    """从 resolver/evolve 原始产物机械投影评估记录。"""

    paths = {system_key: _manifest_paths(manifest) for system_key, manifest in manifests.items()}
    resolved_output_manifests = dict(output_manifests or manifests)
    if set(resolved_output_manifests) != set(manifests):
        raise PilotArtifactError("pilot_resolution_output_manifest_systems_mismatch")
    if evolution_results is None and output_manifests is not None and resolved_output_manifests != dict(manifests):
        raise PilotArtifactError("pilot_resolution_output_manifest_without_evolution")
    output_manifest_hashes: dict[str, str] = {}
    active_manifest_hashes: dict[str, str] = {}
    known_nodes: list[TaxonomyKnownNode] = []
    manifest_keys: dict[str, set[str]] = {}
    if set(manifest_artifacts) != set(manifests):
        raise PilotArtifactError("pilot_resolution_manifest_artifacts_incomplete")
    for system_key, manifest in manifests.items():
        active_manifest_hash = manifest_hash(manifest)
        active_manifest_hashes[system_key] = active_manifest_hash
        output_manifest_hashes[system_key] = manifest_hash(resolved_output_manifests[system_key])
        manifest_keys[system_key] = {node.stable_key for node in manifest.nodes if node.node_status == "active"}
        if resolutions.output_manifest_hashes.get(system_key) != active_manifest_hash:
            raise PilotArtifactError(f"pilot_resolution_manifest_hash_mismatch:{system_key}")
        known_nodes.extend(
            TaxonomyKnownNode(
                system_key=system_key,
                stable_key=node.stable_key,
                node_type=node.node_type,
                parent_stable_key=node.parent_stable_key,
            )
            for node in manifest.nodes
        )

    operation_by_unit: dict[str, TaxonomyEvolutionOperation] = {}
    evolution_by_system: dict[str, TaxonomyEvolutionResult] = {}
    proposed_nodes: list[TaxonomyProposedNode] = []
    tree_diff: list[dict[str, object]] = []
    if evolution_results is not None:
        if set(evolution_results) != set(manifests):
            raise PilotArtifactError("pilot_evolution_systems_mismatch")
        units_by_id = {item.requirement_unit_id: item for item in resolutions.records}
        if len(units_by_id) != len(resolutions.records):
            raise PilotArtifactError("pilot_resolution_requirement_unit_duplicate")
        expected_novel_by_system: dict[str, set[str]] = {
            system_key: {
                item.requirement_unit_id
                for item in resolutions.records
                if item.system_key == system_key
                and item.resolution.status == "unresolved"
                and item.resolution.unresolved_kind == "novel"
            }
            for system_key in manifests
        }
        for system_key, evolution in sorted(evolution_results.items()):
            if evolution.active_manifest_hash != manifest_hash(manifests[system_key]):
                raise PilotArtifactError(f"pilot_evolution_manifest_mismatch:{system_key}")
            for issue in evolution.issues:
                issue_unit_ids = issue.requirement_unit_ids
                if (
                    len(issue_unit_ids) != len(set(issue_unit_ids))
                    or not set(issue_unit_ids) <= expected_novel_by_system[system_key]
                ):
                    raise PilotArtifactError(f"pilot_evolution_issue_unit_invalid:{system_key}")
            referenced = [unit_id for operation in evolution.operations for unit_id in operation.requirement_unit_ids]
            referenced.extend(evolution.unresolved_requirement_unit_ids)
            if set(referenced) != expected_novel_by_system[system_key] or len(referenced) != len(set(referenced)):
                raise PilotArtifactError(f"pilot_evolution_novel_partition_invalid:{system_key}")
            evolution_by_system[system_key] = evolution
            for operation in sorted(evolution.operations, key=lambda item: item.operation_id):
                for unit_id in operation.requirement_unit_ids:
                    operation_by_unit[unit_id] = operation
                tree_diff.append(
                    {
                        "system_key": system_key,
                        "evolution_input_hash": evolution.input_hash,
                        "operation": operation.model_dump(mode="json"),
                    }
                )
                proposed_nodes.extend(
                    TaxonomyProposedNode(
                        system_key=system_key,
                        stable_key=node.stable_key,
                        node_type=node.node_type,
                        display_name=node.display_name,
                        parent_stable_key=node.parent_stable_key,
                        aliases=node.aliases,
                        evidence_requirement_unit_ids=node.requirement_unit_ids,
                    )
                    for node in operation.proposed_nodes
                )

    projected: list[TaxonomyPredictionRecord] = []
    for raw in sorted(resolutions.records, key=lambda item: (item.document_key, item.requirement_unit_id)):
        resolution = raw.resolution
        if resolution.taxonomy_version_id != resolutions.taxonomy_version_ids[raw.system_key]:
            raise PilotArtifactError(f"pilot_resolution_taxonomy_version_mismatch:{raw.requirement_unit_id}")
        if resolution.taxonomy_manifest_hash != active_manifest_hashes[raw.system_key]:
            raise PilotArtifactError(f"pilot_resolution_manifest_mismatch:{raw.requirement_unit_id}")
        if resolution.policy_version != resolutions.policy_hash:
            raise PilotArtifactError(f"pilot_resolution_policy_mismatch:{raw.requirement_unit_id}")
        if resolution.requirement_unit_ids != [raw.requirement_unit_id]:
            raise PilotArtifactError(f"pilot_resolution_unit_identity_mismatch:{raw.requirement_unit_id}")
        for candidate in resolution.candidates:
            candidate_ref = concept_refs.get(candidate.concept_id)
            if candidate_ref is None:
                raise PilotArtifactError(f"pilot_resolution_candidate_concept_unknown:{raw.requirement_unit_id}")
            if candidate_ref.system_key != raw.system_key:
                raise PilotArtifactError(f"pilot_resolution_candidate_cross_system:{raw.requirement_unit_id}")
            if candidate_ref.stable_key != candidate.stable_key:
                raise PilotArtifactError(f"pilot_resolution_candidate_concept_mismatch:{raw.requirement_unit_id}")
            if candidate.stable_key not in manifest_keys[raw.system_key]:
                raise PilotArtifactError(f"pilot_resolution_candidate_not_active:{raw.requirement_unit_id}")
        if resolution.status == "mapped":
            assert resolution.primary_concept_id is not None
            concept_ref = concept_refs.get(resolution.primary_concept_id)
            if concept_ref is None:
                raise PilotArtifactError(f"pilot_resolution_concept_unknown:{raw.requirement_unit_id}")
            if concept_ref.system_key != raw.system_key:
                raise PilotArtifactError(f"pilot_resolution_concept_cross_system:{raw.requirement_unit_id}")
            stable_key = concept_ref.stable_key
            if stable_key not in manifest_keys[raw.system_key]:
                raise PilotArtifactError(f"pilot_resolution_concept_not_in_manifest:{raw.requirement_unit_id}")
            related = []
            for concept_id in resolution.related_concept_ids:
                related_ref = concept_refs.get(concept_id)
                if related_ref is None:
                    raise PilotArtifactError(f"pilot_resolution_related_concept_unknown:{raw.requirement_unit_id}")
                if related_ref.system_key != raw.system_key:
                    raise PilotArtifactError(f"pilot_resolution_related_concept_cross_system:{raw.requirement_unit_id}")
                related_key = related_ref.stable_key
                if related_key not in manifest_keys[raw.system_key]:
                    raise PilotArtifactError(
                        f"pilot_resolution_related_concept_not_in_manifest:{raw.requirement_unit_id}"
                    )
                related.append(related_key)
            if resolution.method == "approved_mapping":
                projected.append(
                    TaxonomyPredictionRecord(
                        record_id=pilot_record_id(raw.document_key, raw.requirement_unit_id),
                        document_key=raw.document_key,
                        system_key=raw.system_key,
                        split=raw.split,
                        requirement_unit_id=raw.requirement_unit_id,
                        input_hash=resolution.input_hash,
                        outcome="approved_mapping",
                        predicted_primary_stable_key=stable_key,
                        predicted_related_stable_keys=sorted(related),
                        predicted_path=paths[raw.system_key][stable_key],
                        latency_ms=raw.latency_ms,
                        cost_usd=raw.cost_usd,
                        write_disposition="none",
                    )
                )
            else:
                top = sorted(resolution.candidates, key=lambda item: item.rank)[0]
                if top.concept_id != resolution.primary_concept_id or top.stable_key != stable_key:
                    raise PilotArtifactError(f"pilot_resolution_candidate_concept_mismatch:{raw.requirement_unit_id}")
                projected.append(
                    TaxonomyPredictionRecord(
                        record_id=pilot_record_id(raw.document_key, raw.requirement_unit_id),
                        document_key=raw.document_key,
                        system_key=raw.system_key,
                        split=raw.split,
                        requirement_unit_id=raw.requirement_unit_id,
                        input_hash=resolution.input_hash,
                        outcome="candidate",
                        predicted_primary_stable_key=stable_key,
                        predicted_related_stable_keys=sorted(related),
                        predicted_path=paths[raw.system_key][stable_key],
                        score=top.score,
                        margin=resolution.margin,
                        scope_conflict=top.scope_conflict,
                        latency_ms=raw.latency_ms,
                        cost_usd=raw.cost_usd,
                        write_disposition="none",
                    )
                )
        elif resolution.status == "unresolved":
            unit_evolution = evolution_by_system.get(raw.system_key)
            unit_operation = operation_by_unit.get(raw.requirement_unit_id)
            if resolution.unresolved_kind == "novel" and unit_evolution is not None and unit_operation is not None:
                projected.append(
                    TaxonomyPredictionRecord(
                        record_id=pilot_record_id(raw.document_key, raw.requirement_unit_id),
                        document_key=raw.document_key,
                        system_key=raw.system_key,
                        split=raw.split,
                        requirement_unit_id=raw.requirement_unit_id,
                        input_hash=_evolution_prediction_input_hash(
                            resolution_input_hash=resolution.input_hash,
                            evolution_input_hash=unit_evolution.input_hash,
                            operation_id=unit_operation.operation_id,
                        ),
                        outcome="proposal",
                        predicted_operation=unit_operation.operation,
                        latency_ms=raw.latency_ms,
                        cost_usd=raw.cost_usd,
                        write_disposition="draft",
                    )
                )
                continue
            input_hash = resolution.input_hash
            if resolution.unresolved_kind == "novel" and unit_evolution is not None:
                input_hash = _evolution_prediction_input_hash(
                    resolution_input_hash=resolution.input_hash,
                    evolution_input_hash=unit_evolution.input_hash,
                    operation_id=None,
                )
            projected.append(
                TaxonomyPredictionRecord(
                    record_id=pilot_record_id(raw.document_key, raw.requirement_unit_id),
                    document_key=raw.document_key,
                    system_key=raw.system_key,
                    split=raw.split,
                    requirement_unit_id=raw.requirement_unit_id,
                    input_hash=input_hash,
                    outcome="unresolved",
                    unresolved_kind=resolution.unresolved_kind,
                    latency_ms=raw.latency_ms,
                    cost_usd=raw.cost_usd,
                    write_disposition="none",
                )
            )
        else:
            raise PilotArtifactError(f"pilot_resolution_status_not_projectable:{resolution.status}")

    return TaxonomyPredictionSet(
        schema_version=2,
        run_id=resolutions.run_id,
        generated_at=resolutions.generated_at,
        dataset_hash=resolutions.dataset_hash,
        policy_hash=resolutions.policy_hash,
        frozen_policy_hash=resolutions.frozen_policy_hash,
        prompt_revisions=resolutions.prompt_revisions,
        model_revisions=resolutions.model_revisions,
        records=projected,
        proposed_nodes=proposed_nodes,
        known_nodes=known_nodes,
        output_manifest_hashes=output_manifest_hashes,
        output_manifest_artifacts=dict(manifest_artifacts),
        tree_diff=tree_diff,
    )


def write_json_once(path: Path, value: object) -> None:
    _write_json_once(path, value)


def write_json_atomic_once(path: Path, value: object) -> None:
    """原子发布不可变 JSON；失败时目标不存在，已存在时绝不覆盖。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        value.model_dump_json(indent=2)
        if hasattr(value, "model_dump_json")
        else json.dumps(value, ensure_ascii=False, indent=2, default=str)
    )
    temporary = path.parent / f".{path.name}.tmp-{uuid4().hex}"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def write_text_once(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)
        if not value.endswith("\n"):
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_once(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        value.model_dump_json(indent=2)
        if hasattr(value, "model_dump_json")
        else json.dumps(value, ensure_ascii=False, indent=2, default=str)
    )
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _resolve_artifact(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise PilotArtifactError("pilot_artifact_path_escape")
    return candidate


def _verify_exact_artifact(
    *,
    root: Path,
    artifact: ArtifactRef,
    expected_path: Path,
    code: str,
) -> Path:
    if Path(artifact.path).is_absolute():
        raise PilotArtifactError(code)
    path = _resolve_artifact(root, artifact.path)
    if path != expected_path.resolve() or not path.is_file() or _file_hash(path) != artifact.sha256:
        raise PilotArtifactError(code)
    return path


def _verify_artifact_ref(*, root: Path, artifact: ArtifactRef, code: str) -> Path:
    if Path(artifact.path).is_absolute():
        raise PilotArtifactError(code)
    path = _resolve_artifact(root, artifact.path)
    if not path.is_file() or _file_hash(path) != artifact.sha256:
        raise PilotArtifactError(code)
    return path


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_paths(manifest: TaxonomyManifest) -> dict[str, list[str]]:
    node_by_key = {node.stable_key: node for node in manifest.nodes}
    paths: dict[str, list[str]] = {}

    def resolve(stable_key: str, visiting: set[str]) -> list[str]:
        if stable_key in paths:
            return paths[stable_key]
        if stable_key in visiting:
            raise PilotArtifactError("pilot_manifest_cycle")
        node = node_by_key.get(stable_key)
        if node is None:
            raise PilotArtifactError(f"pilot_manifest_node_missing:{stable_key}")
        parent_path = resolve(node.parent_stable_key, {*visiting, stable_key}) if node.parent_stable_key else []
        paths[stable_key] = [*parent_path, stable_key]
        return paths[stable_key]

    for key in sorted(node_by_key):
        resolve(key, set())
    return paths
