from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from pydantic import ValidationError

import src.testcase_generator.services.taxonomy_evaluation as taxonomy_evaluation_service
from scripts.taxonomy_generalization_eval import _write_frozen_policy
from scripts.taxonomy_generalization_eval import main as evaluation_cli_main
from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest
from src.testcase_generator.schemas.taxonomy_evaluation import (
    ArtifactRef,
    TaxonomyCalibrationReview,
    TaxonomyCalibrationSystemMetrics,
    TaxonomyDatasetDocument,
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
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
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy
from src.testcase_generator.services.requirement_unit_service import (
    RequirementChunkCoverage,
    RequirementUnitExtractionResult,
    build_requirement_coverage_id,
)
from src.testcase_generator.services.taxonomy_evaluation import (
    RequirementUnitIndex,
    build_calibration_package,
    calibrate_resolution_policy,
    evaluate_taxonomy_generalization,
    load_evaluation_inputs,
    load_requirement_unit_index,
    render_taxonomy_evaluation_report,
    resolve_evaluation_artifact_path,
    validate_calibration_review,
    validate_evaluation_artifact_hashes,
    write_taxonomy_evaluation_artifacts,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
SYSTEM_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SYSTEM_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _hash(char: str) -> str:
    return char * 64


def _artifact(path: str, char: str) -> ArtifactRef:
    return ArtifactRef(path=path, sha256=_hash(char))


def _document(
    key: str,
    *,
    system_key: str,
    system_id: UUID,
    split: str,
    hash_char: str,
) -> TaxonomyDatasetDocument:
    return TaxonomyDatasetDocument.model_validate(
        {
            "document_key": key,
            "document_id": str(uuid5(NAMESPACE_URL, f"taxonomy-pilot:{key}")),
            "system_key": system_key,
            "system_id": str(system_id),
            "split": split,
            "source": {"path": f"/prd/{key}.md", "sha256": _hash(hash_char)},
            "requirement_units": {
                "path": f"artifacts/{key}-units.json",
                "sha256": _hash(hash_char.upper()),
            },
        }
    )


def _dataset(*, duplicate_test_hash: bool = False) -> TaxonomyDatasetManifest:
    documents = [
        _document("drama-v1", system_key="drama", system_id=SYSTEM_A, split="dev", hash_char="1"),
        _document(
            "drama-v2",
            system_key="drama",
            system_id=SYSTEM_A,
            split="test",
            hash_char="1" if duplicate_test_hash else "2",
        ),
        _document("dist-v1", system_key="distribution", system_id=SYSTEM_B, split="dev", hash_char="3"),
        _document("dist-v2", system_key="distribution", system_id=SYSTEM_B, split="test", hash_char="4"),
    ]
    return TaxonomyDatasetManifest(
        schema_version=1,
        corpus_id="cross-prd-pilot-v1",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        created_at=NOW,
        documents=documents,
        gold_artifact=_artifact("gold.json", "5"),
        prediction_artifact=_artifact("predictions.json", "6"),
        transformation_artifact=_artifact("transformations.json", "7"),
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )


def _locked_v3_dataset() -> TaxonomyDatasetManifest:
    return TaxonomyDatasetManifest(
        schema_version=3,
        corpus_id="cross-prd-pilot-v3",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        evaluation_split="test",
        source_commitment_hash="a" * 64,
        upstream_artifact_hashes={"frozen_policy": "b" * 64},
        created_at=NOW,
        documents=[
            _document("drama-v2", system_key="drama", system_id=SYSTEM_A, split="test", hash_char="2"),
            _document("dist-v2", system_key="distribution", system_id=SYSTEM_B, split="test", hash_char="4"),
        ],
        gold_artifact=_artifact("test-gold.json", "5"),
        prediction_artifact=_artifact("test-predictions.json", "6"),
        source_transformation_commitment_artifact=_artifact("source-transformations.json", "7"),
        transformation_projection_artifact=_artifact("transformation-projection.json", "0"),
        transformation_projection_revision="source-fact-unit-projection-v1",
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )


def test_dataset_v2_allows_calibration_stage_without_locked_test_artifacts() -> None:
    dataset = TaxonomyDatasetManifest(
        schema_version=2,
        corpus_id="cross-prd-pilot-v2",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        evaluation_split="dev",
        source_commitment_hash="a" * 64,
        upstream_artifact_hashes={"bootstrap_event": "b" * 64},
        created_at=NOW,
        documents=[
            _document("drama-v1", system_key="drama", system_id=SYSTEM_A, split="dev", hash_char="1"),
            _document("dist-v1", system_key="distribution", system_id=SYSTEM_B, split="dev", hash_char="3"),
        ],
        gold_artifact=_artifact("gold.json", "5"),
        prediction_artifact=_artifact("predictions.json", "6"),
        transformation_artifact=_artifact("transformations.json", "7"),
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )

    assert dataset.evaluation_split == "dev"
    assert {item.split for item in dataset.documents} == {"dev"}


def test_dataset_v3_binds_source_transformation_commitment_without_projection_hash_drift() -> None:
    dataset = _locked_v3_dataset()

    projected = dataset.model_copy(
        update={
            "transformation_projection_artifact": _artifact("transformation-projection.json", "9"),
        }
    )
    changed_commitment = dataset.model_copy(
        update={
            "source_transformation_commitment_artifact": _artifact("source-transformations.json", "8"),
        }
    )
    changed_revision = dataset.model_copy(update={"transformation_projection_revision": "projection-v2"})
    changed_upstream = dataset.model_copy(update={"upstream_artifact_hashes": {"frozen_policy": "c" * 64}})
    changed_source_commitment = dataset.model_copy(update={"source_commitment_hash": "d" * 64})

    assert projected.dataset_hash == dataset.dataset_hash
    assert changed_commitment.dataset_hash != dataset.dataset_hash
    assert changed_revision.dataset_hash != dataset.dataset_hash
    assert changed_upstream.dataset_hash != dataset.dataset_hash
    assert changed_source_commitment.dataset_hash != dataset.dataset_hash


def test_generic_loader_rejects_v3_without_locked_test_receipt_replay(tmp_path: Path) -> None:
    dataset_path = tmp_path / "locked-test-dataset.json"
    dataset_path.write_text(_locked_v3_dataset().model_dump_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset_v3_requires_locked_test_receipt_replay"):
        load_evaluation_inputs(
            dataset_path=dataset_path,
            policy_path=tmp_path / "policy.json",
        )


def test_dataset_v3_rejects_legacy_transformation_artifact() -> None:
    payload = {
        "schema_version": 3,
        "corpus_id": "cross-prd-pilot-v3",
        "pilot_corpus": True,
        "split_strategy": "document_level",
        "test_locked": True,
        "evaluation_split": "test",
        "source_commitment_hash": "a" * 64,
        "upstream_artifact_hashes": {"frozen_policy": "b" * 64},
        "created_at": NOW,
        "documents": [
            _document("drama-v2", system_key="drama", system_id=SYSTEM_A, split="test", hash_char="2"),
            _document("dist-v2", system_key="distribution", system_id=SYSTEM_B, split="test", hash_char="4"),
        ],
        "gold_artifact": _artifact("test-gold.json", "5"),
        "prediction_artifact": _artifact("test-predictions.json", "6"),
        "transformation_artifact": _artifact("legacy-transformations.json", "7"),
        "source_transformation_commitment_artifact": _artifact("source-transformations.json", "8"),
        "transformation_projection_artifact": _artifact("transformation-projection.json", "0"),
        "transformation_projection_revision": "source-fact-unit-projection-v1",
        "prompt_revisions": {"resolver": "resolver@1"},
        "model_revisions": {"taxonomy_resolver": "verify@1"},
    }

    with pytest.raises(ValidationError, match="dataset_v3_legacy_transformation_forbidden"):
        TaxonomyDatasetManifest.model_validate(payload)


def test_legacy_transformation_canonical_hash_keeps_v1_field_set() -> None:
    transformations = TaxonomyTransformationSet(
        schema_version=1,
        corpus_id="cross-prd-pilot-v1",
        records=[],
    )
    expected_payload = {
        "schema_version": 1,
        "corpus_id": "cross-prd-pilot-v1",
        "records": [],
    }
    expected = hashlib.sha256(
        json.dumps(
            expected_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert transformations.canonical_hash == expected


def test_evaluation_accepts_v2_locked_test_bound_to_distinct_calibration_dataset() -> None:
    calibration_dataset = TaxonomyDatasetManifest(
        schema_version=2,
        corpus_id="cross-prd-pilot-v1",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        evaluation_split="dev",
        source_commitment_hash="a" * 64,
        upstream_artifact_hashes={"bootstrap_event": "b" * 64},
        created_at=NOW,
        documents=[
            _document("drama-v1", system_key="drama", system_id=SYSTEM_A, split="dev", hash_char="1"),
            _document("dist-v1", system_key="distribution", system_id=SYSTEM_B, split="dev", hash_char="3"),
        ],
        gold_artifact=_artifact("calibration-gold.json", "5"),
        prediction_artifact=_artifact("calibration-predictions.json", "6"),
        transformation_artifact=_artifact("calibration-transformations.json", "7"),
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )
    calibration_gold = _gold_set(
        calibration_dataset,
        [
            _gold("cal-drama", document_key="drama-v1", system_key="drama", split="dev"),
            _gold("cal-dist", document_key="dist-v1", system_key="distribution", split="dev"),
        ],
    )
    frozen = _frozen_policy(calibration_dataset, calibration_gold)
    test_dataset = TaxonomyDatasetManifest(
        schema_version=2,
        corpus_id="cross-prd-pilot-v1",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        evaluation_split="test",
        source_commitment_hash="a" * 64,
        upstream_artifact_hashes={
            "calibration_dataset": calibration_dataset.dataset_hash,
            "frozen_policy": frozen.canonical_hash,
        },
        created_at=NOW,
        documents=[
            _document("drama-v2", system_key="drama", system_id=SYSTEM_A, split="test", hash_char="2"),
            _document("dist-v2", system_key="distribution", system_id=SYSTEM_B, split="test", hash_char="4"),
        ],
        gold_artifact=_artifact("test-gold.json", "8"),
        prediction_artifact=_artifact("test-predictions.json", "9"),
        transformation_artifact=_artifact("test-transformations.json", "0"),
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )
    test_gold = _gold_set(
        test_dataset,
        [
            _gold("test-drama", document_key="drama-v2", system_key="drama", split="test"),
            _gold("test-dist", document_key="dist-v2", system_key="distribution", split="test"),
        ],
    )
    output_manifests = {
        "drama": _output_manifest(),
        "distribution": _output_manifest(system_id=SYSTEM_B),
    }
    predictions = _predictions(
        test_dataset,
        [
            _prediction("test-drama", document_key="drama-v2", system_key="drama", split="test"),
            _prediction("test-dist", document_key="dist-v2", system_key="distribution", split="test"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        schema_version=2,
        generated_at=NOW + timedelta(minutes=2),
        known_nodes=[
            *_known_node_views("drama", output_manifests["drama"]),
            *_known_node_views("distribution", output_manifests["distribution"]),
        ],
        output_manifest_hashes={
            system_key: manifest_hash(manifest) for system_key, manifest in output_manifests.items()
        },
        output_manifest_artifacts={
            "drama": _artifact("manifests/drama.json", "a"),
            "distribution": _artifact("manifests/distribution.json", "b"),
        },
    )

    result = evaluate_taxonomy_generalization(
        dataset=test_dataset,
        gold=test_gold,
        predictions=predictions,
        output_manifests=output_manifests,
        requirement_units=_requirement_units(test_dataset, test_gold),
        frozen_policy=frozen,
        gate=_gate(),
        evaluated_at=NOW + timedelta(minutes=3),
    )

    assert result.overall_status == "pass"

    tampered_dataset = test_dataset.model_copy(
        update={
            "upstream_artifact_hashes": {
                **(test_dataset.upstream_artifact_hashes or {}),
                "frozen_policy": "f" * 64,
            }
        }
    )
    tampered_gold = test_gold.model_copy(update={"dataset_hash": tampered_dataset.dataset_hash})
    tampered_predictions = predictions.model_copy(update={"dataset_hash": tampered_dataset.dataset_hash})
    with pytest.raises(ValueError, match="test_dataset_frozen_policy_binding_mismatch"):
        evaluate_taxonomy_generalization(
            dataset=tampered_dataset,
            gold=tampered_gold,
            predictions=tampered_predictions,
            output_manifests=output_manifests,
            requirement_units=_requirement_units(tampered_dataset, tampered_gold),
            frozen_policy=frozen,
            gate=_gate(),
            evaluated_at=NOW + timedelta(minutes=3),
        )


def _policy(**overrides: object) -> TaxonomyResolutionPolicy:
    payload: dict[str, object] = {
        "schema_version": 1,
        "top_k": 5,
        "minimum_score": 0.8,
        "minimum_margin": 0.2,
        "out_of_scope_conflict_score": 0.8,
        "decision_context_max_chars": 20_000,
        "require_grounding": True,
        "allowed_node_types": ["module", "capability"],
        "allowed_node_statuses": ["active"],
        "model_role": "taxonomy_resolver",
        "model_revision": "verify@1",
        "fail_behavior": "abstain",
        "auto_accept_signal": "retrieval_score_margin",
    }
    payload.update(overrides)
    return TaxonomyResolutionPolicy.model_validate(payload)


def _gold(
    record_id: str,
    *,
    document_key: str,
    system_key: str,
    split: str,
    expected: str = "reuse",
    primary: str | None = "asset.filter",
    semantic_group_id: str | None = None,
    variant_kind: str = "original",
    document_content_hash: str | None = None,
    eligible_for_auto: bool = True,
) -> TaxonomyGoldRecord:
    source_ref = f"prd:{document_key} §{record_id}"
    statement = f"{document_key} 的固定需求 {record_id}"
    hash_char = {"drama-v1": "1", "drama-v2": "2", "dist-v1": "3", "dist-v2": "4"}[document_key]
    content_hash = document_content_hash or _hash(hash_char)
    payload: dict[str, object] = {
        "record_id": record_id,
        "document_key": document_key,
        "system_key": system_key,
        "split": split,
        "requirement_unit_id": build_requirement_unit_id(
            document_content_hash=content_hash,
            source_ref=source_ref,
            statement=statement,
        ),
        "expected_disposition": expected,
        "expected_primary_stable_key": primary,
        "expected_related_stable_keys": [],
        "acceptable_primary_stable_keys": [],
        "expected_path": ["asset", primary] if primary else [],
        "gold_evidence": [source_ref],
        "eligible_for_auto": eligible_for_auto,
        "semantic_group_id": semantic_group_id,
        "variant_kind": variant_kind,
    }
    if expected == "new_node":
        payload["expected_primary_stable_key"] = None
        payload["expected_new_node_stable_key"] = primary or "task.schedule"
        payload["expected_path"] = []
        payload["expected_operation"] = "add"
    if expected == "abstain":
        payload["expected_primary_stable_key"] = None
        payload["expected_path"] = []
    return TaxonomyGoldRecord.model_validate(payload)


def _prediction(
    record_id: str,
    *,
    document_key: str,
    system_key: str,
    split: str,
    primary: str | None = "asset.filter",
    score: float = 0.9,
    margin: float = 0.3,
    outcome: str = "candidate",
    scope_conflict: bool = False,
    requirement_unit_id: str | None = None,
    cost_usd: float | None = 0.01,
) -> TaxonomyPredictionRecord:
    source_ref = f"prd:{document_key} §{record_id}"
    statement = f"{document_key} 的固定需求 {record_id}"
    hash_char = {"drama-v1": "1", "drama-v2": "2", "dist-v1": "3", "dist-v2": "4"}[document_key]
    payload: dict[str, object] = {
        "record_id": record_id,
        "document_key": document_key,
        "system_key": system_key,
        "split": split,
        "requirement_unit_id": requirement_unit_id
        or build_requirement_unit_id(
            document_content_hash=_hash(hash_char),
            source_ref=source_ref,
            statement=statement,
        ),
        "input_hash": _hash("9"),
        "outcome": outcome,
        "predicted_primary_stable_key": primary,
        "predicted_related_stable_keys": [],
        "predicted_path": ["asset", primary] if primary else [],
        "score": score,
        "margin": margin,
        "scope_conflict": scope_conflict,
        "latency_ms": 100,
        "cost_usd": cost_usd,
        "write_disposition": "none",
    }
    if outcome in {"unresolved", "error"}:
        payload["predicted_primary_stable_key"] = None
        payload["predicted_path"] = []
        payload["score"] = None
        payload["margin"] = None
        payload["unresolved_kind"] = "abstained" if outcome == "unresolved" else None
        if outcome == "error":
            payload["error_code"] = "model_timeout"
    if outcome == "approved_mapping":
        payload["score"] = None
        payload["margin"] = None
    return TaxonomyPredictionRecord.model_validate(payload)


def _gold_set(dataset: TaxonomyDatasetManifest, records: list[TaxonomyGoldRecord]) -> TaxonomyGoldSet:
    return TaxonomyGoldSet(
        schema_version=1,
        corpus_id="cross-prd-pilot-v1",
        dataset_hash=dataset.dataset_hash,
        review_method="human_independent",
        reviewed_by="qa-lead",
        reviewed_at=NOW,
        records=records,
    )


def _requirement_units(
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
) -> RequirementUnitIndex:
    documents = {item.document_key: item for item in dataset.documents}
    result: RequirementUnitIndex = {item.document_key: {} for item in dataset.documents}
    for record in gold.records:
        document = documents[record.document_key]
        unit = _requirement_unit(document, record)
        result[record.document_key][unit.unit_id] = unit
    return result


def _requirement_unit(
    document: TaxonomyDatasetDocument,
    record: TaxonomyGoldRecord,
) -> RequirementUnit:
    source_ref = record.gold_evidence[0]
    statement = f"{record.document_key} 的固定需求 {record.record_id}"
    source_quote = f"固定原文 {record.record_id}"
    return RequirementUnit(
        unit_id=record.requirement_unit_id,
        system_id=document.system_id,
        document_id=document.document_id,
        document_content_hash=document.source.sha256,
        source_ref=source_ref,
        source_quote=source_quote,
        source_quote_hash=build_source_quote_hash(source_quote),
        structural_key=f"capability.{record.record_id}",
        title=f"需求 {record.record_id}",
        statement=statement,
        observable_outcome=f"结果 {record.record_id}",
        scope_status="atomic",
    )


def _frozen_policy(
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
    *,
    policy: TaxonomyResolutionPolicy | None = None,
) -> TaxonomyFrozenPolicy:
    resolved = policy or _policy()
    calibration_system_metrics = [
        TaxonomyCalibrationSystemMetrics(
            system_key=system_key,
            record_count=1,
            eligible_record_count=1,
            auto_decision_count=1,
            eligible_auto_decision_count=1,
            correct_auto_decision_count=1,
            precision=1,
            auto_coverage=1,
        )
        for system_key in sorted({item.system_key for item in dataset.documents})
    ]
    record_count = sum(item.eligible_record_count for item in calibration_system_metrics)
    return TaxonomyFrozenPolicy(
        schema_version=1,
        policy=resolved,
        policy_hash=resolved.canonical_hash,
        calibrated_at=NOW,
        calibration_split="dev",
        calibration_dataset_hash=dataset.dataset_hash,
        calibration_gold_hash=gold.canonical_hash,
        calibration_gold_review_method=gold.review_method,
        calibration_input_hash=_hash("8"),
        observed_precision=1,
        observed_auto_coverage=1,
        calibration_system_metrics=calibration_system_metrics,
        calibration_record_count=record_count,
        eligible_record_count=record_count,
        auto_decision_count=record_count,
        eligible_auto_decision_count=record_count,
        correct_auto_decision_count=record_count,
    )


def _predictions(
    dataset: TaxonomyDatasetManifest,
    records: list[TaxonomyPredictionRecord],
    *,
    policy_hash: str,
    frozen_policy_hash: str | None = None,
    proposed_nodes: list[TaxonomyProposedNode] | None = None,
    known_nodes: list[TaxonomyKnownNode] | None = None,
    output_manifest_hashes: dict[str, str] | None = None,
    output_manifest_artifacts: dict[str, ArtifactRef] | None = None,
    schema_version: int = 1,
    generated_at: datetime | None = None,
) -> TaxonomyPredictionSet:
    resolved_nodes = proposed_nodes or []
    resolved_known_nodes = known_nodes or []
    system_keys = {
        *(item.system_key for item in records),
        *(item.system_key for item in resolved_nodes),
        *(item.system_key for item in resolved_known_nodes),
    }
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "run_id": "pilot-run-001",
        "generated_at": generated_at or NOW + timedelta(minutes=1),
        "dataset_hash": dataset.dataset_hash,
        "policy_hash": policy_hash,
        "frozen_policy_hash": frozen_policy_hash,
        "prompt_revisions": {"resolver": "resolver@1"},
        "model_revisions": {"taxonomy_resolver": "verify@1"},
        "records": records,
        "proposed_nodes": resolved_nodes,
        "known_nodes": resolved_known_nodes,
        "output_manifest_hashes": output_manifest_hashes
        or {system_key: _hash("a") for system_key in sorted(system_keys)},
        "tree_diff": [],
    }
    if schema_version == 2 or output_manifest_artifacts is not None:
        payload["output_manifest_artifacts"] = output_manifest_artifacts or {}
    return TaxonomyPredictionSet.model_validate(payload)


def _gate(**overrides: object) -> TaxonomyEvaluationGate:
    values: dict[str, object] = {
        "minimum_semantic_stability": 0,
        "require_new_node_baseline": False,
        "require_operational_thresholds": False,
        "require_complete_corpus": False,
    }
    values.update(overrides)
    return TaxonomyEvaluationGate.model_validate(values)


def _output_manifest(
    *,
    system_id: UUID = SYSTEM_A,
    module_key: str = "asset",
    capability_key: str = "asset.filter",
    additional_capability_keys: tuple[str, ...] = (),
    include_capability_child: bool = False,
) -> TaxonomyManifest:
    nodes: list[dict[str, object]] = [
        {
            "stable_key": module_key,
            "node_type": "module",
            "display_name": "素材中心",
        },
        {
            "stable_key": capability_key,
            "node_type": "capability",
            "display_name": "筛选与排序",
            "parent_stable_key": module_key,
        },
    ]
    nodes.extend(
        {
            "stable_key": stable_key,
            "node_type": "capability",
            "display_name": stable_key,
            "parent_stable_key": module_key,
        }
        for stable_key in additional_capability_keys
    )
    if include_capability_child:
        nodes.append(
            {
                "stable_key": f"{capability_key}.child",
                "node_type": "module",
                "display_name": "错误子模块",
                "parent_stable_key": capability_key,
            }
        )
    return TaxonomyManifest.model_validate(
        {
            "schema_version": 1,
            "system_id": str(system_id),
            "version": 1,
            "change_note": "evaluation output",
            "created_by": "taxonomy-evaluator",
            "nodes": nodes,
            "mappings": [],
        }
    )


def _known_node_views(system_key: str, manifest: TaxonomyManifest) -> list[TaxonomyKnownNode]:
    return [
        TaxonomyKnownNode(
            system_key=system_key,
            stable_key=node.stable_key,
            node_type=node.node_type,
            parent_stable_key=node.parent_stable_key,
        )
        for node in manifest.nodes
    ]


def _write_manifest_artifact(tmp_path: Path, manifest: TaxonomyManifest) -> ArtifactRef:
    content = manifest.model_dump_json(indent=2)
    path = tmp_path / "output-manifest.json"
    path.write_text(content, encoding="utf-8")
    return ArtifactRef(path=path.name, sha256=hashlib.sha256(content.encode()).hexdigest())


def _extraction_result(
    *,
    document: TaxonomyDatasetDocument,
    input_hash: str,
    source_content: str,
    units: list[RequirementUnit],
) -> RequirementUnitExtractionResult:
    source_ref = units[0].source_ref if units else f"prd:{document.document_key} §fixture"
    content_hash = hashlib.sha256(source_content.encode()).hexdigest()
    return RequirementUnitExtractionResult(
        document_id=document.document_id,
        document_content_hash=document.source.sha256,
        input_hash=input_hash,
        prompt_revision="requirement-unit@1",
        model_revision="primary@1",
        chunk_count=1,
        units=units,
        coverage=[
            RequirementChunkCoverage(
                coverage_id=build_requirement_coverage_id(
                    document_content_hash=document.source.sha256,
                    source_ref=source_ref,
                    chunk_index=1,
                    content_hash=content_hash,
                ),
                source_ref=source_ref,
                heading="fixture",
                section_kind="spec",
                chunk_index=1,
                chunk_count=1,
                content_hash=content_hash,
                disposition="requirements_extracted" if units else "no_requirement",
                requirement_unit_ids=[item.unit_id for item in units],
                reason=None if units else "fixture_has_no_requirement",
            )
        ],
        issues=[],
    )


def test_dataset_rejects_same_document_content_across_dev_and_test() -> None:
    with pytest.raises(ValidationError, match="document_content_hash_leakage"):
        _dataset(duplicate_test_hash=True)


def test_prediction_contract_v2_requires_manifest_artifacts() -> None:
    dataset = _dataset()
    legacy = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=_policy().canonical_hash,
    )
    payload = legacy.model_dump(mode="json")
    payload["schema_version"] = 2

    with pytest.raises(ValidationError, match="prediction_output_manifest_artifacts_required"):
        TaxonomyPredictionSet.model_validate(payload)

    assert "output_manifest_artifacts" not in legacy.model_dump(mode="json")


def test_dataset_requires_dev_and_locked_test_for_each_pilot_system() -> None:
    dataset = _dataset()
    payload = dataset.model_dump(mode="json")
    payload["documents"] = [item for item in payload["documents"] if item["document_key"] != "dist-v2"]

    with pytest.raises(ValidationError, match="system_split_incomplete:distribution"):
        TaxonomyDatasetManifest.model_validate(payload)


def test_dataset_rejects_same_document_identity_across_splits() -> None:
    dataset = _dataset()
    payload = dataset.model_dump(mode="json")
    payload["documents"][1]["document_id"] = payload["documents"][0]["document_id"]

    with pytest.raises(ValidationError, match="duplicate_dataset_document_id"):
        TaxonomyDatasetManifest.model_validate(payload)


def test_dataset_rejects_same_system_id_hidden_behind_multiple_keys() -> None:
    dataset = _dataset()
    payload = dataset.model_dump(mode="json")
    for document in payload["documents"]:
        if document["system_key"] == "distribution":
            document["system_id"] = str(SYSTEM_A)

    with pytest.raises(ValidationError, match="system_id_alias_conflict"):
        TaxonomyDatasetManifest.model_validate(payload)


def test_dataset_hash_binds_freeze_timestamp() -> None:
    dataset = _dataset()
    payload = dataset.model_dump(mode="json")
    payload["created_at"] = (dataset.created_at + timedelta(minutes=1)).isoformat()

    shifted = TaxonomyDatasetManifest.model_validate(payload)

    assert shifted.dataset_hash != dataset.dataset_hash


def test_gold_cannot_reuse_same_requirement_unit_as_a_transformation_variant() -> None:
    dataset = _dataset()
    original = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        semantic_group_id="same-unit",
    )
    variant = _gold(
        "gold2",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        semantic_group_id="same-unit",
        variant_kind="chapter_reorder",
    ).model_copy(update={"requirement_unit_id": original.requirement_unit_id})

    with pytest.raises(ValidationError, match="duplicate_gold_requirement_unit"):
        _gold_set(dataset, [original, variant])


def test_gold_node_graph_rejects_cycles() -> None:
    dataset = _dataset()
    record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
    )

    with pytest.raises(ValidationError, match="gold_node_cycle"):
        TaxonomyGoldSet(
            schema_version=1,
            corpus_id=dataset.corpus_id,
            dataset_hash=dataset.dataset_hash,
            review_method="human_independent",
            reviewed_by="qa-lead",
            reviewed_at=NOW,
            records=[record],
            expected_nodes=[
                TaxonomyGoldNode(
                    gold_node_key="task-a",
                    system_key="drama",
                    node_type="module",
                    parent_gold_node_key="task-b",
                    preferred_stable_key="task.a",
                    evidence_requirement_unit_ids=[record.requirement_unit_id],
                ),
                TaxonomyGoldNode(
                    gold_node_key="task-b",
                    system_key="drama",
                    node_type="module",
                    parent_gold_node_key="task-a",
                    preferred_stable_key="task.b",
                    evidence_requirement_unit_ids=[record.requirement_unit_id],
                ),
            ],
        )


def test_approved_mapping_prediction_cannot_claim_draft_write() -> None:
    prediction = _prediction(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        outcome="approved_mapping",
    )
    payload = prediction.model_dump(mode="json")
    payload["write_disposition"] = "draft"

    with pytest.raises(ValidationError, match="approved_mapping_conflicting_payload"):
        TaxonomyPredictionRecord.model_validate(payload)


def test_proposal_prediction_cannot_claim_existing_taxonomy_path() -> None:
    record = _gold("gold1", document_key="drama-v2", system_key="drama", split="test")
    with pytest.raises(ValidationError, match="proposal_conflicting_payload"):
        TaxonomyPredictionRecord(
            record_id="gold1",
            document_key="drama-v2",
            system_key="drama",
            split="test",
            requirement_unit_id=record.requirement_unit_id,
            input_hash=_hash("9"),
            outcome="proposal",
            predicted_path=["task", "task.schedule"],
            predicted_operation="add",
            write_disposition="draft",
        )


def test_calibration_rejects_test_feedback() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=_policy().canonical_hash,
    )

    with pytest.raises(ValueError, match="test_data_for_calibration_forbidden"):
        calibrate_resolution_policy(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            base_policy=_policy(),
            calibrated_at=NOW,
            minimum_precision=0.95,
        )


def test_calibration_maximizes_dev_coverage_subject_to_precision_gate() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(f"gold{i}", document_key="drama-v1", system_key="drama", split="dev", primary=f"node.{i}")
            for i in range(1, 5)
        ]
        + [_gold("dist1", document_key="dist-v1", system_key="distribution", split="dev", primary="settlement.list")],
    )
    base_policy = _policy(minimum_score=0, minimum_margin=0)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1", document_key="drama-v1", system_key="drama", split="dev", primary="node.1", score=0.95
            ),
            _prediction(
                "gold2", document_key="drama-v1", system_key="drama", split="dev", primary="node.2", score=0.90
            ),
            _prediction("gold3", document_key="drama-v1", system_key="drama", split="dev", primary="wrong", score=0.85),
            _prediction(
                "gold4", document_key="drama-v1", system_key="drama", split="dev", primary="node.4", score=0.80
            ),
            _prediction(
                "dist1",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="settlement.list",
                score=0.96,
            ),
        ],
        policy_hash=base_policy.canonical_hash,
    )

    frozen = calibrate_resolution_policy(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        base_policy=base_policy,
        calibrated_at=NOW + timedelta(minutes=2),
        minimum_precision=0.95,
    )

    assert frozen.policy.minimum_score == 0.9
    assert frozen.observed_precision == 1
    assert frozen.observed_auto_coverage == 0.5
    assert frozen.calibration_split == "dev"
    assert frozen.calibration_record_count == 5
    assert frozen.auto_decision_count == 3
    assert frozen.eligible_auto_decision_count == 3
    assert {item.system_key for item in frozen.calibration_system_metrics} == {"drama", "distribution"}


