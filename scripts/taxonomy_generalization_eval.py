"""Taxonomy 跨 PRD pilot 评估；只读固定 artifact，绝不调用模型或写数据库。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.testcase_generator.schemas.taxonomy_evaluation import (  # noqa: E402
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
    TaxonomyFrozenPolicy,
    TaxonomyGoldSet,
    TaxonomyPredictionSet,
)
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy  # noqa: E402
from src.testcase_generator.services.taxonomy_evaluation import (  # noqa: E402
    RequirementUnitIndex,
    calibrate_resolution_policy,
    evaluate_taxonomy_generalization,
    load_evaluation_inputs,
    load_prediction_output_manifests,
    load_requirement_unit_index,
    resolve_evaluation_artifact_path,
    validate_evaluation_artifact_hashes,
    write_taxonomy_evaluation_artifacts,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Taxonomy 跨 PRD pilot 离线评估（默认 dry-run，不调用模型、不写数据库）"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="calibration 或历史 v1/v2 dataset；v3 locked-test 必须使用 taxonomy_pilot.py verify-locked-test",
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gate", type=Path)
    parser.add_argument(
        "--calibrate-dev",
        action="store_true",
        help="仅用 dev gold/预测冻结 score+margin policy；输入含任何 test 记录都会失败",
    )
    parser.add_argument("--minimum-precision", type=float, default=0.95)
    parser.add_argument("--minimum-auto-decisions", type=int, default=1)
    return parser


def _artifact_path(dataset_path: Path, value: str) -> Path:
    return resolve_evaluation_artifact_path(dataset_path, value)


def _load_calibration_inputs(
    dataset_path: Path,
) -> tuple[TaxonomyDatasetManifest, TaxonomyGoldSet, TaxonomyPredictionSet, RequirementUnitIndex]:
    dataset = TaxonomyDatasetManifest.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    validate_evaluation_artifact_hashes(
        dataset=dataset,
        manifest_path=dataset_path,
        document_splits={"dev"},
        include_transformations=False,
    )
    gold = TaxonomyGoldSet.model_validate_json(
        _artifact_path(dataset_path, dataset.gold_artifact.path).read_text(encoding="utf-8")
    )
    predictions = TaxonomyPredictionSet.model_validate_json(
        _artifact_path(dataset_path, dataset.prediction_artifact.path).read_text(encoding="utf-8")
    )
    load_prediction_output_manifests(
        dataset=dataset,
        dataset_path=dataset_path,
        predictions=predictions,
    )
    requirement_units = load_requirement_unit_index(
        dataset=dataset,
        manifest_path=dataset_path,
        document_splits={"dev"},
    )
    return dataset, gold, predictions, requirement_units


def _write_frozen_policy(output_dir: Path, policy: TaxonomyFrozenPolicy) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)
    try:
        path = output_dir / "frozen-policy.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(policy.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except BaseException:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.calibrate_dev:
            dataset, gold, predictions, requirement_units = _load_calibration_inputs(args.dataset)
            base_policy = TaxonomyResolutionPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
            frozen = calibrate_resolution_policy(
                dataset=dataset,
                gold=gold,
                predictions=predictions,
                requirement_units=requirement_units,
                base_policy=base_policy,
                calibrated_at=datetime.now(timezone.utc),
                minimum_precision=args.minimum_precision,
                minimum_auto_decisions=args.minimum_auto_decisions,
            )
            _write_frozen_policy(args.output, frozen)
            print(
                json.dumps(
                    {
                        "mode": "calibrate-dev",
                        "output": str(args.output / "frozen-policy.json"),
                        "policy_hash": frozen.policy_hash,
                        "frozen_policy_hash": frozen.canonical_hash,
                        "minimum_score": frozen.policy.minimum_score,
                        "minimum_margin": frozen.policy.minimum_margin,
                        "observed_precision": frozen.observed_precision,
                        "observed_auto_coverage": frozen.observed_auto_coverage,
                        "systems": {
                            item.system_key: {
                                "precision": item.precision,
                                "auto_coverage": item.auto_coverage,
                                "auto_decisions": item.auto_decision_count,
                                "eligible_auto_decisions": item.eligible_auto_decision_count,
                                "eligible": item.eligible_record_count,
                            }
                            for item in frozen.calibration_system_metrics
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        (
            dataset,
            gold,
            predictions,
            output_manifests,
            transformations,
            requirement_units,
            frozen_policy,
        ) = load_evaluation_inputs(dataset_path=args.dataset, policy_path=args.policy)
        gate = (
            TaxonomyEvaluationGate.model_validate_json(args.gate.read_text(encoding="utf-8"))
            if args.gate
            else TaxonomyEvaluationGate()
        )
        result = evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=gold,
            predictions=predictions,
            output_manifests=output_manifests,
            requirement_units=requirement_units,
            transformations=transformations,
            frozen_policy=frozen_policy,
            gate=gate,
        )
        write_taxonomy_evaluation_artifacts(
            output_dir=args.output,
            result=result,
            predictions=predictions,
        )
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "output": str(args.output),
                    "overall_status": result.overall_status,
                    "systems": {f"{item.system_key}/{item.split}": item.gate_status for item in result.system_results},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.overall_status == "pass" else 2
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
