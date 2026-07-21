"""跨 PRD Taxonomy 泛化评估、阈值校准与初始激活审核。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from src.testcase_generator.schemas.requirement_unit import RequirementUnit
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest, TaxonomyNodeManifest
from src.testcase_generator.schemas.taxonomy_evaluation import (
    ArtifactRef,
    TaxonomyActivationAuthorization,
    TaxonomyCalibrationNodeSummary,
    TaxonomyCalibrationPackage,
    TaxonomyCalibrationReview,
    TaxonomyCalibrationSystemMetrics,
    TaxonomyDatasetDocument,
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
    TaxonomyEvaluationMetrics,
    TaxonomyEvaluationResult,
    TaxonomyFrozenPolicy,
    TaxonomyGoldNode,
    TaxonomyGoldRecord,
    TaxonomyGoldSet,
    TaxonomyPredictionRecord,
    TaxonomyPredictionSet,
    TaxonomyProposedNode,
    TaxonomySystemEvaluation,
    TaxonomyTransformationSet,
)
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy
from src.testcase_generator.services.requirement_unit_service import RequirementUnitExtractionResult
from src.testcase_generator.services.taxonomy_manifest import manifest_hash

RequirementUnitIndex = dict[str, dict[str, RequirementUnit]]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _json_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _resolve_path(manifest_path: Path, ref: ArtifactRef) -> Path:
    path = Path(ref.path).expanduser()
    return path if path.is_absolute() else manifest_path.parent / path


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_evaluation_artifact_hashes(
    *,
    dataset: TaxonomyDatasetManifest,
    manifest_path: Path,
    document_splits: set[str] | None = None,
    include_transformations: bool = True,
) -> None:
    """在读取内容前验证固定快照，防止文档或 gold 被静默替换。"""

    refs: list[tuple[str, str, ArtifactRef]] = []
    for document in dataset.documents:
        if document_splits is not None and document.split not in document_splits:
            continue
        refs.append((document.document_key, "source", document.source))
        refs.append((document.document_key, "requirement_units", document.requirement_units))
    refs.extend(
        (
            (dataset.corpus_id, "gold", dataset.gold_artifact),
            (dataset.corpus_id, "predictions", dataset.prediction_artifact),
        )
    )
    if include_transformations:
        refs.append((dataset.corpus_id, "transformations", dataset.transformation_artifact))
    for owner, kind, ref in refs:
        path = _resolve_path(manifest_path, ref)
        if not path.is_file():
            raise ValueError(f"artifact_not_found:{owner}:{kind}")
        if _file_hash(path) != ref.sha256:
            raise ValueError(f"artifact_hash_mismatch:{owner}:{kind}")


def load_requirement_unit_index(
    *,
    dataset: TaxonomyDatasetManifest,
    manifest_path: Path,
    document_splits: set[str] | None = None,
) -> RequirementUnitIndex:
    """读取并重放 grounded unit artifact，确保 gold 不能引用虚构需求。"""

    result: RequirementUnitIndex = {}
    global_unit_owner: dict[str, str] = {}
    for document in dataset.documents:
        if document_splits is not None and document.split not in document_splits:
            continue
        artifact_path = _resolve_path(manifest_path, document.requirement_units)
        extraction = RequirementUnitExtractionResult.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        if extraction.document_id != document.document_id:
            raise ValueError(f"requirement_unit_document_id_mismatch:{document.document_key}")
        if extraction.document_content_hash != document.source.sha256:
            raise ValueError(f"requirement_unit_document_hash_mismatch:{document.document_key}")

        source_path = _resolve_path(manifest_path, document.source)
        source_snapshot = source_path.read_text(encoding="utf-8")
        document_units: dict[str, RequirementUnit] = {}
        for unit in extraction.units:
            if unit.system_id != document.system_id:
                raise ValueError(f"requirement_unit_system_mismatch:{unit.unit_id}")
            if unit.document_id != document.document_id:
                raise ValueError(f"requirement_unit_document_mismatch:{unit.unit_id}")
            if unit.document_content_hash != document.source.sha256:
                raise ValueError(f"requirement_unit_snapshot_mismatch:{unit.unit_id}")
            if unit.source_quote not in source_snapshot:
                raise ValueError(f"requirement_unit_quote_not_grounded:{unit.unit_id}")
            owner = global_unit_owner.setdefault(unit.unit_id, document.document_key)
            if owner != document.document_key:
                raise ValueError(f"requirement_unit_cross_document_collision:{unit.unit_id}")
            if unit.unit_id in document_units:
                raise ValueError(f"duplicate_requirement_unit:{unit.unit_id}")
            document_units[unit.unit_id] = unit
        result[document.document_key] = document_units
    return result


def load_evaluation_inputs(
    *,
    dataset_path: Path,
    policy_path: Path,
) -> tuple[
    TaxonomyDatasetManifest,
    TaxonomyGoldSet,
    TaxonomyPredictionSet,
    TaxonomyTransformationSet,
    RequirementUnitIndex,
    TaxonomyFrozenPolicy,
]:
    dataset = TaxonomyDatasetManifest.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=dataset_path)
    gold_path = _resolve_path(dataset_path, dataset.gold_artifact)
    prediction_path = _resolve_path(dataset_path, dataset.prediction_artifact)
    transformation_path = _resolve_path(dataset_path, dataset.transformation_artifact)
    gold = TaxonomyGoldSet.model_validate_json(gold_path.read_text(encoding="utf-8"))
    predictions = TaxonomyPredictionSet.model_validate_json(prediction_path.read_text(encoding="utf-8"))
    transformations = TaxonomyTransformationSet.model_validate_json(transformation_path.read_text(encoding="utf-8"))
    requirement_units = load_requirement_unit_index(dataset=dataset, manifest_path=dataset_path)
    frozen_policy = TaxonomyFrozenPolicy.model_validate_json(policy_path.read_text(encoding="utf-8"))
    return dataset, gold, predictions, transformations, requirement_units, frozen_policy


def _validate_transformations(
    *,
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
    transformations: TaxonomyTransformationSet,
    requirement_units: RequirementUnitIndex,
) -> None:
    if transformations.corpus_id != dataset.corpus_id:
        raise ValueError("transformation_corpus_mismatch")
    gold_by_id = {item.record_id: item for item in gold.records}
    transformation_by_variant = {item.variant_record_id: item for item in transformations.records}
    expected_variant_ids = {item.record_id for item in gold.records if item.variant_kind != "original"}
    if set(transformation_by_variant) != expected_variant_ids:
        raise ValueError("transformation_gold_coverage_mismatch")
    for item in transformations.records:
        source = gold_by_id.get(item.source_record_id)
        variant = gold_by_id.get(item.variant_record_id)
        if source is None or variant is None:
            raise ValueError(f"transformation_gold_record_missing:{item.transformation_id}")
        if source.variant_kind != "original":
            raise ValueError(f"transformation_source_not_original:{item.transformation_id}")
        if (
            source.system_key != item.system_key
            or variant.system_key != item.system_key
            or source.split != item.split
            or variant.split != item.split
            or source.semantic_group_id != item.semantic_group_id
            or variant.semantic_group_id != item.semantic_group_id
            or variant.variant_kind != item.kind
        ):
            raise ValueError(f"transformation_metadata_mismatch:{item.transformation_id}")
        source_unit = requirement_units[source.document_key][source.requirement_unit_id]
        variant_unit = requirement_units[variant.document_key][variant.requirement_unit_id]
        source_text_hash = hashlib.sha256(source_unit.statement.encode("utf-8")).hexdigest()
        variant_text_hash = hashlib.sha256(variant_unit.statement.encode("utf-8")).hexdigest()
        if item.source_text_hash != source_text_hash or item.variant_text_hash != variant_text_hash:
            raise ValueError(f"transformation_text_hash_mismatch:{item.transformation_id}")


def _validate_record_references(
    *,
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
    predictions: TaxonomyPredictionSet,
    requirement_units: RequirementUnitIndex,
    require_complete_corpus: bool = True,
) -> None:
    if gold.corpus_id != dataset.corpus_id:
        raise ValueError("gold_corpus_mismatch")
    if gold.dataset_hash != dataset.dataset_hash:
        raise ValueError("gold_dataset_mismatch")
    if predictions.dataset_hash != dataset.dataset_hash:
        raise ValueError("prediction_dataset_mismatch")
    if dataset.created_at > gold.reviewed_at:
        raise ValueError("gold_review_precedes_dataset_freeze")
    if gold.reviewed_at > predictions.generated_at:
        raise ValueError("prediction_precedes_gold_freeze")

    documents = {item.document_key: item for item in dataset.documents}
    gold_by_id = {item.record_id: item for item in gold.records}
    prediction_split = predictions.records[0].split
    if any(record.split != prediction_split for record in gold.records):
        raise ValueError("gold_prediction_split_mismatch")
    expected_document_keys = {item.document_key for item in dataset.documents if item.split == prediction_split}
    actual_document_keys = {item.document_key for item in gold.records}
    missing_document_keys = sorted(expected_document_keys - actual_document_keys)
    if require_complete_corpus and missing_document_keys:
        raise ValueError(f"gold_document_coverage_missing:{','.join(missing_document_keys)}")
    if require_complete_corpus:
        gold_unit_ids_by_document: dict[str, set[str]] = defaultdict(set)
        for record in gold.records:
            gold_unit_ids_by_document[record.document_key].add(record.requirement_unit_id)
        for document_key in sorted(expected_document_keys):
            expected_unit_ids = set(requirement_units.get(document_key, {}))
            missing_unit_ids = sorted(expected_unit_ids - gold_unit_ids_by_document[document_key])
            if missing_unit_ids:
                preview = ",".join(missing_unit_ids[:5])
                raise ValueError(
                    f"gold_requirement_unit_coverage_missing:{document_key}:count={len(missing_unit_ids)}:{preview}"
                )

    unit_owner: dict[str, tuple[TaxonomyDatasetDocument, RequirementUnit]] = {}
    for dataset_document in dataset.documents:
        for indexed_unit in requirement_units.get(dataset_document.document_key, {}).values():
            unit_owner[indexed_unit.unit_id] = (dataset_document, indexed_unit)
    for gold_record in gold.records:
        gold_document = documents.get(gold_record.document_key)
        if gold_document is None:
            raise ValueError(f"gold_document_missing:{gold_record.record_id}")
        if gold_document.system_key != gold_record.system_key or gold_document.split != gold_record.split:
            raise ValueError(f"gold_document_metadata_mismatch:{gold_record.record_id}")
        gold_unit = requirement_units.get(gold_record.document_key, {}).get(gold_record.requirement_unit_id)
        if gold_unit is None:
            raise ValueError(f"gold_requirement_unit_missing:{gold_record.record_id}")
        if gold_unit.source_ref not in gold_record.gold_evidence:
            raise ValueError(f"gold_source_evidence_mismatch:{gold_record.record_id}")
        if gold_record.eligible_for_auto and gold_unit.scope_status != "atomic":
            raise ValueError(f"gold_non_atomic_auto_eligibility:{gold_record.record_id}")
    for prediction_record in predictions.records:
        prediction_document = documents.get(prediction_record.document_key)
        if prediction_document is None:
            raise ValueError(f"prediction_document_missing:{prediction_record.record_id}")
        if (
            prediction_document.system_key != prediction_record.system_key
            or prediction_document.split != prediction_record.split
        ):
            raise ValueError(f"prediction_document_metadata_mismatch:{prediction_record.record_id}")
        matching_gold_record = gold_by_id.get(prediction_record.record_id)
        if matching_gold_record is not None and (
            prediction_record.document_key != matching_gold_record.document_key
            or prediction_record.system_key != matching_gold_record.system_key
            or prediction_record.split != matching_gold_record.split
            or prediction_record.requirement_unit_id != matching_gold_record.requirement_unit_id
        ):
            raise ValueError(f"prediction_gold_metadata_mismatch:{prediction_record.record_id}")
        prediction_unit = requirement_units.get(prediction_record.document_key, {}).get(
            prediction_record.requirement_unit_id
        )
        if prediction_unit is None:
            raise ValueError(f"prediction_requirement_unit_missing:{prediction_record.record_id}")

    split_systems = {item.system_key for item in dataset.documents if item.split == prediction_split}
    for proposed_node in predictions.proposed_nodes:
        if proposed_node.system_key not in split_systems:
            raise ValueError(f"prediction_node_system_not_in_split:{proposed_node.system_key}")
    for known_node in predictions.known_nodes:
        if known_node.system_key not in split_systems:
            raise ValueError(f"prediction_node_system_not_in_split:{known_node.system_key}")
    for proposed_node in predictions.proposed_nodes:
        for unit_id in proposed_node.evidence_requirement_unit_ids:
            owner = unit_owner.get(unit_id)
            if owner is None:
                raise ValueError(f"proposed_node_evidence_missing:{proposed_node.stable_key}:{unit_id}")
            document, _ = owner
            if document.system_key != proposed_node.system_key or document.split != prediction_split:
                raise ValueError(f"proposed_node_evidence_scope_mismatch:{proposed_node.stable_key}:{unit_id}")
    for gold_node in gold.expected_nodes:
        for unit_id in gold_node.evidence_requirement_unit_ids:
            owner = unit_owner.get(unit_id)
            if owner is None:
                raise ValueError(f"gold_node_evidence_missing:{gold_node.gold_node_key}:{unit_id}")
            document, _ = owner
            if document.system_key != gold_node.system_key or document.split != prediction_split:
                raise ValueError(f"gold_node_evidence_scope_mismatch:{gold_node.gold_node_key}:{unit_id}")


def _candidate_is_auto_accepted(record: TaxonomyPredictionRecord, policy: TaxonomyResolutionPolicy) -> bool:
    return bool(
        record.outcome == "candidate"
        and record.score is not None
        and record.margin is not None
        and record.score >= policy.minimum_score
        and record.margin >= policy.minimum_margin
        and not record.scope_conflict
    )


def _is_correct_primary(
    gold: TaxonomyGoldRecord,
    prediction: TaxonomyPredictionRecord,
    *,
    require_auto_eligibility: bool = True,
) -> bool:
    return bool(
        (gold.eligible_for_auto or not require_auto_eligibility)
        and gold.expected_disposition == "reuse"
        and prediction.predicted_primary_stable_key in gold.acceptable_primary_keys
    )


def calibrate_resolution_policy(
    *,
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
    predictions: TaxonomyPredictionSet,
    requirement_units: RequirementUnitIndex,
    base_policy: TaxonomyResolutionPolicy,
    calibrated_at: datetime,
    minimum_precision: float,
    minimum_auto_decisions: int = 1,
) -> TaxonomyFrozenPolicy:
    """只用 dev 的原始 top-1 score/margin 冻结阈值，最大化满足精度门的覆盖。"""

    if calibrated_at.tzinfo is None or calibrated_at.utcoffset() is None:
        raise ValueError("policy_calibrated_at_timezone_required")
    if not 0 <= minimum_precision <= 1:
        raise ValueError("minimum_precision_out_of_range")
    if minimum_auto_decisions < 1:
        raise ValueError("minimum_auto_decisions_invalid")
    if any(item.split == "test" for item in gold.records) or any(item.split == "test" for item in predictions.records):
        raise ValueError("test_data_for_calibration_forbidden")
    if predictions.frozen_policy_hash is not None:
        raise ValueError("calibration_prediction_frozen_policy_forbidden")
    _validate_record_references(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=requirement_units,
        require_complete_corpus=True,
    )
    if predictions.policy_hash != base_policy.canonical_hash:
        raise ValueError("calibration_base_policy_mismatch")
    if predictions.prompt_revisions != dataset.prompt_revisions:
        raise ValueError("calibration_prompt_revision_mismatch")
    if predictions.model_revisions != dataset.model_revisions:
        raise ValueError("calibration_model_revision_mismatch")
    if predictions.generated_at > calibrated_at:
        raise ValueError("calibration_precedes_predictions")

    gold_by_id = {item.record_id: item for item in gold.records}
    extra_prediction_ids = {item.record_id for item in predictions.records} - set(gold_by_id)
    if extra_prediction_ids:
        raise ValueError("calibration_prediction_without_gold")
    candidate_predictions = [item for item in predictions.records if item.outcome == "candidate"]
    if not candidate_predictions:
        raise ValueError("calibration_candidate_required")

    scores = sorted({0.0, *(item.score for item in candidate_predictions if item.score is not None)})
    margins = sorted({0.0, *(item.margin for item in candidate_predictions if item.margin is not None)})
    records_by_system = {
        system_key: [item for item in gold.records if item.system_key == system_key]
        for system_key in sorted({item.system_key for item in gold.records})
    }
    eligible_by_system = {
        system_key: [item for item in records if item.eligible_for_auto]
        for system_key, records in records_by_system.items()
    }
    if any(not items for items in eligible_by_system.values()):
        raise ValueError("calibration_system_has_no_eligible_gold")
    options: list[
        tuple[
            float,
            int,
            float,
            float,
            float,
            list[TaxonomyCalibrationSystemMetrics],
        ]
    ] = []
    for score_threshold in scores:
        for margin_threshold in margins:
            accepted = [
                item
                for item in candidate_predictions
                if item.score is not None
                and item.margin is not None
                and item.score >= score_threshold
                and item.margin >= margin_threshold
                and not item.scope_conflict
            ]
            accepted_by_system = {
                system_key: [item for item in accepted if item.system_key == system_key]
                for system_key in eligible_by_system
            }
            system_metrics: list[TaxonomyCalibrationSystemMetrics] = []
            option_valid = True
            for system_key, eligible in eligible_by_system.items():
                system_accepted = accepted_by_system[system_key]
                eligible_accepted = [item for item in system_accepted if gold_by_id[item.record_id].eligible_for_auto]
                if len(eligible_accepted) < minimum_auto_decisions:
                    option_valid = False
                    break
                correct = sum(1 for item in system_accepted if _is_correct_primary(gold_by_id[item.record_id], item))
                precision = correct / len(system_accepted)
                if precision < minimum_precision:
                    option_valid = False
                    break
                system_metrics.append(
                    TaxonomyCalibrationSystemMetrics(
                        system_key=system_key,
                        record_count=len(records_by_system[system_key]),
                        eligible_record_count=len(eligible),
                        auto_decision_count=len(system_accepted),
                        eligible_auto_decision_count=len(eligible_accepted),
                        correct_auto_decision_count=correct,
                        precision=precision,
                        auto_coverage=len(eligible_accepted) / len(eligible),
                    )
                )
            if option_valid:
                options.append(
                    (
                        min(item.auto_coverage for item in system_metrics),
                        sum(item.eligible_auto_decision_count for item in system_metrics),
                        min(item.precision for item in system_metrics),
                        score_threshold,
                        margin_threshold,
                        system_metrics,
                    )
                )
    if not options:
        raise ValueError("no_calibrated_threshold_meets_precision_gate")

    coverage, _, precision, score_threshold, margin_threshold, system_metrics = max(
        options,
        key=lambda item: (item[0], item[1], item[2], item[3], item[4]),
    )
    accepted_records = [
        item
        for item in candidate_predictions
        if item.score is not None
        and item.margin is not None
        and item.score >= score_threshold
        and item.margin >= margin_threshold
        and not item.scope_conflict
    ]
    correct_count = sum(1 for item in accepted_records if _is_correct_primary(gold_by_id[item.record_id], item))
    calibration_input_hash = hashlib.sha256(
        _json_key(
            {
                "dataset_hash": dataset.dataset_hash,
                "gold_hash": gold.canonical_hash,
                "prediction_hash": predictions.canonical_hash,
                "base_policy_hash": base_policy.canonical_hash,
            }
        ).encode("utf-8")
    ).hexdigest()
    policy = base_policy.model_copy(
        update={
            "minimum_score": score_threshold,
            "minimum_margin": margin_threshold,
        }
    )
    return TaxonomyFrozenPolicy(
        schema_version=1,
        policy=policy,
        policy_hash=policy.canonical_hash,
        calibrated_at=calibrated_at,
        calibration_split="dev",
        calibration_dataset_hash=dataset.dataset_hash,
        calibration_gold_hash=gold.canonical_hash,
        calibration_gold_review_method=gold.review_method,
        calibration_input_hash=calibration_input_hash,
        observed_precision=precision,
        observed_auto_coverage=coverage,
        calibration_system_metrics=system_metrics,
        calibration_record_count=len(gold.records),
        eligible_record_count=sum(len(items) for items in eligible_by_system.values()),
        auto_decision_count=len(accepted_records),
        eligible_auto_decision_count=sum(item.eligible_auto_decision_count for item in system_metrics),
        correct_auto_decision_count=correct_count,
    )


def _decision(
    gold: TaxonomyGoldRecord,
    prediction: TaxonomyPredictionRecord | None,
    policy: TaxonomyResolutionPolicy,
) -> tuple[str, bool | None]:
    if prediction is None:
        return "missing", None
    if _candidate_is_auto_accepted(prediction, policy):
        return "auto_mapped", _is_correct_primary(gold, prediction)
    if prediction.outcome == "candidate" or prediction.outcome == "unresolved":
        return "abstained", None
    if prediction.outcome == "approved_mapping":
        return "approved_mapping", _is_correct_primary(
            gold,
            prediction,
            require_auto_eligibility=False,
        )
    return prediction.outcome, None


def _decision_signature(
    gold: TaxonomyGoldRecord,
    prediction: TaxonomyPredictionRecord | None,
    policy: TaxonomyResolutionPolicy,
    proposal_shapes_by_unit: dict[str, tuple[tuple[str, str, str | None], ...]],
) -> tuple[str, str | None]:
    outcome, _ = _decision(gold, prediction, policy)
    if outcome in {"auto_mapped", "approved_mapping"} and prediction is not None:
        return "mapped", prediction.predicted_primary_stable_key
    if outcome == "proposal" and prediction is not None:
        shapes = proposal_shapes_by_unit.get(prediction.requirement_unit_id, ())
        if not shapes:
            return "proposal_missing_node", gold.record_id
        return outcome, _json_key({"operation": prediction.predicted_operation, "nodes": shapes})
    if outcome == "abstained":
        unresolved_kind = (
            prediction.unresolved_kind
            if prediction is not None and prediction.outcome == "unresolved"
            else "candidate_below_frozen_policy"
        )
        return outcome, unresolved_kind
    if outcome in {"error", "missing"}:
        return outcome, gold.record_id
    return outcome, None


def _node_metrics(
    *,
    system_key: str,
    gold_records: list[TaxonomyGoldRecord],
    gold_nodes: list[TaxonomyGoldNode],
    proposed_nodes: list[TaxonomyProposedNode],
) -> tuple[float | None, float | None, float, float]:
    nodes = [item for item in proposed_nodes if item.system_key == system_key]
    system_gold_nodes = [item for item in gold_nodes if item.system_key == system_key]
    gold_nodes_by_key = {item.gold_node_key: item for item in system_gold_nodes}
    expected_record_groups = {
        item.expected_new_node_stable_key
        for item in gold_records
        if item.expected_disposition == "new_node" and item.expected_new_node_stable_key is not None
    }
    expected_group_count = len(system_gold_nodes) if system_gold_nodes else len(expected_record_groups)
    if not nodes:
        return None, 0 if expected_group_count else None, 0, 0
    gold_by_unit = {item.requirement_unit_id: item for item in gold_records}
    expected_groups: dict[str, list[TaxonomyProposedNode]] = defaultdict(list)
    matched_expected_groups: set[str] = set()
    correct = 0
    unsupported = 0
    for node in nodes:
        evidence_ids = set(node.evidence_requirement_unit_ids)
        node_matches = [
            item
            for item in system_gold_nodes
            if item.node_type == node.node_type and set(item.evidence_requirement_unit_ids) == evidence_ids
        ]
        if len(node_matches) == 1:
            match = node_matches[0]
            expected_groups[match.gold_node_key].append(node)
            expected_parent_keys: set[str | None]
            if match.parent_gold_node_key is None:
                expected_parent_keys = {None}
            else:
                expected_parent_keys = set(gold_nodes_by_key[match.parent_gold_node_key].accepted_keys)
            if node.stable_key in match.accepted_keys and node.parent_stable_key in expected_parent_keys:
                correct += 1
                matched_expected_groups.add(f"gold:{match.gold_node_key}")
            continue
        if system_gold_nodes:
            unsupported += 1
            continue
        evidence = [gold_by_unit.get(unit_id) for unit_id in node.evidence_requirement_unit_ids]
        if not evidence or any(item is None or item.expected_disposition != "new_node" for item in evidence):
            unsupported += 1
            continue
        supported_records = [item for item in evidence if item is not None]
        compatible = set(supported_records[0].acceptable_new_node_keys)
        for record in supported_records[1:]:
            compatible &= record.acceptable_new_node_keys
        if not compatible:
            unsupported += 1
            continue
        group_key = sorted(compatible)[0]
        expected_groups[group_key].append(node)
        if node.stable_key in compatible:
            correct += 1
            matched_expected_groups.add(f"record:{group_key}")

    duplicate_count = sum(max(0, len({item.stable_key for item in group}) - 1) for group in expected_groups.values())
    total = len(nodes)
    recall = len(matched_expected_groups) / expected_group_count if expected_group_count else None
    return correct / total, recall, duplicate_count / total, unsupported / total


def _structural_metrics(
    *,
    system_key: str,
    predictions: TaxonomyPredictionSet,
) -> tuple[float, list[str]]:
    proposed = [item for item in predictions.proposed_nodes if item.system_key == system_key]
    known = [item for item in predictions.known_nodes if item.system_key == system_key]
    violations: list[str] = []
    proposed_keys = [item.stable_key for item in proposed]
    known_keys = {item.stable_key for item in known}
    all_keys = set(proposed_keys) | known_keys

    if len(proposed_keys) != len(set(proposed_keys)) or set(proposed_keys) & known_keys:
        violations.append("duplicate_stable_key")
    if any(item.parent_stable_key and item.parent_stable_key not in all_keys for item in proposed) or any(
        item.parent_stable_key and item.parent_stable_key not in all_keys for item in known
    ):
        violations.append("parent_missing")

    parent_by_key = {item.stable_key: item.parent_stable_key for item in known}
    parent_by_key.update({item.stable_key: item.parent_stable_key for item in proposed})
    for start in parent_by_key:
        seen: set[str] = set()
        current: str | None = start
        while current is not None and current in parent_by_key:
            if current in seen:
                violations.append("parent_cycle")
                break
            seen.add(current)
            current = parent_by_key[current]
        if "parent_cycle" in violations:
            break

    type_by_key = {item.stable_key: item.node_type for item in known}
    type_by_key.update({item.stable_key: item.node_type for item in proposed})
    proposed_capability_child = any(
        item.parent_stable_key and type_by_key.get(item.parent_stable_key) == "capability" for item in proposed
    )
    known_capability_child = any(
        item.parent_stable_key and type_by_key.get(item.parent_stable_key) == "capability" for item in known
    )
    if proposed_capability_child or known_capability_child:
        violations.append("capability_has_child")

    checks = 4
    return (checks - len(set(violations))) / checks, sorted(set(violations))


def _stability_metrics(
    *,
    records: list[TaxonomyGoldRecord],
    predictions: TaxonomyPredictionSet,
    policy: TaxonomyResolutionPolicy,
) -> tuple[float | None, dict[str, float]]:
    predictions_by_id = {item.record_id: item for item in predictions.records}
    proposal_shapes: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
    for node in predictions.proposed_nodes:
        shape = (node.stable_key, node.node_type, node.parent_stable_key)
        for unit_id in node.evidence_requirement_unit_ids:
            proposal_shapes[unit_id].append(shape)
    proposal_shapes_by_unit = {
        unit_id: tuple(sorted(shapes, key=lambda item: (item[0], item[1], item[2] or "")))
        for unit_id, shapes in proposal_shapes.items()
    }
    groups: dict[str, list[TaxonomyGoldRecord]] = defaultdict(list)
    for record in records:
        if record.semantic_group_id:
            groups[record.semantic_group_id].append(record)
    comparisons: list[tuple[str, bool]] = []
    for grouped in groups.values():
        originals = sorted(
            (item for item in grouped if item.variant_kind == "original"),
            key=lambda item: item.record_id,
        )
        if not originals:
            continue
        baseline = originals[0]
        baseline_signature = _decision_signature(
            baseline,
            predictions_by_id.get(baseline.record_id),
            policy,
            proposal_shapes_by_unit,
        )
        for variant in grouped:
            if variant.record_id == baseline.record_id or variant.variant_kind == "original":
                continue
            comparisons.append(
                (
                    variant.variant_kind,
                    _decision_signature(
                        variant,
                        predictions_by_id.get(variant.record_id),
                        policy,
                        proposal_shapes_by_unit,
                    )
                    == baseline_signature,
                )
            )
    by_variant: dict[str, float] = {}
    for kind in sorted({kind for kind, _ in comparisons}):
        values = [matched for variant_kind, matched in comparisons if variant_kind == kind]
        by_variant[kind] = sum(values) / len(values)
    overall = sum(matched for _, matched in comparisons) / len(comparisons) if comparisons else None
    return overall, by_variant


def _evaluate_system(
    *,
    system_key: str,
    split: str,
    records: list[TaxonomyGoldRecord],
    gold_nodes: list[TaxonomyGoldNode],
    predictions_by_id: dict[str, TaxonomyPredictionRecord],
    predictions: TaxonomyPredictionSet,
    policy: TaxonomyResolutionPolicy,
    gate: TaxonomyEvaluationGate,
    independent_gold: bool,
    independent_calibration_gold: bool,
) -> tuple[TaxonomySystemEvaluation, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    decisions: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    abstentions: list[dict[str, object]] = []
    auto_count = 0
    eligible_auto_count = 0
    correct_auto = 0
    correct_auto_reuse = 0
    path_correct = 0
    path_total = 0
    predicted_abstentions = 0
    correct_abstentions = 0
    expected_abstentions = 0
    correct_expected_abstentions = 0
    intervention_count = 0
    operational_failures = 0
    expected_operation_count = 0
    correct_operation_count = 0
    eligible_count = sum(1 for item in records if item.eligible_for_auto)
    expected_reuse_count = sum(1 for item in records if item.expected_disposition == "reuse")

    for gold_record in sorted(records, key=lambda item: item.record_id):
        prediction = predictions_by_id.get(gold_record.record_id)
        outcome, correct = _decision(gold_record, prediction, policy)
        if gold_record.expected_operation is not None:
            expected_operation_count += 1
            if (
                prediction is not None
                and prediction.outcome == "proposal"
                and prediction.predicted_operation == gold_record.expected_operation
            ):
                correct_operation_count += 1
        decisions.append(
            {
                "record_id": gold_record.record_id,
                "system_key": system_key,
                "split": split,
                "decision": outcome,
                "correct": correct,
                "predicted_primary_stable_key": (
                    prediction.predicted_primary_stable_key if prediction is not None else None
                ),
                "predicted_operation": prediction.predicted_operation if prediction is not None else None,
                "expected_operation": gold_record.expected_operation,
            }
        )
        if outcome in {"auto_mapped", "approved_mapping"}:
            auto_count += 1
            if gold_record.eligible_for_auto:
                eligible_auto_count += 1
            if correct:
                correct_auto += 1
                correct_auto_reuse += 1
            if gold_record.expected_disposition == "reuse" and prediction is not None:
                path_total += 1
                acceptable_paths = {tuple(gold_record.expected_path), *map(tuple, gold_record.acceptable_paths)}
                if tuple(prediction.predicted_path) in acceptable_paths:
                    path_correct += 1
        if gold_record.expected_disposition == "abstain":
            expected_abstentions += 1
        if outcome in {"abstained", "error", "missing"}:
            abstention: dict[str, object] = {
                "record_id": gold_record.record_id,
                "system_key": system_key,
                "split": split,
                "decision": outcome,
                "expected_disposition": gold_record.expected_disposition,
            }
            abstentions.append(abstention)
        if outcome == "abstained":
            predicted_abstentions += 1
            if gold_record.expected_disposition == "abstain":
                correct_abstentions += 1
                correct_expected_abstentions += 1
        if outcome in {"abstained", "proposal", "error", "missing"}:
            intervention_count += 1
        if outcome in {"error", "missing"}:
            operational_failures += 1
            errors.append(
                {
                    "record_id": gold_record.record_id,
                    "system_key": system_key,
                    "split": split,
                    "error_code": prediction.error_code if prediction is not None else "missing_prediction",
                }
            )

    new_precision, new_recall, duplicate_rate, unsupported_rate = _node_metrics(
        system_key=system_key,
        gold_records=records,
        gold_nodes=gold_nodes,
        proposed_nodes=predictions.proposed_nodes,
    )
    structural_rate, structural_violations = _structural_metrics(
        system_key=system_key,
        predictions=predictions,
    )
    stability_rate, stability_by_variant = _stability_metrics(
        records=records,
        predictions=predictions,
        policy=policy,
    )
    record_count = len(records)
    metrics = TaxonomyEvaluationMetrics(
        record_count=record_count,
        auto_mapped_count=auto_count,
        correct_auto_mapped_count=correct_auto,
        exact_primary_precision=_ratio(correct_auto, auto_count),
        auto_coverage=eligible_auto_count / eligible_count if eligible_count else 0,
        expected_reuse_coverage=_ratio(correct_auto_reuse, expected_reuse_count),
        hierarchical_path_accuracy=_ratio(path_correct, path_total),
        abstention_precision=_ratio(correct_abstentions, predicted_abstentions),
        abstention_recall=_ratio(correct_expected_abstentions, expected_abstentions),
        new_node_precision=new_precision,
        new_node_recall=new_recall,
        proposal_operation_type_accuracy=_ratio(correct_operation_count, expected_operation_count),
        duplicate_node_rate=duplicate_rate,
        unsupported_node_rate=unsupported_rate,
        semantic_stability_rate=stability_rate,
        stability_by_variant=stability_by_variant,
        human_intervention_rate=intervention_count / record_count if record_count else 0,
        operational_failure_rate=operational_failures / record_count if record_count else 0,
        structural_invariant_rate=structural_rate,
        structural_violations=structural_violations,
    )

    failures: list[str] = []
    incomplete: list[str] = []
    if gate.require_independent_gold:
        if not independent_calibration_gold:
            incomplete.append("independent_dev_gold_missing")
        if not independent_gold:
            incomplete.append(f"independent_{split}_gold_missing")
    if auto_count:
        if metrics.exact_primary_precision is None:
            incomplete.append("reuse_precision_missing")
        elif metrics.exact_primary_precision < gate.minimum_reuse_precision:
            failures.append("reuse_precision_below_gate")
    elif expected_reuse_count:
        incomplete.append("reuse_precision_missing")
    if expected_reuse_count:
        if gate.require_operational_thresholds and gate.minimum_expected_reuse_coverage is None:
            incomplete.append("reuse_coverage_threshold_missing")
        elif (
            gate.minimum_expected_reuse_coverage is not None
            and metrics.expected_reuse_coverage is not None
            and metrics.expected_reuse_coverage < gate.minimum_expected_reuse_coverage
        ):
            failures.append("reuse_coverage_below_gate")
        if metrics.hierarchical_path_accuracy is None:
            incomplete.append("hierarchical_path_accuracy_missing")
        elif metrics.hierarchical_path_accuracy < gate.minimum_hierarchical_path_accuracy:
            failures.append("hierarchical_path_accuracy_below_gate")
    if gate.minimum_semantic_stability > 0:
        if metrics.semantic_stability_rate is None:
            incomplete.append("semantic_transformations_missing")
        elif metrics.semantic_stability_rate < gate.minimum_semantic_stability:
            failures.append("semantic_stability_below_gate")
    if metrics.duplicate_node_rate > gate.maximum_duplicate_node_rate:
        failures.append("duplicate_node_rate_above_gate")
    if metrics.unsupported_node_rate > gate.maximum_unsupported_node_rate:
        failures.append("unsupported_node_rate_above_gate")
    if metrics.structural_invariant_rate < gate.minimum_structural_invariant_rate:
        failures.append("structural_invariant_below_gate")

    expects_new_node = any(item.expected_disposition == "new_node" for item in records)
    if gate.require_new_node_baseline and not expects_new_node:
        incomplete.append("new_node_baseline_missing")
    elif expects_new_node and metrics.new_node_precision is None:
        failures.append("new_node_predictions_missing")
    if expects_new_node:
        if gate.require_operational_thresholds and gate.minimum_new_node_precision is None:
            incomplete.append("new_node_precision_threshold_missing")
        elif gate.minimum_new_node_precision is not None and (
            metrics.new_node_precision is None or metrics.new_node_precision < gate.minimum_new_node_precision
        ):
            failures.append("new_node_precision_below_gate")
        if gate.require_operational_thresholds and gate.minimum_new_node_recall is None:
            incomplete.append("new_node_recall_threshold_missing")
        elif gate.minimum_new_node_recall is not None and (
            metrics.new_node_recall is None or metrics.new_node_recall < gate.minimum_new_node_recall
        ):
            failures.append("new_node_recall_below_gate")
    if expected_operation_count:
        if gate.require_operational_thresholds and gate.minimum_proposal_operation_type_accuracy is None:
            incomplete.append("proposal_operation_type_accuracy_threshold_missing")
        elif gate.minimum_proposal_operation_type_accuracy is not None and (
            metrics.proposal_operation_type_accuracy is None
            or metrics.proposal_operation_type_accuracy < gate.minimum_proposal_operation_type_accuracy
        ):
            failures.append("proposal_operation_type_accuracy_below_gate")
    if gate.require_operational_thresholds and gate.maximum_human_intervention_rate is None:
        incomplete.append("human_intervention_threshold_missing")
    elif (
        gate.maximum_human_intervention_rate is not None
        and metrics.human_intervention_rate > gate.maximum_human_intervention_rate
    ):
        failures.append("human_intervention_rate_above_gate")
    if metrics.operational_failure_rate > gate.maximum_operational_failure_rate:
        failures.append("operational_failure_rate_above_gate")

    status = "fail" if failures else "incomplete" if incomplete else "pass"
    return (
        TaxonomySystemEvaluation(
            system_key=system_key,
            split=split,
            metrics=metrics,
            gate_status=status,
            gate_findings=[*failures, *incomplete],
        ),
        decisions,
        errors,
        abstentions,
    )


def evaluate_taxonomy_generalization(
    *,
    dataset: TaxonomyDatasetManifest,
    gold: TaxonomyGoldSet,
    predictions: TaxonomyPredictionSet,
    requirement_units: RequirementUnitIndex,
    transformations: TaxonomyTransformationSet | None = None,
    frozen_policy: TaxonomyFrozenPolicy,
    gate: TaxonomyEvaluationGate,
    evaluated_at: datetime | None = None,
) -> TaxonomyEvaluationResult:
    """逐系统、逐 split 计算门禁；不生成跨系统聚合精度。"""

    now = evaluated_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluation_time_timezone_required")
    if now < predictions.generated_at:
        raise ValueError("evaluation_precedes_predictions")
    _validate_record_references(
        dataset=dataset,
        gold=gold,
        predictions=predictions,
        requirement_units=requirement_units,
        require_complete_corpus=gate.require_complete_corpus,
    )
    if transformations is not None:
        _validate_transformations(
            dataset=dataset,
            gold=gold,
            transformations=transformations,
            requirement_units=requirement_units,
        )
    if frozen_policy.calibration_dataset_hash != dataset.dataset_hash:
        raise ValueError("frozen_policy_dataset_mismatch")
    if frozen_policy.calibrated_at < dataset.created_at:
        raise ValueError("policy_freeze_precedes_dataset")
    if predictions.policy_hash != frozen_policy.policy_hash:
        raise ValueError("prediction_policy_hash_mismatch")
    if predictions.records[0].split == "test":
        if predictions.frozen_policy_hash is None:
            raise ValueError("test_prediction_frozen_policy_hash_required")
        if predictions.frozen_policy_hash != frozen_policy.canonical_hash:
            raise ValueError("prediction_frozen_policy_hash_mismatch")
    calibration_systems = {item.system_key for item in frozen_policy.calibration_system_metrics}
    dataset_systems = {item.system_key for item in dataset.documents}
    if calibration_systems != dataset_systems:
        raise ValueError("frozen_policy_calibration_system_coverage_mismatch")
    if predictions.prompt_revisions != dataset.prompt_revisions:
        raise ValueError("prediction_prompt_revision_mismatch")
    if predictions.model_revisions != dataset.model_revisions:
        raise ValueError("prediction_model_revision_mismatch")
    if (
        any(item.split == "test" for item in predictions.records)
        and predictions.generated_at <= frozen_policy.calibrated_at
    ):
        raise ValueError("test_run_precedes_policy_freeze")

    predictions_by_id = {item.record_id: item for item in predictions.records}
    gold_by_id = {item.record_id: item for item in gold.records}
    extra_prediction_ids = sorted(set(predictions_by_id) - set(gold_by_id))
    grouped: dict[tuple[str, str], list[TaxonomyGoldRecord]] = defaultdict(list)
    for record in gold.records:
        grouped[(record.system_key, record.split)].append(record)

    system_results: list[TaxonomySystemEvaluation] = []
    decisions: list[dict[str, object]] = []
    errors: list[dict[str, object]] = [
        {"record_id": record_id, "error_code": "prediction_without_gold"} for record_id in extra_prediction_ids
    ]
    abstentions: list[dict[str, object]] = []
    for (system_key, split), records in sorted(grouped.items()):
        system_result, system_decisions, system_errors, system_abstentions = _evaluate_system(
            system_key=system_key,
            split=split,
            records=records,
            gold_nodes=gold.expected_nodes,
            predictions_by_id=predictions_by_id,
            predictions=predictions,
            policy=frozen_policy.policy,
            gate=gate,
            independent_gold=gold.review_method == "human_independent",
            independent_calibration_gold=(frozen_policy.calibration_gold_review_method == "human_independent"),
        )
        system_results.append(system_result)
        decisions.extend(system_decisions)
        errors.extend(system_errors)
        abstentions.extend(system_abstentions)

    statuses = {item.gate_status for item in system_results}
    if "fail" in statuses or extra_prediction_ids:
        overall_status = "fail"
    elif "incomplete" in statuses:
        overall_status = "incomplete"
    else:
        overall_status = "pass"
    return TaxonomyEvaluationResult(
        run_id=predictions.run_id,
        evaluated_at=now,
        corpus_id=dataset.corpus_id,
        dataset_hash=dataset.dataset_hash,
        gold_hash=gold.canonical_hash,
        prediction_hash=predictions.canonical_hash,
        policy_hash=frozen_policy.policy_hash,
        frozen_policy_hash=frozen_policy.canonical_hash,
        gate_hash=gate.canonical_hash,
        gold_review_method=gold.review_method,
        calibration_gold_review_method=frozen_policy.calibration_gold_review_method,
        output_manifest_hashes=dict(sorted(predictions.output_manifest_hashes.items())),
        system_results=system_results,
        overall_status=overall_status,
        decisions=decisions,
        errors=errors,
        abstentions=abstentions,
        tree_diff=predictions.tree_diff,
        total_cost_usd=sum(item.cost_usd for item in predictions.records),
        total_latency_ms=sum(item.latency_ms for item in predictions.records),
    )


def _format_metric(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def render_taxonomy_evaluation_report(result: TaxonomyEvaluationResult) -> str:
    lines = [
        "# Taxonomy 跨 PRD 泛化评估报告",
        "",
        "> 本报告只代表固定的 pilot corpus，不能证明所有行业、所有 PRD 都能自动正确分类。",
        "> 为避免一个系统的高分掩盖另一个系统失败，本报告不提供跨系统聚合分。",
        "",
        f"- Run: `{result.run_id}`",
        f"- Overall: **{result.overall_status.upper()}**",
        f"- Dataset hash: `{result.dataset_hash}`",
        f"- Gold hash: `{result.gold_hash}`",
        f"- Policy hash: `{result.policy_hash}`",
        f"- Frozen policy hash: `{result.frozen_policy_hash}`",
        f"- Gate hash: `{result.gate_hash}`",
        f"- Gold review: `{result.gold_review_method}`",
        f"- Calibration gold review: `{result.calibration_gold_review_method}`",
        f"- Cost: `${result.total_cost_usd:.6f}`",
        f"- Latency sum: `{result.total_latency_ms} ms`",
        "",
    ]
    for system in result.system_results:
        metric = system.metrics
        lines.extend(
            [
                f"## {system.system_key} / {system.split}",
                "",
                f"- Gate: **{system.gate_status.upper()}**",
                f"- exact-primary precision: `{_format_metric(metric.exact_primary_precision)}`",
                f"- auto coverage: `{_format_metric(metric.auto_coverage)}`",
                f"- expected reuse coverage: `{_format_metric(metric.expected_reuse_coverage)}`",
                f"- abstention precision / recall: `{_format_metric(metric.abstention_precision)}` / "
                f"`{_format_metric(metric.abstention_recall)}`",
                f"- semantic stability: `{_format_metric(metric.semantic_stability_rate)}`",
                f"- new-node precision: `{_format_metric(metric.new_node_precision)}`",
                f"- new-node recall: `{_format_metric(metric.new_node_recall)}`",
                f"- proposal operation-type accuracy: `{_format_metric(metric.proposal_operation_type_accuracy)}`",
                f"- duplicate / unsupported node rate: `{metric.duplicate_node_rate:.3f}` / "
                f"`{metric.unsupported_node_rate:.3f}`",
                f"- structural invariants: `{metric.structural_invariant_rate:.3f}`",
                f"- human intervention: `{metric.human_intervention_rate:.3f}`",
                f"- operational failure: `{metric.operational_failure_rate:.3f}`",
                f"- Findings: `{', '.join(system.gate_findings) or 'none'}`",
                "",
            ]
        )
    lines.extend(
        [
            "## 结论边界",
            "",
            "即使所有 pilot 门禁通过，也只允许进入 feature-flag/shadow 集成；不能直接默认激活或替代受控审核。",
            "模型自报 confidence 未被当作校准概率，自动接受只由冻结的 score/margin policy 决定。",
            "",
        ]
    )
    return "\n".join(lines)


def _render_system_report(result: TaxonomyEvaluationResult, system: TaxonomySystemEvaluation) -> str:
    metric = system.metrics
    return "\n".join(
        [
            f"# {system.system_key} / {system.split} Taxonomy 评估",
            "",
            "> 这是独立系统结果，不与其他系统求平均。语料仍只属于 pilot corpus。",
            "",
            f"- Gate: **{system.gate_status.upper()}**",
            f"- Run: `{result.run_id}`",
            f"- exact-primary precision: `{_format_metric(metric.exact_primary_precision)}`",
            f"- auto coverage: `{metric.auto_coverage:.3f}`",
            f"- expected reuse coverage: `{_format_metric(metric.expected_reuse_coverage)}`",
            f"- hierarchical path: `{_format_metric(metric.hierarchical_path_accuracy)}`",
            f"- semantic stability: `{_format_metric(metric.semantic_stability_rate)}`",
            f"- new-node precision: `{_format_metric(metric.new_node_precision)}`",
            f"- new-node recall: `{_format_metric(metric.new_node_recall)}`",
            f"- proposal operation-type accuracy: `{_format_metric(metric.proposal_operation_type_accuracy)}`",
            f"- duplicate-node rate: `{metric.duplicate_node_rate:.3f}`",
            f"- unsupported-node rate: `{metric.unsupported_node_rate:.3f}`",
            f"- structural invariants: `{metric.structural_invariant_rate:.3f}`",
            f"- human intervention: `{metric.human_intervention_rate:.3f}`",
            f"- Findings: `{', '.join(system.gate_findings) or 'none'}`",
            "",
        ]
    )


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_taxonomy_evaluation_artifacts(
    *,
    output_dir: Path,
    result: TaxonomyEvaluationResult,
    predictions: TaxonomyPredictionSet,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "predictions.json", predictions.model_dump(mode="json"))
    _write_json(output_dir / "errors.json", result.errors)
    _write_json(output_dir / "abstentions.json", result.abstentions)
    _write_json(output_dir / "tree-diff.json", result.tree_diff)
    _write_json(
        output_dir / "metrics.json",
        {
            "run_id": result.run_id,
            "evaluation_hash": result.canonical_hash,
            "overall_status": result.overall_status,
            "aggregate_metrics": None,
            "dataset_hash": result.dataset_hash,
            "gold_hash": result.gold_hash,
            "prediction_hash": result.prediction_hash,
            "policy_hash": result.policy_hash,
            "frozen_policy_hash": result.frozen_policy_hash,
            "gate_hash": result.gate_hash,
            "gold_review_method": result.gold_review_method,
            "calibration_gold_review_method": result.calibration_gold_review_method,
            "output_manifest_hashes": dict(sorted(result.output_manifest_hashes.items())),
            "systems": [item.model_dump(mode="json") for item in result.system_results],
        },
    )
    _write_json(
        output_dir / "cost-latency.json",
        {
            "run_id": result.run_id,
            "total_cost_usd": result.total_cost_usd,
            "total_latency_ms": result.total_latency_ms,
        },
    )
    report_path = output_dir / "REPORT.md"
    temporary = report_path.with_suffix(".md.tmp")
    temporary.write_text(render_taxonomy_evaluation_report(result), encoding="utf-8")
    temporary.replace(report_path)
    for system in result.system_results:
        system_dir = output_dir / "systems" / system.system_key / system.split
        system_dir.mkdir(parents=True, exist_ok=True)
        _write_json(system_dir / "metrics.json", system.model_dump(mode="json"))
        system_report = system_dir / "REPORT.md"
        system_temporary = system_report.with_suffix(".md.tmp")
        system_temporary.write_text(_render_system_report(result, system), encoding="utf-8")
        system_temporary.replace(system_report)


def _node_summary(node: TaxonomyNodeManifest) -> TaxonomyCalibrationNodeSummary:
    return TaxonomyCalibrationNodeSummary(
        stable_key=node.stable_key,
        display_name=node.display_name,
        node_type=node.node_type,
        parent_stable_key=node.parent_stable_key,
        definition=node.definition or "",
        scope_note=node.scope_note or "",
        evidence_count=len(node.in_scope_examples or []) + len(node.out_of_scope_examples or []),
    )


def build_calibration_package(
    *,
    draft_manifest: TaxonomyManifest,
    dataset: TaxonomyDatasetManifest,
    evaluation_result: TaxonomyEvaluationResult,
    system_key: str,
    exceptions: list[str],
    samples: list[dict[str, object]],
    prepared_by: str,
    prepared_at: datetime,
    max_samples: int = 20,
    max_boundaries: int = 20,
) -> TaxonomyCalibrationPackage:
    if draft_manifest.schema_version != 2:
        raise ValueError("calibration_package_requires_v2_manifest")
    if evaluation_result.overall_status != "pass":
        raise ValueError("calibration_package_gate_not_passed")
    if evaluation_result.dataset_hash != dataset.dataset_hash:
        raise ValueError("calibration_package_dataset_mismatch")
    if evaluation_result.gold_review_method != "human_independent":
        raise ValueError("calibration_package_independent_test_gold_required")
    if evaluation_result.calibration_gold_review_method != "human_independent":
        raise ValueError("calibration_package_independent_dev_gold_required")
    if prepared_at < evaluation_result.evaluated_at:
        raise ValueError("calibration_package_precedes_evaluation")
    system_documents = [item for item in dataset.documents if item.system_key == system_key]
    if not system_documents:
        raise ValueError("calibration_package_system_missing")
    if {item.system_id for item in system_documents} != {draft_manifest.system_id}:
        raise ValueError("calibration_package_system_id_mismatch")
    if evaluation_result.output_manifest_hashes.get(system_key) != manifest_hash(draft_manifest):
        raise ValueError("calibration_package_manifest_not_evaluated")
    system_test = next(
        (item for item in evaluation_result.system_results if item.system_key == system_key and item.split == "test"),
        None,
    )
    if system_test is None or system_test.gate_status != "pass":
        raise ValueError("calibration_package_system_test_not_passed")
    if max_samples < 1:
        raise ValueError("calibration_package_sample_limit_invalid")
    if max_boundaries < 1:
        raise ValueError("calibration_package_boundary_limit_invalid")
    roots = sorted(
        (node for node in draft_manifest.nodes if node.parent_stable_key is None),
        key=lambda node: node.stable_key,
    )
    explicit_boundaries = sorted(
        (
            node
            for node in draft_manifest.nodes
            if node.out_of_scope_examples or (node.aliases and node.parent_stable_key is not None)
        ),
        key=lambda node: node.stable_key,
    )
    fallback_boundaries = sorted(
        (node for node in draft_manifest.nodes if node.node_type == "capability" and node not in explicit_boundaries),
        key=lambda node: node.stable_key,
    )
    boundaries = [*explicit_boundaries, *fallback_boundaries][:max_boundaries]
    decision_ids = {
        item.get("record_id") for item in evaluation_result.decisions if item.get("system_key") == system_key
    }
    if any(sample.get("record_id") not in decision_ids for sample in samples):
        raise ValueError("calibration_sample_not_in_evaluation")
    focused_samples = sorted(samples, key=_json_key)[:max_samples]
    machine_exceptions = [
        f"{item.get('decision')}:{item.get('record_id')}"
        for item in evaluation_result.abstentions
        if item.get("system_key") == system_key
    ]
    machine_exceptions.extend(
        f"error:{item.get('record_id')}:{item.get('error_code')}"
        for item in evaluation_result.errors
        if item.get("system_key") == system_key
    )
    system_tree_diff = [item for item in evaluation_result.tree_diff if item.get("system_key") in {None, system_key}]
    return TaxonomyCalibrationPackage(
        schema_version=1,
        system_id=draft_manifest.system_id,
        system_key=system_key,
        draft_manifest_hash=manifest_hash(draft_manifest),
        evaluation_run_hash=evaluation_result.canonical_hash,
        dataset_hash=evaluation_result.dataset_hash,
        gold_hash=evaluation_result.gold_hash,
        prediction_hash=evaluation_result.prediction_hash,
        policy_hash=evaluation_result.policy_hash,
        frozen_policy_hash=evaluation_result.frozen_policy_hash,
        gate_hash=evaluation_result.gate_hash,
        gold_review_method="human_independent",
        calibration_gold_review_method="human_independent",
        gate_status="pass",
        review_scope="top_level_boundary_exception_sample",
        prepared_by=prepared_by,
        prepared_at=prepared_at,
        total_node_count=len(draft_manifest.nodes),
        top_level_nodes=[_node_summary(node) for node in roots],
        critical_boundaries=[_node_summary(node) for node in boundaries],
        exceptions=sorted({*exceptions, *machine_exceptions}),
        tree_diff=system_tree_diff,
        samples=focused_samples,
    )


def validate_calibration_review(
    *,
    draft_manifest: TaxonomyManifest,
    package: TaxonomyCalibrationPackage,
    review: TaxonomyCalibrationReview,
    activation_actor: str,
    activation_at: datetime | None = None,
) -> TaxonomyActivationAuthorization:
    return validate_calibration_review_binding(
        draft_system_id=draft_manifest.system_id,
        draft_manifest_hash=manifest_hash(draft_manifest),
        draft_created_by=draft_manifest.created_by,
        package=package,
        review=review,
        activation_actor=activation_actor,
        activation_at=activation_at,
    )


def validate_calibration_review_binding(
    *,
    draft_system_id: UUID,
    draft_manifest_hash: str,
    draft_created_by: str,
    package: TaxonomyCalibrationPackage,
    review: TaxonomyCalibrationReview,
    activation_actor: str,
    activation_at: datetime | None = None,
) -> TaxonomyActivationAuthorization:
    """校验存储层可验证的 hash/职责分离绑定，不依赖重建完整 manifest。"""

    draft_hash = draft_manifest_hash
    if package.system_id != draft_system_id:
        raise ValueError("calibration_review_system_id_mismatch")
    if package.draft_manifest_hash != draft_hash or review.draft_manifest_hash != draft_hash:
        raise ValueError("calibration_review_manifest_hash_mismatch")
    if review.package_hash != package.canonical_hash:
        raise ValueError("calibration_review_package_hash_mismatch")
    if review.evaluation_run_hash != package.evaluation_run_hash:
        raise ValueError("calibration_review_evaluation_hash_mismatch")
    if review.decision != "approved":
        raise ValueError("calibration_review_not_approved")
    if review.reviewer.casefold() != activation_actor.strip().casefold():
        raise ValueError("calibration_review_actor_mismatch")
    if review.reviewer.casefold() in {
        draft_created_by.casefold(),
        package.prepared_by.casefold(),
    }:
        raise ValueError("calibration_review_self_approval_forbidden")
    if review.reviewed_at < package.prepared_at:
        raise ValueError("calibration_review_precedes_package")
    effective_activation_at = activation_at or datetime.now(timezone.utc)
    if effective_activation_at.tzinfo is None or effective_activation_at.utcoffset() is None:
        raise ValueError("activation_time_timezone_required")
    if review.reviewed_at > effective_activation_at:
        raise ValueError("calibration_review_after_activation")
    return TaxonomyActivationAuthorization(
        activation_allowed=True,
        package_hash=package.canonical_hash,
        review_hash=review.canonical_hash,
        draft_manifest_hash=draft_hash,
        review_id=review.review_id,
        reviewer=review.reviewer,
        reviewed_at=review.reviewed_at,
        rollback_plan=review.rollback_plan,
    )