def test_calibration_rejects_selective_prediction_coverage() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v1", system_key="drama", split="dev"),
            _gold(
                "gold2",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="settlement.list",
            ),
        ],
    )
    base_policy = _policy(minimum_score=0, minimum_margin=0)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v1", system_key="drama", split="dev")],
        policy_hash=base_policy.canonical_hash,
    )

    with pytest.raises(ValueError, match="calibration_prediction_coverage_missing"):
        calibrate_resolution_policy(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            base_policy=base_policy,
            calibrated_at=NOW + timedelta(minutes=2),
            minimum_precision=0.95,
        )


def test_post_prediction_calibration_gold_requires_explicit_reviewed_workflow_opt_in() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v1", system_key="drama", split="dev"),
            _gold("gold2", document_key="dist-v1", system_key="distribution", split="dev"),
        ],
    ).model_copy(update={"reviewed_at": NOW + timedelta(minutes=2)})
    base_policy = _policy(minimum_score=0, minimum_margin=0)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v1", system_key="drama", split="dev"),
            _prediction("gold2", document_key="dist-v1", system_key="distribution", split="dev"),
        ],
        policy_hash=base_policy.canonical_hash,
        generated_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="prediction_precedes_gold_freeze"):
        calibrate_resolution_policy(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            base_policy=base_policy,
            calibrated_at=NOW + timedelta(minutes=3),
            minimum_precision=0.95,
        )

    frozen = calibrate_resolution_policy(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        base_policy=base_policy,
        calibrated_at=NOW + timedelta(minutes=3),
        minimum_precision=0.95,
        allow_post_prediction_gold_review=True,
    )
    assert frozen.observed_precision == 1


