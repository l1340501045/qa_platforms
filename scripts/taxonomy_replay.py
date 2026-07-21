"""历史批次 taxonomy 回放工具；默认 dry-run，写库需显式 --apply。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import TextIO
from uuid import UUID

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.platform_api.core.database import get_session_factory  # noqa: E402
from src.testcase_generator.services.taxonomy_manifest import (  # noqa: E402
    load_assignment_set,
    load_manifest,
    manifest_hash,
)
from src.testcase_generator.services.taxonomy_replay import (  # noqa: E402
    TaxonomyReplayError,
    TaxonomyReplayService,
)
from src.testcase_generator.services.taxonomy_replay_report import write_replay_artifacts  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="历史批次 taxonomy 回放（默认 dry-run）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("replay", help="生成 dry-run 报告或显式 apply")
    replay.add_argument("assignments", type=Path)
    replay.add_argument("--manifest", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path)
    replay.add_argument("--apply", action="store_true")
    replay.add_argument("--expected-baseline-hash")
    replay.add_argument("--expected-plan-hash")
    replay.add_argument("--expected-anomaly-case-ids", type=Path)
    replay.add_argument("--actor")

    rollback = subparsers.add_parser("rollback", help="按 backfill run 精确回滚 taxonomy 字段")
    rollback.add_argument("run_id", type=UUID)
    rollback.add_argument("--actor", required=True)
    return parser


async def _run_async(args: argparse.Namespace) -> int:
    factory = get_session_factory()
    async with factory() as session:
        service = TaxonomyReplayService(session)
        if args.command == "rollback":
            rollback_result = await service.rollback(args.run_id, actor=args.actor)
            _print_json(asdict(rollback_result))
            return 0

        assignments = load_assignment_set(args.assignments)
        manifest = load_manifest(args.manifest)
        digest = manifest_hash(manifest)
        if digest != assignments.manifest_hash:
            raise TaxonomyReplayError("assignment_manifest_hash_mismatch", "assignment 未绑定当前 manifest")
        if manifest.version != assignments.taxonomy_version:
            raise TaxonomyReplayError("assignment_manifest_version_mismatch", "taxonomy version 不一致")
        if args.apply and (not args.expected_baseline_hash or not args.expected_plan_hash or not args.actor):
            raise TaxonomyReplayError(
                "apply_confirmation_required",
                "--apply 必须同时提供 --expected-baseline-hash、--expected-plan-hash 和 --actor",
            )

        output_dir = args.output_dir
        if args.apply:
            output_dir = output_dir or (
                Path(".audit") / f"{assignments.batch_id}-taxonomy-replay" / f"apply-{args.expected_plan_hash[:16]}"
            )
            _preflight_apply_output(output_dir)
        expected_anomaly_case_ids = (
            _load_uuid_set(args.expected_anomaly_case_ids) if args.expected_anomaly_case_ids else None
        )

        replay_result = await service.replay(
            assignments,
            apply=args.apply,
            expected_baseline_hash=args.expected_baseline_hash,
            expected_plan_hash=args.expected_plan_hash,
            expected_legacy_anomaly_case_ids=expected_anomaly_case_ids,
            actor=args.actor,
        )
        output_dir = output_dir or (
            Path(".audit") / f"{assignments.batch_id}-taxonomy-replay" / f"dry-run-{replay_result.plan_hash[:16]}"
        )
        if replay_result.applied:
            _print_json(
                {
                    "status": "database_committed_artifacts_pending",
                    "run_id": replay_result.run_id,
                    "rollback_command": (
                        f"uv run python scripts/taxonomy_replay.py rollback {replay_result.run_id} --actor <name>"
                    ),
                },
                file=sys.stderr,
            )
        try:
            write_replay_artifacts(
                output_dir=output_dir,
                result=replay_result,
                assignments=assignments,
                manifest=manifest,
                replace_existing=not replay_result.applied,
                expected_anomaly_case_ids=expected_anomaly_case_ids,
            )
        except Exception as exc:
            if replay_result.applied:
                _print_json(
                    {
                        "status": "database_committed_artifact_write_failed",
                        "run_id": replay_result.run_id,
                        "artifact_error": str(exc),
                        "rollback_command": (
                            f"uv run python scripts/taxonomy_replay.py rollback {replay_result.run_id} --actor <name>"
                        ),
                    },
                    file=sys.stderr,
                )
                return 3
            raise
        _print_json(
            {
                "output_dir": str(output_dir),
                "applied": replay_result.applied,
                "run_id": replay_result.run_id,
                "source_scope": replay_result.source_scope,
                "baseline_hash": replay_result.baseline_hash,
                "plan_hash": replay_result.plan_hash,
                "overall_coverage": replay_result.overall_coverage,
                "main_coverage": replay_result.main_coverage,
                "unresolved_count": replay_result.unresolved_count,
            }
        )
        return 0


def _preflight_apply_output(output_dir: Path) -> None:
    if output_dir.exists():
        raise TaxonomyReplayError("apply_output_exists", f"apply 产物目录必须唯一且不存在：{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".taxonomy-replay-probe-", dir=output_dir.parent):
        pass


def _load_uuid_set(path: Path) -> frozenset[UUID]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TaxonomyReplayError("expected_anomaly_set_invalid", "冻结异常集合必须是 case UUID JSON 数组")
    try:
        case_ids = frozenset(UUID(str(value)) for value in payload)
    except ValueError as exc:
        raise TaxonomyReplayError("expected_anomaly_set_invalid", str(exc)) from exc
    if len(case_ids) != len(payload):
        raise TaxonomyReplayError("expected_anomaly_set_duplicate", "冻结异常集合包含重复 UUID")
    return case_ids


def _print_json(payload: object, *, file: TextIO | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), file=file)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run_async(args))
    except (OSError, json.JSONDecodeError, ValidationError, TaxonomyReplayError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
