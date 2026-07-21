"""受控管理系统级业务 taxonomy，所有写命令默认 dry-run。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.platform_api.core.database import get_session_factory  # noqa: E402
from src.platform_api.services.taxonomy_admin_service import (  # noqa: E402
    TaxonomyActivationResult,
    TaxonomyAdminError,
    TaxonomyAdminService,
    TaxonomyImportResult,
)
from src.testcase_generator.schemas.taxonomy_evaluation import (  # noqa: E402
    TaxonomyCalibrationPackage,
    TaxonomyCalibrationReview,
)
from src.testcase_generator.services.taxonomy_manifest import (  # noqa: E402
    load_manifest,
    manifest_hash,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="业务 taxonomy 管理工具（写操作默认 dry-run）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="仅校验 manifest，不连接数据库")
    validate.add_argument("manifest", type=Path)

    import_cmd = subparsers.add_parser("import", help="校验并导入 immutable draft version")
    import_cmd.add_argument("manifest", type=Path)
    import_cmd.add_argument("--actor", required=True)
    import_cmd.add_argument("--apply", action="store_true")

    activate = subparsers.add_parser("activate", help="激活指定 version，并退役旧 active version")
    activate.add_argument("--system-id", type=UUID, required=True)
    activate.add_argument("--version", type=int, required=True)
    activate.add_argument("--actor", required=True)
    activate.add_argument("--calibration-package", type=Path)
    activate.add_argument("--calibration-review", type=Path)
    activate.add_argument("--apply", action="store_true")
    return parser


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


async def _run_async(args: argparse.Namespace) -> int:
    if args.command == "validate":
        manifest = load_manifest(args.manifest)
        _print_json(
            {
                "valid": True,
                "manifest_hash": manifest_hash(manifest),
                "system_id": manifest.system_id,
                "version": manifest.version,
                "node_count": len(manifest.nodes),
                "mapping_count": len(manifest.mappings),
            }
        )
        return 0

    factory = get_session_factory()
    async with factory() as session:
        service = TaxonomyAdminService(session)
        result: TaxonomyImportResult | TaxonomyActivationResult
        if args.command == "import":
            result = await service.import_manifest(
                load_manifest(args.manifest),
                actor=args.actor,
                apply=args.apply,
            )
        else:
            calibration_package = (
                TaxonomyCalibrationPackage.model_validate_json(args.calibration_package.read_text(encoding="utf-8"))
                if args.calibration_package
                else None
            )
            calibration_review = (
                TaxonomyCalibrationReview.model_validate_json(args.calibration_review.read_text(encoding="utf-8"))
                if args.calibration_review
                else None
            )
            result = await service.activate(
                system_id=args.system_id,
                version=args.version,
                actor=args.actor,
                calibration_package=calibration_package,
                calibration_review=calibration_review,
                apply=args.apply,
            )
    _print_json(asdict(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return asyncio.run(_run_async(args))
    except (OSError, json.JSONDecodeError, ValidationError, TaxonomyAdminError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