def test_calibration_counts_ineligible_auto_decisions_as_false_positives() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("drama-eligible", document_key="drama-v1", system_key="drama", split="dev"),
            _gold(
                "drama-ineligible",
                document_key="drama-v1",
                system_key="drama",
                split="dev",
                eligible_for_auto=False,
            ),
            _gold(
                "dist-eligible",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="settlement.list",
            ),
        ],
    )
    base_policy = _policy(minimum_score=0, minimum_margin=0)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "drama-eligible",
                document_key="drama-v1",
                system_key="drama",
                split="dev",
                score=0.95,
            ),
            _prediction(
                "drama-ineligible",
                document_key="drama-v1",
                system_key="drama",
                split="dev",
                score=0.96,
            ),
            _prediction(
                "dist-eligible",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="settlement.list",
                score=0.98,
            ),
        ],
        policy_hash=base_policy.canonical_hash,
    )

    with pytest.raises(ValueError, match="no_calibrated_threshold_meets_precision_gate"):
        calibrate_resolution_policy(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            base_policy=base_policy,
            calibrated_at=NOW + timedelta(minutes=2),
            minimum_precision=0.95,
        )


def test_frozen_policy_hash_binds_calibration_review_metadata() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v1", system_key="drama", split="dev")],
    )
    frozen = _frozen_policy(dataset, gold)
    provisional = frozen.model_copy(update={"calibration_gold_review_method": "model_assisted_provisional"})

    assert frozen.canonical_hash != provisional.canonical_hash


def test_frozen_policy_rejects_metrics_that_disagree_with_counts() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v1", system_key="drama", split="dev")],
    )
    payload = _frozen_policy(dataset, gold).model_dump(mode="json")
    payload["calibration_system_metrics"][0]["precision"] = 0.5

    with pytest.raises(ValidationError, match="calibration_system_precision_mismatch"):
        TaxonomyFrozenPolicy.model_validate(payload)


def test_calibration_cannot_hide_one_system_failure_with_another_system() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v1", system_key="drama", split="dev"),
            _gold(
                "gold2",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="settlement.list",
            ),
        ],
    )
    base_policy = _policy(minimum_score=0, minimum_margin=0)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v1", system_key="drama", split="dev", score=0.9),
            _prediction(
                "gold2",
                document_key="dist-v1",
                system_key="distribution",
                split="dev",
                primary="wrong.node",
                score=0.95,
            ),
        ],
        policy_hash=base_policy.canonical_hash,
    )

    with pytest.raises(ValueError, match="no_calibrated_threshold_meets_precision_gate"):
        calibrate_resolution_policy(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            base_policy=base_policy,
            calibrated_at=NOW + timedelta(minutes=2),
            minimum_precision=0.95,
        )


def test_evaluation_reports_each_system_without_aggregate_masking() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v2", system_key="drama", split="test", primary="asset.filter"),
            _gold("gold2", document_key="dist-v2", system_key="distribution", split="test", primary="settlement.list"),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    output_manifests = {
        "drama": _output_manifest(),
        "distribution": _output_manifest(
            system_id=SYSTEM_B,
            capability_key="settlement.list",
            additional_capability_keys=("wrong.node",),
        ),
    }
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test", primary="asset.filter"),
            _prediction("gold2", document_key="dist-v2", system_key="distribution", split="test", primary="wrong.node"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        schema_version=2,
        known_nodes=[
            *_known_node_views("drama", output_manifests["drama"]),
            *_known_node_views("distribution", output_manifests["distribution"]),
        ],
        output_manifest_hashes={
            system_key: manifest_hash(output_manifest) for system_key, output_manifest in output_manifests.items()
        },
        output_manifest_artifacts={
            "drama": _artifact("manifests/drama.json", "a"),
            "distribution": _artifact("manifests/distribution.json", "b"),
        },
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        output_manifests=output_manifests,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(
            minimum_reuse_precision=0.95,
            minimum_structural_invariant_rate=1,
            require_complete_corpus=True,
        ),
    )

    by_system = {item.system_key: item for item in result.system_results}
    assert by_system["drama"].gate_status == "pass"
    assert by_system["distribution"].gate_status == "fail"
    assert result.overall_status == "fail"
    assert result.aggregate_metrics is None


def test_evaluation_keeps_unknown_gateway_cost_as_unknown() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                cost_usd=None,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(),
    )

    assert result.total_cost_usd is None
    assert "Cost: `unknown`" in render_taxonomy_evaluation_report(result)


def test_ineligible_requirement_cannot_be_counted_as_correct_auto_mapping() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                eligible_for_auto=False,
            )
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_reuse_precision=0.95),
    )

    metrics = result.system_results[0].metrics
    assert metrics.exact_primary_precision == 0
    assert metrics.auto_coverage == 0
    assert "reuse_precision_below_gate" in result.system_results[0].gate_findings
    assert result.overall_status == "fail"


def test_wrong_approved_mapping_fails_reuse_precision_gate() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                primary="wrong.node",
                outcome="approved_mapping",
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_reuse_precision=0.95),
    )

    metrics = result.system_results[0].metrics
    assert metrics.auto_mapped_count == 1
    assert metrics.exact_primary_precision == 0
    assert "reuse_precision_below_gate" in result.system_results[0].gate_findings
    assert result.overall_status == "fail"


def test_evaluation_rejects_prediction_from_another_dataset_revision() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    ).model_copy(update={"dataset_hash": _hash("f")})

    with pytest.raises(ValueError, match="prediction_dataset_mismatch"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(),
        )


def test_evaluation_rejects_frozen_calibration_metadata_changed_after_test_run() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )
    altered = frozen.model_copy(update={"calibration_gold_review_method": "model_assisted_provisional"})

    with pytest.raises(ValueError, match="prediction_frozen_policy_hash_mismatch"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=altered,
            gate=_gate(),
        )


def test_evaluation_rejects_prediction_record_rebound_to_another_document() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="dist-v2",
                system_key="distribution",
                split="test",
                primary="asset.filter",
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    with pytest.raises(ValueError, match="prediction_gold_metadata_mismatch:gold1"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(),
        )


def test_evaluation_rejects_prediction_rebound_to_another_unit_in_same_document() -> None:
    dataset = _dataset()
    gold1 = _gold("gold1", document_key="drama-v2", system_key="drama", split="test")
    gold2 = _gold("gold2", document_key="drama-v2", system_key="drama", split="test")
    gold = _gold_set(dataset, [gold1, gold2])
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                requirement_unit_id=gold2.requirement_unit_id,
            ),
            _prediction("gold2", document_key="drama-v2", system_key="drama", split="test"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    with pytest.raises(ValueError, match="prediction_gold_metadata_mismatch:gold1"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(),
        )


def test_evaluation_cannot_precede_locked_test_predictions() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    with pytest.raises(ValueError, match="evaluation_precedes_predictions"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(),
            evaluated_at=predictions.generated_at - timedelta(seconds=1),
        )


def test_release_gate_is_incomplete_until_operational_thresholds_are_approved() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=TaxonomyEvaluationGate(
            minimum_semantic_stability=0,
            require_new_node_baseline=False,
            require_complete_corpus=False,
        ),
    )

    assert result.overall_status == "incomplete"
    assert "reuse_coverage_threshold_missing" in result.system_results[0].gate_findings
    assert "human_intervention_threshold_missing" in result.system_results[0].gate_findings


def test_release_gate_requires_reuse_examples_when_reuse_baseline_is_enabled() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="new_node",
            )
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_reuse_baseline=True, require_new_node_baseline=True),
    )

    assert result.overall_status != "pass"
    assert "reuse_baseline_missing" in result.system_results[0].gate_findings


def test_release_gate_requires_every_locked_test_document() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    with pytest.raises(ValueError, match="gold_document_coverage_missing:dist-v2"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(require_complete_corpus=True),
        )


def test_release_gate_requires_every_requirement_unit_in_locked_documents() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _gold("gold2", document_key="dist-v2", system_key="distribution", split="test"),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _prediction("gold2", document_key="dist-v2", system_key="distribution", split="test"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )
    requirement_units = _requirement_units(dataset, gold)
    omitted_gold = _gold(
        "omitted",
        document_key="drama-v2",
        system_key="drama",
        split="test",
    )
    omitted_unit = _requirement_unit(
        next(item for item in dataset.documents if item.document_key == "drama-v2"),
        omitted_gold,
    )
    requirement_units["drama-v2"][omitted_unit.unit_id] = omitted_unit

    with pytest.raises(ValueError, match="gold_requirement_unit_coverage_missing:drama-v2:count=1"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=requirement_units,
            frozen_policy=frozen,
            gate=_gate(require_complete_corpus=True),
        )


def test_semantic_stability_detects_rewrite_drift_even_when_both_are_confident() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                primary="asset.filter",
                semantic_group_id="filter-semantic",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                primary="asset.filter",
                semantic_group_id="filter-semantic",
                variant_kind="title_rewrite",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test", primary="asset.filter"),
            _prediction("gold2", document_key="drama-v2", system_key="drama", split="test", primary="asset.sort"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_semantic_stability=0.95),
    )

    metric = result.system_results[0].metrics
    assert metric.semantic_stability_rate == 0
    assert metric.stability_by_variant["title_rewrite"] == 0


def test_semantic_stability_ignores_acceptance_mechanism_for_same_target() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="same-target",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="same-target",
                variant_kind="synonym",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _prediction(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="approved_mapping",
            ),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_semantic_stability=0.95),
    )

    assert result.system_results[0].metrics.semantic_stability_rate == 1


def test_semantic_group_rejects_inconsistent_gold_expectations() -> None:
    dataset = _dataset()

    with pytest.raises(ValidationError, match="semantic_group_gold_mismatch:rewrite-group"):
        _gold_set(
            dataset,
            [
                _gold(
                    "gold1",
                    document_key="drama-v2",
                    system_key="drama",
                    split="test",
                    primary="asset.filter",
                    semantic_group_id="rewrite-group",
                ),
                _gold(
                    "gold2",
                    document_key="drama-v2",
                    system_key="drama",
                    split="test",
                    primary="asset.sort",
                    semantic_group_id="rewrite-group",
                    variant_kind="title_rewrite",
                ),
            ],
        )


def test_semantic_stability_does_not_count_matching_errors_as_success() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="error-group",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="error-group",
                variant_kind="synonym",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test", outcome="error"),
            _prediction("gold2", document_key="drama-v2", system_key="drama", split="test", outcome="error"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_semantic_stability=0.95),
    )

    assert result.system_results[0].metrics.semantic_stability_rate == 0


def test_semantic_stability_compares_proposed_node_shape_not_only_operation() -> None:
    dataset = _dataset()
    original = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
        semantic_group_id="proposal-group",
    )
    variant = _gold(
        "gold2",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
        semantic_group_id="proposal-group",
        variant_kind="title_rewrite",
    )
    gold = _gold_set(dataset, [original, variant])
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            TaxonomyPredictionRecord(
                record_id=original.record_id,
                document_key=original.document_key,
                system_key=original.system_key,
                split=original.split,
                requirement_unit_id=original.requirement_unit_id,
                input_hash=_hash("9"),
                outcome="proposal",
                predicted_operation="add",
                write_disposition="draft",
            ),
            TaxonomyPredictionRecord(
                record_id=variant.record_id,
                document_key=variant.document_key,
                system_key=variant.system_key,
                split=variant.split,
                requirement_unit_id=variant.requirement_unit_id,
                input_hash=_hash("a"),
                outcome="proposal",
                predicted_operation="add",
                write_disposition="draft",
            ),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="module",
                display_name="定时提交",
                evidence_requirement_unit_ids=[original.requirement_unit_id],
            ),
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.scheduled-submit",
                node_type="module",
                display_name="预约提交",
                evidence_requirement_unit_ids=[variant.requirement_unit_id],
            ),
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_semantic_stability=0.95, require_new_node_baseline=True),
    )

    assert result.system_results[0].metrics.semantic_stability_rate == 0
    assert "semantic_stability_below_gate" in result.system_results[0].gate_findings


def test_transformation_artifact_must_exactly_cover_non_original_gold() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="rewrite-group",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                semantic_group_id="rewrite-group",
                variant_kind="title_rewrite",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _prediction("gold2", document_key="drama-v2", system_key="drama", split="test"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )
    empty = TaxonomyTransformationSet(
        schema_version=1,
        corpus_id=dataset.corpus_id,
        records=[],
    )

    with pytest.raises(ValueError, match="transformation_gold_coverage_mismatch"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            transformations=empty,
            frozen_policy=frozen,
            gate=_gate(minimum_semantic_stability=0.95),
        )

    units = _requirement_units(dataset, gold)
    source_unit = units[gold.records[0].document_key][gold.records[0].requirement_unit_id]
    variant_unit = units[gold.records[1].document_key][gold.records[1].requirement_unit_id]
    transformations = TaxonomyTransformationSet(
        schema_version=1,
        corpus_id=dataset.corpus_id,
        records=[
            TaxonomyTransformationRecord(
                transformation_id="rewrite-1",
                system_key="drama",
                split="test",
                semantic_group_id="rewrite-group",
                source_record_id="gold1",
                variant_record_id="gold2",
                kind="title_rewrite",
                transformation_revision="manual-fixture@1",
                source_text_hash=hashlib.sha256(source_unit.statement.encode()).hexdigest(),
                variant_text_hash=hashlib.sha256(variant_unit.statement.encode()).hexdigest(),
            )
        ],
    )
    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=units,
        transformations=transformations,
        frozen_policy=frozen,
        gate=_gate(minimum_semantic_stability=0.95),
    )
    assert result.system_results[0].metrics.semantic_stability_rate == 1


def test_duplicate_and_unsupported_proposed_nodes_are_measured_from_gold_evidence() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="new_node",
                primary="task.schedule",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="reuse",
                primary="asset.filter",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    nodes = [
        TaxonomyProposedNode(
            system_key="drama",
            stable_key="task.schedule",
            node_type="module",
            display_name="定时提交",
            evidence_requirement_unit_ids=[gold.records[0].requirement_unit_id],
        ),
        TaxonomyProposedNode(
            system_key="drama",
            stable_key="task.scheduled_submit",
            node_type="module",
            display_name="预约提交",
            evidence_requirement_unit_ids=[gold.records[0].requirement_unit_id],
        ),
        TaxonomyProposedNode(
            system_key="drama",
            stable_key="asset.single_create",
            node_type="module",
            display_name="单个新建商品",
            evidence_requirement_unit_ids=[gold.records[1].requirement_unit_id],
        ),
    ]
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
                primary=None,
            ),
            _prediction("gold2", document_key="drama-v2", system_key="drama", split="test", primary="asset.filter"),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=nodes,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_new_node_baseline=True),
    )

    metric = result.system_results[0].metrics
    assert metric.duplicate_node_rate == pytest.approx(1 / 3)
    assert metric.unsupported_node_rate == pytest.approx(1 / 3)
    assert metric.new_node_precision == pytest.approx(1 / 3)
    assert result.system_results[0].gate_status == "fail"


def test_node_level_gold_does_not_penalize_supported_bootstrap_parent_nodes() -> None:
    dataset = _dataset()
    record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
    )
    gold = TaxonomyGoldSet(
        schema_version=1,
        corpus_id="cross-prd-pilot-v1",
        dataset_hash=dataset.dataset_hash,
        review_method="human_independent",
        reviewed_by="qa-lead",
        reviewed_at=NOW,
        records=[record],
        expected_nodes=[
            TaxonomyGoldNode(
                gold_node_key="task-parent",
                system_key="drama",
                node_type="module",
                preferred_stable_key="task",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
            TaxonomyGoldNode(
                gold_node_key="task-schedule",
                system_key="drama",
                node_type="capability",
                parent_gold_node_key="task-parent",
                preferred_stable_key="task.schedule",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
                primary=None,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task",
                node_type="module",
                display_name="任务",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="capability",
                display_name="定时提交",
                parent_stable_key="task",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_new_node_baseline=True),
    )

    metrics = result.system_results[0].metrics
    assert metrics.new_node_precision == 1
    assert metrics.new_node_recall == 1
    assert metrics.unsupported_node_rate == 0


def test_explicit_node_gold_does_not_fall_back_to_record_gold_on_wrong_type() -> None:
    dataset = _dataset()
    record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
    )
    gold = TaxonomyGoldSet(
        schema_version=1,
        corpus_id=dataset.corpus_id,
        dataset_hash=dataset.dataset_hash,
        review_method="human_independent",
        reviewed_by="qa-lead",
        reviewed_at=NOW,
        records=[record],
        expected_nodes=[
            TaxonomyGoldNode(
                gold_node_key="task-schedule",
                system_key="drama",
                node_type="capability",
                preferred_stable_key="task.schedule",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            )
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
                primary=None,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="module",
                display_name="定时提交",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            )
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_new_node_baseline=True),
    )

    metrics = result.system_results[0].metrics
    assert metrics.new_node_precision == 0
    assert metrics.new_node_recall == 0
    assert metrics.unsupported_node_rate == 1


def test_explicit_node_gold_requires_the_expected_parent_boundary() -> None:
    dataset = _dataset()
    record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
    )
    gold = TaxonomyGoldSet(
        schema_version=1,
        corpus_id=dataset.corpus_id,
        dataset_hash=dataset.dataset_hash,
        review_method="human_independent",
        reviewed_by="qa-lead",
        reviewed_at=NOW,
        records=[record],
        expected_nodes=[
            TaxonomyGoldNode(
                gold_node_key="task-parent",
                system_key="drama",
                node_type="module",
                preferred_stable_key="task",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
            TaxonomyGoldNode(
                gold_node_key="task-schedule",
                system_key="drama",
                node_type="capability",
                parent_gold_node_key="task-parent",
                preferred_stable_key="task.schedule",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
                primary=None,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task",
                node_type="module",
                display_name="任务",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="capability",
                display_name="定时提交",
                parent_stable_key=None,
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            ),
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_new_node_baseline=True),
    )

    metrics = result.system_results[0].metrics
    assert metrics.new_node_precision == 0.5
    assert metrics.new_node_recall == 0.5


def test_new_node_precision_cannot_hide_missing_expected_nodes() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="new_node",
                primary="task.schedule",
            ),
            _gold(
                "gold2",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="new_node",
                primary="task.cancel",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction(
                record.record_id,
                document_key=record.document_key,
                system_key=record.system_key,
                split=record.split,
                outcome="unresolved",
                primary=None,
            )
            for record in gold.records
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="module",
                display_name="定时提交",
                evidence_requirement_unit_ids=[gold.records[0].requirement_unit_id],
            )
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(
            require_new_node_baseline=True,
            require_operational_thresholds=True,
            minimum_new_node_precision=1,
            minimum_new_node_recall=1,
            maximum_human_intervention_rate=1,
        ),
    )

    metrics = result.system_results[0].metrics
    assert metrics.new_node_precision == 1
    assert metrics.new_node_recall == 0.5
    assert "new_node_recall_below_gate" in result.system_results[0].gate_findings
    assert result.overall_status == "fail"


def test_correct_new_node_with_wrong_change_operation_fails_gate() -> None:
    dataset = _dataset()
    record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        expected="new_node",
        primary="task.schedule",
    )
    gold = _gold_set(dataset, [record])
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            TaxonomyPredictionRecord(
                record_id=record.record_id,
                document_key=record.document_key,
                system_key=record.system_key,
                split=record.split,
                requirement_unit_id=record.requirement_unit_id,
                input_hash=_hash("9"),
                outcome="proposal",
                predicted_operation="split",
                write_disposition="draft",
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="module",
                display_name="定时提交",
                evidence_requirement_unit_ids=[record.requirement_unit_id],
            )
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(
            require_new_node_baseline=True,
            require_operational_thresholds=True,
            minimum_new_node_precision=1,
            minimum_new_node_recall=1,
            minimum_proposal_operation_type_accuracy=1,
            maximum_human_intervention_rate=1,
        ),
    )

    metrics = result.system_results[0].metrics
    assert metrics.new_node_precision == 1
    assert metrics.new_node_recall == 1
    assert metrics.proposal_operation_type_accuracy == 0
    assert metrics.abstention_precision is None
    assert metrics.abstention_recall is None
    assert "proposal_operation_type_accuracy_below_gate" in result.system_results[0].gate_findings
    assert result.overall_status == "fail"


def test_proposed_tree_cycle_fails_structural_invariant_gate() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                expected="new_node",
                primary="task.schedule",
            )
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    unit_id = gold.records[0].requirement_unit_id
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                outcome="unresolved",
                primary=None,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        proposed_nodes=[
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task",
                node_type="module",
                display_name="任务",
                parent_stable_key="task.schedule",
                evidence_requirement_unit_ids=[unit_id],
            ),
            TaxonomyProposedNode(
                system_key="drama",
                stable_key="task.schedule",
                node_type="module",
                display_name="定时提交",
                parent_stable_key="task",
                evidence_requirement_unit_ids=[unit_id],
            ),
        ],
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(require_new_node_baseline=True),
    )

    metric = result.system_results[0].metrics
    assert metric.structural_invariant_rate < 1
    assert "parent_cycle" in metric.structural_violations


def test_test_predictions_must_be_created_after_policy_freeze() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold).model_copy(update={"calibrated_at": NOW + timedelta(minutes=1)})
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        generated_at=NOW + timedelta(seconds=30),
    )

    with pytest.raises(ValueError, match="test_run_precedes_policy_freeze"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(),
        )


def test_model_assisted_provisional_gold_cannot_pass_release_gate() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    provisional_gold = gold.model_copy(update={"review_method": "model_assisted_provisional"})
    frozen = _frozen_policy(dataset, provisional_gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=provisional_gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, provisional_gold),
        frozen_policy=frozen,
        gate=_gate(),
    )

    assert result.overall_status == "incomplete"
    assert result.system_results[0].gate_status == "incomplete"
    assert "independent_test_gold_missing" in result.system_results[0].gate_findings


def _draft_manifest() -> TaxonomyManifest:
    return TaxonomyManifest.model_validate(
        {
            "schema_version": 2,
            "system_id": str(SYSTEM_A),
            "version": 1,
            "change_note": "bootstrap draft",
            "created_by": "taxonomy-builder",
            "nodes": [
                {
                    "stable_key": "asset",
                    "node_type": "module",
                    "display_name": "素材中心",
                    "definition": "管理素材。",
                    "scope_note": "包含素材管理。",
                },
                {
                    "stable_key": "asset.filter",
                    "node_type": "capability",
                    "display_name": "筛选与排序",
                    "parent_stable_key": "asset",
                    "definition": "筛选素材。",
                    "scope_note": "包含筛选，不包含上传。",
                    "in_scope_examples": [
                        {
                            "text": "素材列表支持筛选。",
                            "document_content_hash": _hash("a"),
                            "requirement_unit_id": f"ru_{'b' * 64}",
                        }
                    ],
                    "out_of_scope_examples": [
                        {
                            "text": "上传素材不属于筛选。",
                            "document_content_hash": _hash("a"),
                            "requirement_unit_id": f"ru_{'c' * 64}",
                        }
                    ],
                },
            ],
            "mappings": [],
        }
    )


def test_calibration_package_is_focused_and_review_is_independent() -> None:
    manifest = _draft_manifest()
    distribution_manifest = _output_manifest(
        system_id=SYSTEM_B,
        capability_key="settlement.list",
    )
    output_manifests = {
        "drama": manifest,
        "distribution": distribution_manifest,
    }
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [
            _gold("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _gold(
                "gold2",
                document_key="dist-v2",
                system_key="distribution",
                split="test",
                primary="settlement.list",
            ),
        ],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [
            _prediction("gold1", document_key="drama-v2", system_key="drama", split="test"),
            _prediction(
                "gold2",
                document_key="dist-v2",
                system_key="distribution",
                split="test",
                primary="settlement.list",
            ),
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        schema_version=2,
        known_nodes=[
            *_known_node_views("drama", manifest),
            *_known_node_views("distribution", distribution_manifest),
        ],
        output_manifest_hashes={
            "drama": manifest_hash(manifest),
            "distribution": manifest_hash(distribution_manifest),
        },
        output_manifest_artifacts={
            "drama": _artifact("manifests/drama.json", "a"),
            "distribution": _artifact("manifests/distribution.json", "b"),
        },
    )
    evaluation = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        output_manifests=output_manifests,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(
            require_complete_corpus=True,
            require_operational_thresholds=True,
            minimum_expected_reuse_coverage=1,
            maximum_human_intervention_rate=0,
        ),
        evaluated_at=NOW + timedelta(minutes=2),
    )
    assert evaluation.overall_status == "pass"

    package = build_calibration_package(
        draft_manifest=manifest,
        dataset=dataset,
        evaluation_result=evaluation,
        system_key="drama",
        exceptions=["1 条 novel 待后续 evolve"],
        samples=[{"record_id": "gold1"}],
        prepared_by="taxonomy-builder",
        prepared_at=NOW + timedelta(minutes=3),
        max_samples=5,
    )

    assert package.review_scope == "top_level_boundary_exception_sample"
    assert [item.stable_key for item in package.top_level_nodes] == ["asset"]
    assert [item.stable_key for item in package.critical_boundaries] == ["asset.filter"]
    assert len(package.samples) == 1
    assert package.total_node_count == 2
    assert "mappings" not in package.model_dump(mode="json")

    different_manifest = manifest.model_copy(update={"change_note": "unreviewed replacement draft"})
    with pytest.raises(ValueError, match="calibration_package_manifest_not_evaluated"):
        build_calibration_package(
            draft_manifest=different_manifest,
            dataset=dataset,
            evaluation_result=evaluation,
            system_key="drama",
            exceptions=[],
            samples=[{"record_id": "gold1"}],
            prepared_by="taxonomy-builder",
            prepared_at=NOW + timedelta(minutes=3),
        )

    review = TaxonomyCalibrationReview(
        schema_version=1,
        review_id="review-001",
        package_hash=package.canonical_hash,
        draft_manifest_hash=manifest_hash(manifest),
        evaluation_run_hash=package.evaluation_run_hash,
        decision="approved",
        reviewer="taxonomy-reviewer",
        reviewed_at=NOW + timedelta(minutes=5),
        findings=["顶层与关键边界符合需求。"],
        rollback_plan="恢复上一 active version 并关闭通用 taxonomy flag。",
    )

    authorization = validate_calibration_review(
        draft_manifest=manifest,
        package=package,
        review=review,
        activation_actor="taxonomy-reviewer",
    )
    assert authorization.activation_allowed is True
    assert authorization.review_hash == review.canonical_hash

    with pytest.raises(ValueError, match="calibration_review_self_approval_forbidden"):
        validate_calibration_review(
            draft_manifest=manifest,
            package=package,
            review=review.model_copy(update={"reviewer": "taxonomy-builder"}),
            activation_actor="taxonomy-builder",
        )

    with pytest.raises(ValueError, match="calibration_review_after_activation"):
        validate_calibration_review(
            draft_manifest=manifest,
            package=package,
            review=review,
            activation_actor="taxonomy-reviewer",
            activation_at=review.reviewed_at - timedelta(seconds=1),
        )


def test_report_is_explicitly_pilot_and_artifacts_are_machine_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )
    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(),
    )

    report = render_taxonomy_evaluation_report(result)
    assert "pilot corpus" in report
    assert "不能证明所有行业" in report
    assert "不提供跨系统聚合分" in report
    assert result.gate_hash in report

    output_dir = tmp_path / "evaluation"
    write_taxonomy_evaluation_artifacts(
        output_dir=output_dir,
        result=result,
        predictions=predictions,
    )
    assert {path.name for path in output_dir.iterdir()} == {
        "REPORT.md",
        "abstentions.json",
        "cost-latency.json",
        "errors.json",
        "metrics.json",
        "predictions.json",
        "systems",
        "tree-diff.json",
    }

    sentinel = output_dir / "REPORT.md"
    original_report = sentinel.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_taxonomy_evaluation_artifacts(
            output_dir=output_dir,
            result=result,
            predictions=predictions,
        )
    assert sentinel.read_text(encoding="utf-8") == original_report

    original_write_json = taxonomy_evaluation_service._write_json
    write_count = 0

    def fail_during_write(path: Path, value: object) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise RuntimeError("simulated_partial_write")
        original_write_json(path, value)

    monkeypatch.setattr(taxonomy_evaluation_service, "_write_json", fail_during_write)
    partial_output = tmp_path / "partial-evaluation"
    with pytest.raises(RuntimeError, match="simulated_partial_write"):
        write_taxonomy_evaluation_artifacts(
            output_dir=partial_output,
            result=result,
            predictions=predictions,
        )
    assert not partial_output.exists()


def test_frozen_policy_writer_never_overwrites_existing_run(tmp_path: Path) -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    output_dir = tmp_path / "calibration"

    _write_frozen_policy(output_dir, frozen)
    policy_path = output_dir / "frozen-policy.json"
    original = policy_path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        _write_frozen_policy(output_dir, frozen.model_copy(update={"observed_precision": 0.5}))

    assert policy_path.read_text(encoding="utf-8") == original


def test_artifact_hash_validation_detects_source_snapshot_drift(tmp_path: Path) -> None:
    source = tmp_path / "prd.md"
    source.write_text("真实内容", encoding="utf-8")
    document = _document("drama-v1", system_key="drama", system_id=SYSTEM_A, split="dev", hash_char="1")
    document = document.model_copy(update={"source": ArtifactRef(path=source.name, sha256=_hash("0"))})
    dataset = _dataset().model_copy(
        update={
            "documents": [document, *_dataset().documents[1:]],
        }
    )

    with pytest.raises(ValueError, match="artifact_hash_mismatch:drama-v1:source"):
        validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=tmp_path / "dataset.json")


def test_dev_requirement_unit_loader_does_not_open_locked_test_artifacts(tmp_path: Path) -> None:
    dataset = _dataset()
    documents: list[TaxonomyDatasetDocument] = []
    for index, document in enumerate(dataset.documents, start=1):
        if document.split == "test":
            documents.append(document)
            continue
        source_content = f"固定原文 dev-{index}\n"
        source_path = tmp_path / f"source-dev-{index}.md"
        source_path.write_text(source_content, encoding="utf-8")
        source_hash = hashlib.sha256(source_content.encode()).hexdigest()
        record = _gold(
            f"dev-{index}",
            document_key=document.document_key,
            system_key=document.system_key,
            split="dev",
            document_content_hash=source_hash,
        )
        unit = _requirement_unit(
            document.model_copy(update={"source": ArtifactRef(path=source_path.name, sha256=source_hash)}), record
        )
        resolved_document = document.model_copy(
            update={"source": ArtifactRef(path=source_path.name, sha256=source_hash)}
        )
        extraction = _extraction_result(
            document=resolved_document,
            input_hash=_hash(str(index)),
            source_content=source_content,
            units=[
                unit.model_copy(
                    update={
                        "source_quote": source_content.strip(),
                        "source_quote_hash": build_source_quote_hash(source_content.strip()),
                    }
                )
            ],
        )
        unit_path = tmp_path / f"units-dev-{index}.json"
        unit_path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
        documents.append(
            document.model_copy(
                update={
                    "source": ArtifactRef(path=source_path.name, sha256=source_hash),
                    "requirement_units": ArtifactRef(
                        path=unit_path.name,
                        sha256=hashlib.sha256(unit_path.read_bytes()).hexdigest(),
                    ),
                }
            )
        )
    filtered_dataset = dataset.model_copy(update={"documents": documents})

    loaded = load_requirement_unit_index(
        dataset=filtered_dataset,
        manifest_path=tmp_path / "dataset.json",
        document_splits={"dev"},
    )

    assert set(loaded) == {"drama-v1", "dist-v1"}


def test_evaluation_artifact_paths_cannot_escape_dataset_directory(tmp_path: Path) -> None:
    manifest_path = tmp_path / "dataset.json"

    with pytest.raises(ValueError, match="artifact_path_absolute_forbidden"):
        resolve_evaluation_artifact_path(manifest_path, str(tmp_path / "gold.json"))
    with pytest.raises(ValueError, match="artifact_path_escape"):
        resolve_evaluation_artifact_path(manifest_path, "../gold.json")

    assert resolve_evaluation_artifact_path(manifest_path, "artifacts/gold.json") == (
        tmp_path / "artifacts" / "gold.json"
    )


@pytest.mark.parametrize(
    ("mismatch", "error_code"),
    [
        ("artifact_hash", "prediction_output_manifest_artifact_hash_mismatch:drama"),
        ("manifest_hash", "prediction_output_manifest_hash_mismatch:drama"),
        ("system_identity", "prediction_output_manifest_system_id_mismatch:drama"),
    ],
)
def test_prediction_manifest_loader_verifies_artifact_and_system_identity(
    tmp_path: Path,
    mismatch: str,
    error_code: str,
) -> None:
    dataset = _dataset()
    manifest = _output_manifest(system_id=SYSTEM_B if mismatch == "system_identity" else SYSTEM_A)
    artifact = _write_manifest_artifact(tmp_path, manifest)
    if mismatch == "artifact_hash":
        artifact = artifact.model_copy(update={"sha256": _hash("f")})
    declared_manifest_hash = _hash("e") if mismatch == "manifest_hash" else manifest_hash(manifest)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=_policy().canonical_hash,
        schema_version=2,
        known_nodes=_known_node_views("drama", manifest),
        output_manifest_hashes={"drama": declared_manifest_hash},
        output_manifest_artifacts={"drama": artifact},
    )

    with pytest.raises(ValueError, match=error_code):
        taxonomy_evaluation_service.load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=tmp_path / "dataset.json",
            predictions=predictions,
        )


@pytest.mark.parametrize("view_change", ["missing", "extra"])
def test_prediction_manifest_loader_rejects_incomplete_or_extra_node_view(
    tmp_path: Path,
    view_change: str,
) -> None:
    dataset = _dataset()
    manifest = _output_manifest(include_capability_child=True)
    artifact = _write_manifest_artifact(tmp_path, manifest)
    known_nodes = _known_node_views("drama", manifest)
    if view_change == "missing":
        known_nodes = known_nodes[:-1]
    else:
        known_nodes.append(
            TaxonomyKnownNode(
                system_key="drama",
                stable_key="rogue",
                node_type="domain",
            )
        )
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=_policy().canonical_hash,
        schema_version=2,
        known_nodes=known_nodes,
        output_manifest_hashes={"drama": manifest_hash(manifest)},
        output_manifest_artifacts={"drama": artifact},
    )

    with pytest.raises(ValueError, match=f"prediction_manifest_node_view_mismatch:drama:{view_change}="):
        taxonomy_evaluation_service.load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=tmp_path / "dataset.json",
            predictions=predictions,
        )


def test_prediction_manifest_loader_rejects_sanitized_proposed_node_evidence(tmp_path: Path) -> None:
    dataset = _dataset()
    manifest_evidence_id = f"ru_{'1' * 64}"
    sanitized_evidence_id = f"ru_{'2' * 64}"
    evidence = {
        "text": "固定需求证据",
        "document_content_hash": dataset.documents[1].source.sha256,
        "requirement_unit_id": manifest_evidence_id,
    }
    manifest = TaxonomyManifest.model_validate(
        {
            "schema_version": 2,
            "system_id": str(SYSTEM_A),
            "version": 1,
            "change_note": "evidence binding fixture",
            "created_by": "taxonomy-evaluator",
            "nodes": [
                {
                    "stable_key": "asset",
                    "node_type": "module",
                    "display_name": "素材中心",
                    "definition": "管理素材能力。",
                    "scope_note": "只包含素材相关职责。",
                    "in_scope_examples": [evidence],
                },
                {
                    "stable_key": "asset.filter",
                    "node_type": "capability",
                    "display_name": "筛选与排序",
                    "parent_stable_key": "asset",
                    "definition": "筛选和排序素材。",
                    "scope_note": "不包含商品筛选。",
                    "in_scope_examples": [evidence],
                },
            ],
            "mappings": [],
        }
    )
    artifact = _write_manifest_artifact(tmp_path, manifest)
    proposed_nodes = [
        TaxonomyProposedNode(
            system_key="drama",
            stable_key=node.stable_key,
            node_type=node.node_type,
            display_name=node.display_name,
            parent_stable_key=node.parent_stable_key,
            aliases=node.aliases,
            evidence_requirement_unit_ids=[
                sanitized_evidence_id if node.stable_key == "asset.filter" else manifest_evidence_id
            ],
        )
        for node in manifest.nodes
    ]
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=_policy().canonical_hash,
        schema_version=2,
        proposed_nodes=proposed_nodes,
        output_manifest_hashes={"drama": manifest_hash(manifest)},
        output_manifest_artifacts={"drama": artifact},
    )

    with pytest.raises(
        ValueError,
        match="prediction_manifest_proposed_node_evidence_mismatch:drama:asset.filter",
    ):
        taxonomy_evaluation_service.load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=tmp_path / "dataset.json",
            predictions=predictions,
        )


def test_structural_gate_uses_complete_verified_manifest(tmp_path: Path) -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    manifest = _output_manifest(include_capability_child=True)
    artifact = _write_manifest_artifact(tmp_path, manifest)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        schema_version=2,
        known_nodes=_known_node_views("drama", manifest),
        output_manifest_hashes={"drama": manifest_hash(manifest)},
        output_manifest_artifacts={"drama": artifact},
    )

    with pytest.raises(ValueError, match="prediction_output_manifests_not_verified"):
        evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            requirement_units=_requirement_units(dataset, gold),
            frozen_policy=frozen,
            gate=_gate(minimum_structural_invariant_rate=1),
        )

    output_manifests = taxonomy_evaluation_service.load_prediction_output_manifests(
        dataset=dataset,
        dataset_path=tmp_path / "dataset.json",
        predictions=predictions,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        output_manifests=output_manifests,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(minimum_structural_invariant_rate=1),
    )

    assert result.overall_status == "fail"
    assert "capability_has_child" in result.system_results[0].metrics.structural_violations


def test_legacy_prediction_contract_cannot_pass_activation_gate() -> None:
    dataset = _dataset()
    gold = _gold_set(
        dataset,
        [_gold("gold1", document_key="drama-v2", system_key="drama", split="test")],
    )
    frozen = _frozen_policy(dataset, gold)
    predictions = _predictions(
        dataset,
        [_prediction("gold1", document_key="drama-v2", system_key="drama", split="test")],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
    )

    result = evaluate_taxonomy_generalization(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=_requirement_units(dataset, gold),
        frozen_policy=frozen,
        gate=_gate(),
    )

    assert result.overall_status == "incomplete"
    assert "prediction_contract_v2_required" in result.system_results[0].gate_findings


def test_cli_dry_run_reads_frozen_artifacts_and_writes_report_bundle(tmp_path: Path) -> None:
    def write_artifact(name: str, content: str) -> ArtifactRef:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return ArtifactRef(path=name, sha256=hashlib.sha256(content.encode()).hexdigest())

    source_documents: list[TaxonomyDatasetDocument] = []
    for index, source in enumerate(_dataset().documents, start=1):
        source_content = f"# 固定 PRD {index}\n"
        if source.document_key == "drama-v2":
            source_content += "固定原文 gold1\n"
        source_ref = write_artifact(f"source-{index}.md", source_content)
        source_documents.append(source.model_copy(update={"source": source_ref}))

    drama_document = next(item for item in source_documents if item.document_key == "drama-v2")
    gold_record = _gold(
        "gold1",
        document_key="drama-v2",
        system_key="drama",
        split="test",
        document_content_hash=drama_document.source.sha256,
    )
    unit = _requirement_unit(drama_document, gold_record)
    documents: list[TaxonomyDatasetDocument] = []
    for index, document in enumerate(source_documents, start=1):
        units = [unit] if document.document_key == "drama-v2" else []
        extraction = _extraction_result(
            document=document,
            input_hash=_hash(str(index)),
            source_content=(tmp_path / document.source.path).read_text(encoding="utf-8"),
            units=units,
        )
        units_ref = write_artifact(f"units-{index}.json", extraction.model_dump_json(indent=2))
        documents.append(document.model_copy(update={"requirement_units": units_ref}))
    transformations = write_artifact(
        "transformations.json",
        TaxonomyTransformationSet(
            schema_version=1,
            corpus_id="cross-prd-pilot-v1",
            records=[],
        ).model_dump_json(indent=2),
    )
    placeholder = ArtifactRef(path="pending.json", sha256=_hash("0"))
    dataset = TaxonomyDatasetManifest(
        schema_version=1,
        corpus_id="cross-prd-pilot-v1",
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        created_at=NOW,
        documents=documents,
        gold_artifact=placeholder,
        prediction_artifact=placeholder,
        transformation_artifact=transformations,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )
    gold = _gold_set(dataset, [gold_record])
    frozen = _frozen_policy(dataset, gold)
    output_manifest = _output_manifest()
    output_manifest_ref = write_artifact(
        "output-manifest.json",
        output_manifest.model_dump_json(indent=2),
    )
    predictions = _predictions(
        dataset,
        [
            _prediction(
                "gold1",
                document_key="drama-v2",
                system_key="drama",
                split="test",
                requirement_unit_id=gold_record.requirement_unit_id,
            )
        ],
        policy_hash=frozen.policy_hash,
        frozen_policy_hash=frozen.canonical_hash,
        schema_version=2,
        known_nodes=_known_node_views("drama", output_manifest),
        output_manifest_hashes={"drama": manifest_hash(output_manifest)},
        output_manifest_artifacts={"drama": output_manifest_ref},
    )
    gold_ref = write_artifact("gold.json", gold.model_dump_json(indent=2))
    prediction_ref = write_artifact("prediction-input.json", predictions.model_dump_json(indent=2))
    dataset = dataset.model_copy(update={"gold_artifact": gold_ref, "prediction_artifact": prediction_ref})
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    policy_path = tmp_path / "frozen-policy.json"
    policy_path.write_text(frozen.model_dump_json(indent=2), encoding="utf-8")
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(
        _gate().model_dump_json(indent=2),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    exit_code = evaluation_cli_main(
        [
            "--dataset",
            str(dataset_path),
            "--policy",
            str(policy_path),
            "--gate",
            str(gate_path),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert (output / "REPORT.md").is_file()
    assert (output / "metrics.json").is_file()
