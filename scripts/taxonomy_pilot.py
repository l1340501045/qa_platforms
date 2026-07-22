"""通用 Taxonomy 真实 pilot 受控运行器；默认不写数据库、不运行锁定测试预测。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import TypeAdapter, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient  # noqa: E402
from src.knowledge_base.services.parsers.markdown_parser import (  # noqa: E402
    MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
)
from src.platform_api.core.model_runtime import (  # noqa: E402
    ModelConfigBundle,
    ModelRole,
    build_environment_model_bundle,
    model_runtime_scope,
)
from src.platform_api.core.settings import settings  # noqa: E402
from src.testcase_generator.schemas.parsed_context import SourceItem  # noqa: E402
from src.testcase_generator.schemas.requirement_unit import RequirementUnit  # noqa: E402
from src.testcase_generator.schemas.taxonomy import TaxonomyManifest  # noqa: E402
from src.testcase_generator.schemas.taxonomy_evaluation import (  # noqa: E402
    ArtifactRef,
    RecordId,
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
    TaxonomyGoldRecord,
    TaxonomyGoldSet,
    TaxonomyPredictionSet,
    TaxonomyTransformationSet,
)
from src.testcase_generator.schemas.taxonomy_pilot import (  # noqa: E402
    PilotBootstrapIdentity,
    PilotConceptRefEntry,
    PilotConceptRefSet,
    PilotCorpusSpec,
    PilotCoverageGoldSet,
    PilotFrozenCorpus,
    PilotFrozenDocument,
    PilotGoldReviewAttestation,
    PilotLockedTestFailureReceipt,
    PilotLockedTestInputCommitment,
    PilotResolutionRecord,
    PilotResolutionSet,
    PilotSourceTransformationCommitment,
)
from src.testcase_generator.schemas.taxonomy_resolution import TaxonomyResolutionPolicy  # noqa: E402
from src.testcase_generator.services.llm_client import LLMClient, llm_stats  # noqa: E402
from src.testcase_generator.services.requirement_unit_service import (  # noqa: E402
    REQUIREMENT_UNIT_PROMPT_REVISION,
    REQUIREMENT_UNIT_VERIFIER_PROMPT_REVISION,
    RequirementUnitExtractionResult,
    RequirementUnitService,
    build_llm_requirement_unit_extractor,
    build_llm_requirement_unit_verifier,
)
from src.testcase_generator.services.taxonomy_bootstrap import (  # noqa: E402
    BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
    BOOTSTRAP_PROPOSAL_PROMPT_REVISION,
    TaxonomyBootstrapPolicy,
    TaxonomyBootstrapResult,
    TaxonomyBootstrapService,
    build_llm_taxonomy_bootstrap_binding,
)
from src.testcase_generator.services.taxonomy_candidate_retriever import (  # noqa: E402
    TAXONOMY_RETRIEVER_REVISION,
    TaxonomyCandidateRetriever,
    TaxonomySearchConcept,
)
from src.testcase_generator.services.taxonomy_evaluation import (  # noqa: E402
    evaluate_taxonomy_generalization,
    load_prediction_output_manifests,
    load_requirement_unit_index,
    render_taxonomy_evaluation_report,
    validate_evaluation_artifact_hashes,
)
from src.testcase_generator.services.taxonomy_evolution import (  # noqa: E402
    EVOLUTION_PROMPT_REVISION,
    TaxonomyEvolutionPolicy,
    TaxonomyEvolutionResult,
    TaxonomyEvolutionService,
    build_llm_taxonomy_evolution_binding,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash  # noqa: E402
from src.testcase_generator.services.taxonomy_pilot import (  # noqa: E402
    PILOT_TRANSFORMATION_PROJECTION_REVISION,
    PilotArtifactError,
    PilotRunLedger,
    PilotSourceCoverageError,
    VerifiedPilotBootstrap,
    build_evolution_draft_manifests,
    build_pilot_frozen_policy,
    build_provisional_bootstrap_gold,
    derive_locked_test_evidence,
    freeze_pilot_corpus,
    load_frozen_corpus,
    load_split_snapshots,
    pilot_record_id,
    project_resolution_predictions,
    render_locked_test_source_coverage_failure,
    reserve_locked_test,
    validate_pilot_locked_test_gate,
    verify_pilot_bootstrap_artifacts,
    verify_pilot_calibration_artifacts,
    verify_pilot_locked_test_artifacts,
    verify_pilot_locked_test_failure_artifacts,
    verify_pilot_policy_freeze_artifacts,
    verify_pilot_requirement_artifacts,
    write_json_atomic_once,
    write_json_once,
    write_text_once,
)
from src.testcase_generator.services.taxonomy_resolver import (  # noqa: E402
    TAXONOMY_RESOLVER_PROMPT_REVISION,
    TaxonomyResolver,
    build_llm_taxonomy_decider,
)
from src.testcase_generator.stages.parse.feature_segmenter import (  # noqa: E402
    SEG_SYSTEM_PROMPT,
    FeatureSegmentationError,
)
from src.testcase_generator.stages.parse.node import (  # noqa: E402
    TAXONOMY_SOURCE_INVENTORY_REVISION,
    extract_document_inventory_sections,
)
from src.testcase_generator.stages.parse.section_classifier import (  # noqa: E402
    CLASSIFY_SYSTEM_PROMPT,
    SectionClassificationError,
    classify_sections,
)

_RECORD_ID_ADAPTER = TypeAdapter(RecordId)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taxonomy pilot 受控运行器（离线、零数据库写入）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="冻结外部 PRD 快照，不调用模型")
    freeze.add_argument("--spec", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--actor", required=True)
    freeze.add_argument("--run-id", required=True)

    extract = subparsers.add_parser("extract-units", help="按固定 prompt 提取原子需求")
    extract.add_argument("--root", type=Path, required=True)
    extract.add_argument("--split", choices=("bootstrap", "calibration"), required=True)
    extract.add_argument("--actor", required=True)
    extract.add_argument("--run-id", required=True)
    bootstrap = subparsers.add_parser(
        "bootstrap-taxonomy",
        help="仅用 bootstrap split 生成 baseline draft 与预标审核包",
    )
    bootstrap.add_argument("--root", type=Path, required=True)
    bootstrap.add_argument("--actor", required=True)
    bootstrap.add_argument("--run-id", required=True)
    calibration = subparsers.add_parser(
        "resolve-calibration",
        help="仅用独立 calibration split 对 bootstrap taxonomy 生成原始决议与预标",
    )
    calibration.add_argument("--root", type=Path, required=True)
    calibration.add_argument("--actor", required=True)
    calibration.add_argument("--run-id", required=True)
    policy_freeze = subparsers.add_parser(
        "freeze-calibration-policy",
        help="用独立 calibration gold 冻结 score/margin 策略，不调用模型",
    )
    policy_freeze.add_argument("--root", type=Path, required=True)
    policy_freeze.add_argument("--independent-gold", type=Path, required=True)
    policy_freeze.add_argument("--coverage-gold", type=Path, required=True)
    policy_freeze.add_argument("--actor", required=True)
    policy_freeze.add_argument("--run-id", required=True)
    policy_freeze.add_argument("--minimum-precision", type=float, default=0.95)
    policy_freeze.add_argument("--minimum-auto-decisions", type=int, default=1)
    locked_test = subparsers.add_parser(
        "run-locked-test",
        help="一次性执行 test 提取、预测和评估；预约后失败也会消耗测试机会",
    )
    locked_test.add_argument("--root", type=Path, required=True)
    locked_test.add_argument("--source-gold", type=Path, required=True)
    locked_test.add_argument("--transformation-commitment", type=Path, required=True)
    locked_test.add_argument("--gate", type=Path, required=True)
    locked_test.add_argument("--actor", required=True)
    locked_test.add_argument("--run-id", required=True)
    verify_locked_test = subparsers.add_parser(
        "verify-locked-test",
        help="离线重放唯一 locked test 的输入承诺、机械投影、评估和终态回执",
    )
    verify_locked_test.add_argument("--root", type=Path, required=True)
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_revision(name: str, prompt: str) -> str:
    return f"{name}@{hashlib.sha256(prompt.encode('utf-8')).hexdigest()}"


def _model_revision(bundle: ModelConfigBundle, role: ModelRole) -> str:
    endpoint = bundle.for_role(role)
    endpoint_hash = hashlib.sha256((endpoint.base_url or "").encode("utf-8")).hexdigest()[:12]
    return f"{endpoint.model_name}@endpoint-{endpoint_hash}@config-{bundle.revision}"


def _source_revision() -> dict[str, object]:
    repository = Path(__file__).resolve().parent.parent
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PilotArtifactError("pilot_git_revision_unavailable") from exc
    return {"git_commit": commit, "worktree_dirty": bool(status.strip())}


def _runtime_manifest(bundle: ModelConfigBundle) -> dict[str, object]:
    return {
        "schema_version": 1,
        "bundle_revision": bundle.revision,
        "bundle_source": bundle.source,
        "source_revision": _source_revision(),
        "execution": {
            "llm_concurrency": settings.llm_concurrency,
            "requirement_unit_concurrency": min(4, settings.llm_concurrency),
            "llm_timeout_seconds": settings.llm_timeout,
            "llm_max_retries": settings.llm_max_retries,
            "llm_json_mode": settings.llm_json_mode,
        },
        "preprocessing": {
            "canonical_image_enrichment_revision": MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
            "feature_segmentation_enabled": settings.feature_seg_llm_enabled,
            "feature_segmentation_strict": True,
            "feature_segmentation_used_for_taxonomy": False,
            "feature_segmenter_prompt_revision": _prompt_revision("feature-segmenter", SEG_SYSTEM_PROMPT),
            "taxonomy_source_inventory_revision": TAXONOMY_SOURCE_INVENTORY_REVISION,
            "section_classification_strict": True,
            "section_classifier_prompt_revision": _prompt_revision("section-classifier", CLASSIFY_SYSTEM_PROMPT),
            "requirement_unit_prompt_revision": REQUIREMENT_UNIT_PROMPT_REVISION,
            "requirement_unit_verifier_prompt_revision": REQUIREMENT_UNIT_VERIFIER_PROMPT_REVISION,
        },
        "models": {
            role.value: {
                "model_name": bundle.for_role(role).model_name,
                "base_url_sha256": hashlib.sha256((bundle.for_role(role).base_url or "").encode("utf-8")).hexdigest(),
                "vector_dimension": bundle.for_role(role).vector_dimension,
                "source": bundle.for_role(role).source,
            }
            for role in ModelRole
        },
    }


def _pin_runtime(root: Path, bundle: ModelConfigBundle) -> None:
    path = root / "runtime" / "model-bundle.json"
    manifest = _runtime_manifest(bundle)
    source_revision = manifest.get("source_revision")
    if not isinstance(source_revision, dict) or source_revision.get("worktree_dirty") is not False:
        raise PilotArtifactError("pilot_worktree_dirty")
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise PilotArtifactError("pilot_model_bundle_changed")
        return
    try:
        write_json_atomic_once(path, manifest)
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise PilotArtifactError("pilot_model_bundle_changed") from None


def _telemetry(root: Path, run_id: str) -> None:
    write_json_once(
        root / "telemetry" / f"{run_id}.json",
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "call_count": len(llm_stats.calls),
            "calls": [asdict(call) for call in llm_stats.calls],
            "cost_usd": None,
            "cost_note": "当前网关客户端未返回可归因价格，不能把未知成本记录为 0。",
        },
    )


def _telemetry_if_missing(root: Path, run_id: str) -> None:
    if not (root / "telemetry" / f"{run_id}.json").exists():
        _telemetry(root, run_id)


def _strict_llm_telemetry_issues(calls: Sequence[object]) -> list[str]:
    return sorted(
        {
            f"{getattr(call, 'schema_name', 'unknown')}:{error}"
            for call in calls
            if (error := getattr(call, "error", None))
        }
    )


def _artifact(root: Path, path: Path) -> ArtifactRef:
    return ArtifactRef(path=str(path.relative_to(root)), sha256=_sha256_file(path))


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _copy_file_once(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as source_handle, target.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle)
        target_handle.flush()
        os.fsync(target_handle.fileno())


def _fsync_artifact_tree(root: Path) -> None:
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        _fsync_directory(directory)
    _fsync_directory(root.parent)


def _validated_record_id(value: str) -> str:
    return _RECORD_ID_ADAPTER.validate_python(value)


def _prepare_extraction_run(root: Path, run_id: str) -> Path:
    """每次尝试写入自己的不可变目录；只有台账 completed 事件能赋予权威性。"""

    run_id = _validated_record_id(run_id)
    run_root = root / "runs" / "requirement-extraction" / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise PilotArtifactError(f"pilot_requirement_run_already_exists:{run_id}") from exc
    return run_root


def _blocking_extraction_issue_codes(extraction: RequirementUnitExtractionResult) -> list[str]:
    blocking: set[str] = {
        issue.code
        for issue in extraction.issues
        if issue.code
        in {
            "extractor_failed",
            "duplicate_unit_payload_conflict",
            "source_quote_not_grounded",
            "semantic_evidence_not_entailed",
            "semantic_verifier_failed",
        }
    }
    if extraction.chunk_count and not extraction.units:
        blocking.add("empty_extraction")
    return sorted(blocking)


async def _extract_split_requirement_units(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    split: str,
    output_dir: Path,
    bundle: ModelConfigBundle,
    allow_locked_test: bool = False,
) -> tuple[dict[str, RequirementUnitExtractionResult], dict[str, dict[str, object]]]:
    selected = [item for item in corpus.documents if item.split == split]
    documents = {item.document_key: item for item in selected}
    client = LLMClient(bundle)
    extractor_binding = build_llm_requirement_unit_extractor(
        client.generate_structured,
        model_revision=_model_revision(bundle, ModelRole.PRIMARY),
    )
    verifier_binding = build_llm_requirement_unit_verifier(
        client.generate_structured,
        model_revision=_model_revision(bundle, ModelRole.VERIFY),
    )
    snapshots = load_split_snapshots(
        corpus=corpus,
        root=root,
        split=split,
        allow_locked_test=allow_locked_test,
    )
    summaries: dict[str, dict[str, object]] = {}
    extractions: dict[str, RequirementUnitExtractionResult] = {}
    blocking_documents: dict[str, list[str]] = {}
    with model_runtime_scope(bundle):
        for document_key, snapshot in snapshots.items():
            document = documents[document_key]
            sections = extract_document_inventory_sections(
                document_id=document.document_id,
                title=document.title,
                content=snapshot,
                doc_type="prd",
            )
            source = SourceItem(
                doc_id=document.document_id,
                doc_type="prd",
                trust_level=1,
                title=document.title,
                sections=sections,
            )
            await classify_sections([source], strict=True)
            extraction = await RequirementUnitService(
                concurrency=min(4, settings.llm_concurrency),
                eligible_section_kinds=frozenset({"spec", "summary", "flow", "mock", "future", "tbd"}),
            ).extract(
                system_id=document.system_id,
                document_id=document.document_id,
                document_content_hash=document.source.sha256,
                document_snapshot=snapshot,
                sections=source.sections,
                extractor=extractor_binding.extractor,
                prompt_revision=extractor_binding.prompt_revision,
                model_revision=extractor_binding.model_revision,
                verifier=verifier_binding.verifier,
                verifier_prompt_revision=verifier_binding.prompt_revision,
                verifier_model_revision=verifier_binding.model_revision,
            )
            target = output_dir / f"{document_key}.json"
            write_json_once(target, extraction)
            extractions[document_key] = extraction
            summaries[document_key] = {
                "artifact": _artifact(root, target).model_dump(mode="json"),
                "section_count": len(source.sections),
                "chunk_count": extraction.chunk_count,
                "unit_count": len(extraction.units),
                "atomic_count": sum(unit.scope_status == "atomic" for unit in extraction.units),
                "issue_count": len(extraction.issues),
            }
            blocking_codes = _blocking_extraction_issue_codes(extraction)
            if blocking_codes:
                blocking_documents[document_key] = blocking_codes
    if blocking_documents:
        raise PilotArtifactError(
            "pilot_requirement_extraction_incomplete:"
            + json.dumps(blocking_documents, ensure_ascii=False, sort_keys=True)
        )
    return extractions, summaries


async def _extract_units(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    selected = [item for item in corpus.documents if item.split == args.split]
    run_id = _validated_record_id(args.run_id)

    bundle = build_environment_model_bundle(settings)
    _pin_runtime(root, bundle)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id=run_id,
        actor=args.actor,
        payload={
            "split": args.split,
            "document_keys": [item.document_key for item in selected],
        },
    )
    llm_stats.calls.clear()
    try:
        run_root = _prepare_extraction_run(root, run_id)
        _, summaries = await _extract_split_requirement_units(
            root=root,
            corpus=corpus,
            split=args.split,
            output_dir=run_root,
            bundle=bundle,
        )
        _telemetry_if_missing(root, run_id)
        degraded_calls = _strict_llm_telemetry_issues(llm_stats.calls)
        if degraded_calls:
            raise PilotArtifactError("pilot_degraded_llm_output:" + json.dumps(degraded_calls, ensure_ascii=False))
        _fsync_artifact_tree(run_root)
        ledger.append(
            event_type="requirement_extraction_completed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={"schema_version": 1, "split": args.split, "documents": summaries},
        )
        return {"split": args.split, "documents": summaries}
    except Exception as exc:
        _telemetry_if_missing(root, run_id)
        ledger.append(
            event_type="requirement_extraction_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={"split": args.split, "error_type": type(exc).__name__},
        )
        raise


def _load_bootstrap_extractions(
    root: Path,
    corpus: PilotFrozenCorpus,
) -> tuple[dict[str, RequirementUnitExtractionResult], dict[str, Path]]:
    paths = verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"bootstrap"})
    extractions: dict[str, RequirementUnitExtractionResult] = {}
    for document in (item for item in corpus.documents if item.split == "bootstrap"):
        path = paths[document.document_key]
        extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        if extraction.document_id != document.document_id:
            raise PilotArtifactError(f"pilot_requirement_document_mismatch:{document.document_key}")
        if extraction.document_content_hash != document.source.sha256:
            raise PilotArtifactError(f"pilot_requirement_hash_mismatch:{document.document_key}")
        extractions[document.document_key] = extraction
    return extractions, paths


def _bootstrap_identity(
    *,
    root: Path,
    corpus: PilotFrozenCorpus,
    extraction_paths: dict[str, Path],
    bundle: ModelConfigBundle,
    bootstrap_policy: TaxonomyBootstrapPolicy,
    resolution_policy: TaxonomyResolutionPolicy,
) -> PilotBootstrapIdentity:
    """仅绑定 bootstrap 输入；它不是 calibration/test dataset。"""

    runtime_manifest_path = root / "runtime" / "model-bundle.json"
    if not runtime_manifest_path.is_file():
        raise PilotArtifactError("pilot_runtime_manifest_missing")
    payload: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "bootstrap_identity",
        "corpus_id": corpus.corpus_id,
        "source_commitment_hash": corpus.source_commitment_hash,
        "bootstrap_policy_hash": bootstrap_policy.canonical_hash,
        "resolution_policy_hash": resolution_policy.canonical_hash,
        "runtime_manifest": _artifact(root, runtime_manifest_path).model_dump(mode="json"),
        "documents": [
            {
                "document_key": document.document_key,
                "document_id": str(document.document_id),
                "system_key": document.system_key,
                "system_id": str(document.system_id),
                "source": document.source.model_dump(mode="json"),
                "requirement_units": _artifact(
                    root,
                    extraction_paths[document.document_key],
                ).model_dump(mode="json"),
            }
            for document in sorted(corpus.documents, key=lambda item: item.document_key)
            if document.split == "bootstrap"
        ],
        "prompt_revisions": {
            "taxonomy_source_inventory": TAXONOMY_SOURCE_INVENTORY_REVISION,
            "section_classifier": _prompt_revision("section-classifier", CLASSIFY_SYSTEM_PROMPT),
            "pilot_preprocessing_policy": "semantic-feature-and-section-strict@1",
            "requirement_unit": REQUIREMENT_UNIT_PROMPT_REVISION,
            "bootstrap_proposal": BOOTSTRAP_PROPOSAL_PROMPT_REVISION,
            "bootstrap_consolidation": BOOTSTRAP_CONSOLIDATION_PROMPT_REVISION,
        },
        "model_revisions": {
            "primary": _model_revision(bundle, ModelRole.PRIMARY),
            "verify": _model_revision(bundle, ModelRole.VERIFY),
            "embedding": _model_revision(bundle, ModelRole.EMBEDDING),
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PilotBootstrapIdentity.model_validate(
        {**payload, "bootstrap_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    )


def _review_report(
    *,
    bootstrap_hash: str,
    results: dict[str, TaxonomyBootstrapResult],
) -> str:
    lines = [
        "# Dev Bootstrap 聚焦审核包",
        "",
        "> 状态：模型辅助预标，不是独立人工 gold，不允许解锁 test prediction 或激活 taxonomy。",
        "",
        f"- Bootstrap identity hash: `{bootstrap_hash}`",
        "- 该 hash 只绑定 bootstrap 输入，不是 calibration/test dataset hash。",
        "- 审核范围：顶层结构、关键边界、异常项、确定性抽样；完整 unit 预标在 `dev-gold-provisional.json`。",
        "- 业务判断：这里审核的是系统自动产出的目录草案，不要求逐条手工建立 mapping。",
    ]
    boundary_markers = ("不包含", "不含", "仅", "除外", "不支持", "不负责")
    for system_key, result in sorted(results.items()):
        lines.extend(["", f"## {system_key}"])
        manifest = result.draft_manifest
        if manifest is None:
            lines.extend(
                [
                    "",
                    "- 结果：未形成可审草案",
                    f"- Issues: `{', '.join(result.issue_codes) or 'none'}`",
                    f"- Unresolved units: `{len(result.unresolved_requirement_unit_ids)}`",
                ]
            )
            continue
        top_level = sorted(
            (node for node in manifest.nodes if node.parent_stable_key is None),
            key=lambda node: node.stable_key,
        )
        boundaries = sorted(
            (
                node
                for node in manifest.nodes
                if any(marker in (node.scope_note or "") for marker in boundary_markers) or node.out_of_scope_examples
            ),
            key=lambda node: node.stable_key,
        )
        samples = sorted(manifest.nodes, key=lambda node: node.stable_key)[:10]
        lines.extend(
            [
                "",
                (
                    f"- 节点：`{len(manifest.nodes)}`；已归属 unit：`{len(result.assignments)}`；"
                    f"未决：`{len(result.unresolved_requirement_unit_ids)}`"
                ),
                f"- Manifest hash: `{result.draft_manifest_hash}`",
                f"- Issues: `{', '.join(result.issue_codes) or 'none'}`",
                "",
                "### 顶层结构",
                *[f"- `{node.stable_key}` {node.display_name}：{node.definition}" for node in top_level],
                "",
                "### 关键边界",
                *(
                    [f"- `{node.stable_key}` {node.display_name}：{node.scope_note}" for node in boundaries]
                    or ["- 未发现显式正反边界，需重点确认 scope 是否过宽。"]
                ),
                "",
                "### 确定性抽样",
                *[f"- `{node.stable_key}` {node.display_name}（{node.node_type}）" for node in samples],
            ]
        )
    lines.extend(
        [
            "",
            "## 放行条件",
            "",
            "1. 先修正目录边界和明显错误预标。",
            "2. 独立人工确认完整 dev gold 后，才能做 score/margin 校准。",
            "3. Frozen policy 形成前，不得运行 locked test prediction。",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_bootstrap_results_for_completion(results: dict[str, TaxonomyBootstrapResult]) -> None:
    """只有形成可审 manifest 的每系统结果才能记为 bootstrap completed。"""

    if not results:
        raise PilotArtifactError("pilot_taxonomy_bootstrap_empty")
    for system_key, result in sorted(results.items()):
        if result.draft_manifest is None or result.draft_manifest_hash is None:
            raise PilotArtifactError(f"pilot_taxonomy_bootstrap_incomplete:{system_key}")


async def _bootstrap_taxonomy(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    extractions, extraction_paths = _load_bootstrap_extractions(root, corpus)
    bundle = build_environment_model_bundle(settings)
    _pin_runtime(root, bundle)
    run_id = _validated_record_id(args.run_id)
    run_root = root / "runs" / "taxonomy-bootstrap" / run_id
    if run_root.exists():
        raise PilotArtifactError(f"pilot_taxonomy_bootstrap_run_already_exists:{run_id}")
    target_dir = run_root / "raw"

    bootstrap_policy = TaxonomyBootstrapPolicy(
        schema_version=1,
        max_units_per_batch=20,
        max_batch_chars=60_000,
        max_consolidation_chars=100_000,
        max_nodes=1_000,
        fail_behavior="draft_only",
    )
    base_policy = TaxonomyResolutionPolicy(
        schema_version=1,
        top_k=5,
        minimum_score=0,
        minimum_margin=0,
        out_of_scope_conflict_score=0.85,
        decision_context_max_chars=20_000,
        require_grounding=True,
        allowed_node_types=("module", "capability"),
        allowed_node_statuses=("active",),
        model_role="taxonomy_resolver",
        model_revision=_model_revision(bundle, ModelRole.VERIFY),
        fail_behavior="abstain",
        auto_accept_signal="retrieval_score_margin",
    )
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="taxonomy_bootstrap_started",
        corpus=corpus,
        run_id=run_id,
        actor=args.actor,
        payload={"systems": sorted({item.system_key for item in corpus.documents if item.split == "bootstrap"})},
    )
    llm_stats.calls.clear()
    results: dict[str, TaxonomyBootstrapResult] = {}
    try:
        write_json_once(run_root / "policies" / "bootstrap-policy.json", bootstrap_policy)
        write_json_once(run_root / "policies" / "base-resolution-policy.json", base_policy)
        client = LLMClient(bundle)
        binding = build_llm_taxonomy_bootstrap_binding(
            client.generate_structured,
            proposal_model_revision=_model_revision(bundle, ModelRole.PRIMARY),
            consolidation_model_revision=_model_revision(bundle, ModelRole.VERIFY),
        )
        with model_runtime_scope(bundle):
            for system_key in sorted({item.system_key for item in corpus.documents if item.split == "bootstrap"}):
                documents = [
                    item for item in corpus.documents if item.split == "bootstrap" and item.system_key == system_key
                ]
                units = [unit for document in documents for unit in extractions[document.document_key].units]
                result = await TaxonomyBootstrapService(policy=bootstrap_policy).bootstrap(
                    system_id=documents[0].system_id,
                    version=1,
                    change_note=f"{corpus.corpus_id} bootstrap baseline",
                    created_by=args.actor,
                    requirement_units=units,
                    model_binding=binding,
                )
                results[system_key] = result
                write_json_once(target_dir / f"{system_key}.json", result)
                if result.draft_manifest is not None:
                    write_json_once(run_root / "manifests" / f"{system_key}.json", result.draft_manifest)

        _validate_bootstrap_results_for_completion(results)
        identity = _bootstrap_identity(
            root=root,
            corpus=corpus,
            extraction_paths=extraction_paths,
            bundle=bundle,
            bootstrap_policy=bootstrap_policy,
            resolution_policy=base_policy,
        )
        bootstrap_hash = identity.bootstrap_hash
        write_json_once(run_root / "artifacts" / "bootstrap-identity.json", identity)
        documents_by_key = {item.document_key: item for item in corpus.documents}
        gold = build_provisional_bootstrap_gold(
            corpus_id=corpus.corpus_id,
            dataset_hash=bootstrap_hash,
            bootstrap_results=results,
            requirement_units=extractions,
            documents=documents_by_key,
            reviewed_by=f"bootstrap-derived:{args.actor}",
            reviewed_at=datetime.now(timezone.utc),
        )
        gold_path = run_root / "reviews" / "dev-gold-provisional.json"
        write_json_once(gold_path, gold)
        write_text_once(
            run_root / "reviews" / "BOOTSTRAP-REVIEW.md",
            _review_report(bootstrap_hash=bootstrap_hash, results=results),
        )
        _telemetry_if_missing(root, run_id)
        _fsync_artifact_tree(run_root)
        summaries = {
            system_key: {
                "manifest_hash": result.draft_manifest_hash,
                "node_count": len(result.draft_manifest.nodes) if result.draft_manifest else 0,
                "assignment_count": len(result.assignments),
                "unresolved_count": len(result.unresolved_requirement_unit_ids),
                "issue_codes": result.issue_codes,
            }
            for system_key, result in results.items()
        }
        ledger.append(
            event_type="taxonomy_bootstrap_completed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={
                "schema_version": 1,
                "bootstrap_hash": bootstrap_hash,
                "identity": _artifact(root, run_root / "artifacts" / "bootstrap-identity.json").model_dump(mode="json"),
                "provisional_gold": _artifact(root, gold_path).model_dump(mode="json"),
                "review_report": _artifact(root, run_root / "reviews" / "BOOTSTRAP-REVIEW.md").model_dump(mode="json"),
                "results": {
                    system_key: _artifact(root, target_dir / f"{system_key}.json").model_dump(mode="json")
                    for system_key in sorted(results)
                },
                "output_manifests": {
                    system_key: _artifact(root, run_root / "manifests" / f"{system_key}.json").model_dump(mode="json")
                    for system_key in sorted(results)
                },
                "output_manifest_hashes": {
                    system_key: str(result.draft_manifest_hash) for system_key, result in sorted(results.items())
                },
            },
        )
        return {
            "bootstrap_hash": bootstrap_hash,
            "gold_review_method": gold.review_method,
            "artifact_root": str(run_root.relative_to(root)),
            "systems": summaries,
        }
    except Exception as exc:
        _telemetry_if_missing(root, run_id)
        ledger.append(
            event_type="taxonomy_bootstrap_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={"error_type": type(exc).__name__},
        )
        raise


def _pilot_uuid(corpus: PilotFrozenCorpus, system_key: str, kind: str, value: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"taxonomy-pilot:{corpus.source_commitment_hash}:{system_key}:{kind}:{value}",
    )


def _calibration_taxonomy_context(
    *,
    corpus: PilotFrozenCorpus,
    system_key: str,
    manifest: TaxonomyManifest,
) -> tuple[UUID, list[TaxonomySearchConcept], list[PilotConceptRefEntry]]:
    if manifest.schema_version != 2:
        raise PilotArtifactError(f"pilot_calibration_manifest_v2_required:{system_key}")
    taxonomy_version_id = _pilot_uuid(
        corpus,
        system_key,
        "taxonomy-version",
        manifest_hash(manifest),
    )
    concepts: list[TaxonomySearchConcept] = []
    references: list[PilotConceptRefEntry] = []
    for node in sorted(manifest.nodes, key=lambda item: item.stable_key):
        if node.definition is None or node.scope_note is None:
            raise PilotArtifactError(f"pilot_calibration_manifest_semantics_missing:{system_key}:{node.stable_key}")
        concept_id = _pilot_uuid(corpus, system_key, "concept", node.stable_key)
        concepts.append(
            TaxonomySearchConcept(
                taxonomy_version_id=taxonomy_version_id,
                concept_id=concept_id,
                stable_key=node.stable_key,
                node_type=node.node_type,
                node_status=node.node_status,
                display_name=node.display_name,
                aliases=node.aliases,
                definition=node.definition,
                scope_note=node.scope_note,
                in_scope_examples=node.in_scope_examples or [],
                out_of_scope_examples=node.out_of_scope_examples or [],
            )
        )
        references.append(
            PilotConceptRefEntry(
                concept_id=concept_id,
                system_key=system_key,
                stable_key=node.stable_key,
            )
        )
    return taxonomy_version_id, concepts, references


async def _resolve_split_units(
    *,
    corpus: PilotFrozenCorpus,
    bootstrap: VerifiedPilotBootstrap,
    documents: Sequence[PilotFrozenDocument],
    extractions: dict[str, RequirementUnitExtractionResult],
    bundle: ModelConfigBundle,
    policy: TaxonomyResolutionPolicy,
    dataset_hash: str,
    run_id: str,
    split: str,
    prompt_revisions: dict[str, str],
    model_revisions: dict[str, str],
    frozen_policy_hash: str | None = None,
) -> tuple[PilotResolutionSet, PilotConceptRefSet, TaxonomyPredictionSet]:
    embedding_client = EmbeddingClient(bundle)
    retriever = TaxonomyCandidateRetriever(
        embed_batch=embedding_client.embed_batch,
        embedding_revision=_model_revision(bundle, ModelRole.EMBEDDING),
    )
    llm_client = LLMClient(bundle)
    decider_binding = build_llm_taxonomy_decider(
        llm_client.generate_structured,
        model_revision=_model_revision(bundle, ModelRole.VERIFY),
    )
    taxonomy_version_ids: dict[str, UUID] = {}
    concept_entries: list[PilotConceptRefEntry] = []
    resolvers: dict[str, TaxonomyResolver] = {}
    concepts_by_system: dict[str, list[TaxonomySearchConcept]] = {}
    with model_runtime_scope(bundle):
        for system_key, manifest in sorted(bootstrap.manifests.items()):
            taxonomy_version_id, concepts, references = _calibration_taxonomy_context(
                corpus=corpus,
                system_key=system_key,
                manifest=manifest,
            )
            index = await retriever.build_index(
                taxonomy_version_id=taxonomy_version_id,
                taxonomy_manifest_hash=manifest_hash(manifest),
                concepts=concepts,
                policy=policy,
            )
            taxonomy_version_ids[system_key] = taxonomy_version_id
            concepts_by_system[system_key] = concepts
            concept_entries.extend(references)
            resolvers[system_key] = TaxonomyResolver(
                candidate_source=retriever.bind(index=index, policy=policy),
                decider_binding=decider_binding,
            )

        records: list[PilotResolutionRecord] = []
        for document in documents:
            resolver = resolvers[document.system_key]
            manifest = bootstrap.manifests[document.system_key]
            for unit in extractions[document.document_key].units:
                started_at = monotonic()
                resolution = await resolver.resolve(
                    unit,
                    taxonomy_version_id=taxonomy_version_ids[document.system_key],
                    taxonomy_manifest_hash=manifest_hash(manifest),
                    concepts=concepts_by_system[document.system_key],
                    policy=policy,
                )
                records.append(
                    PilotResolutionRecord(
                        document_key=document.document_key,
                        system_key=document.system_key,
                        split=split,
                        requirement_unit_id=unit.unit_id,
                        latency_ms=max(0, round((monotonic() - started_at) * 1000)),
                        cost_usd=None,
                        resolution=resolution,
                    )
                )
    resolutions = PilotResolutionSet(
        schema_version=1,
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        dataset_hash=dataset_hash,
        policy_hash=policy.canonical_hash,
        frozen_policy_hash=frozen_policy_hash,
        prompt_revisions=prompt_revisions,
        model_revisions=model_revisions,
        taxonomy_version_ids=taxonomy_version_ids,
        output_manifest_hashes=bootstrap.receipt.output_manifest_hashes,
        records=records,
    )
    concept_ref_set = PilotConceptRefSet(schema_version=1, records=concept_entries)
    predictions = project_resolution_predictions(
        resolutions=resolutions,
        concept_refs=concept_ref_set.by_concept_id,
        manifests=bootstrap.manifests,
        manifest_artifacts=bootstrap.receipt.output_manifests,
    )
    return resolutions, concept_ref_set, predictions


async def _evolve_locked_test_novel_units(
    *,
    bootstrap: VerifiedPilotBootstrap,
    extractions: dict[str, RequirementUnitExtractionResult],
    resolutions: PilotResolutionSet,
    bundle: ModelConfigBundle,
    policy: TaxonomyEvolutionPolicy,
) -> dict[str, TaxonomyEvolutionResult]:
    """只把 resolver 明确拒识为 novel 的 unit 送入 draft-only evolve。"""

    units_by_id = {unit.unit_id: unit for extraction in extractions.values() for unit in extraction.units}
    if len(units_by_id) != sum(len(extraction.units) for extraction in extractions.values()):
        raise PilotArtifactError("pilot_locked_test_requirement_unit_duplicate")
    novel_units_by_system: dict[str, list[RequirementUnit]] = {system_key: [] for system_key in bootstrap.manifests}
    for record in resolutions.records:
        if record.resolution.status != "unresolved" or record.resolution.unresolved_kind != "novel":
            continue
        unit = units_by_id.get(record.requirement_unit_id)
        if unit is None or unit.system_id != bootstrap.manifests[record.system_key].system_id:
            raise PilotArtifactError(f"pilot_evolution_requirement_unit_unknown:{record.requirement_unit_id}")
        novel_units_by_system[record.system_key].append(unit)

    llm_client = LLMClient(bundle)
    model_binding = build_llm_taxonomy_evolution_binding(
        llm_client.generate_structured,
        model_revision=_model_revision(bundle, ModelRole.VERIFY),
    )
    service = TaxonomyEvolutionService(policy=policy)
    results: dict[str, TaxonomyEvolutionResult] = {}
    with model_runtime_scope(bundle):
        for system_key, manifest in sorted(bootstrap.manifests.items()):
            results[system_key] = await service.evolve(
                active_manifest=manifest,
                requirement_units=sorted(
                    novel_units_by_system[system_key],
                    key=lambda item: item.unit_id,
                ),
                model_binding=model_binding,
                impact_snapshot={},
            )
    return results


def _locked_test_evolution_policy() -> TaxonomyEvolutionPolicy:
    return TaxonomyEvolutionPolicy(
        schema_version=1,
        max_context_chars=100_000,
        max_operations=1_000,
        fail_behavior="draft_only",
    )


def _json_artifact_sha256(value: object) -> str:
    payload = (
        value.model_dump_json(indent=2)
        if hasattr(value, "model_dump_json")
        else json.dumps(value, ensure_ascii=False, indent=2, default=str)
    )
    return hashlib.sha256(f"{payload}\n".encode("utf-8")).hexdigest()


def _build_calibration_provisional_gold(
    *,
    corpus: PilotFrozenCorpus,
    dataset_hash: str,
    predictions: TaxonomyPredictionSet,
    extractions: dict[str, RequirementUnitExtractionResult],
    reviewed_by: str,
    reviewed_at: datetime,
) -> TaxonomyGoldSet:
    prediction_by_unit = {(item.document_key, item.requirement_unit_id): item for item in predictions.records}
    documents = {item.document_key: item for item in corpus.documents if item.split == "calibration"}
    records: list[TaxonomyGoldRecord] = []
    for document_key, extraction in sorted(extractions.items()):
        document = documents[document_key]
        for unit in extraction.units:
            prediction = prediction_by_unit.get((document_key, unit.unit_id))
            if prediction is None:
                raise PilotArtifactError(f"pilot_calibration_prediction_missing:{unit.unit_id}")
            common: dict[str, object] = {
                "record_id": pilot_record_id(document_key, unit.unit_id),
                "document_key": document_key,
                "system_key": document.system_key,
                "split": "dev",
                "requirement_unit_id": unit.unit_id,
                "gold_evidence": [unit.source_ref],
                "eligible_for_auto": unit.scope_status == "atomic",
            }
            if prediction.outcome in {"candidate", "approved_mapping"}:
                records.append(
                    TaxonomyGoldRecord(
                        **common,
                        expected_disposition="reuse",
                        expected_primary_stable_key=prediction.predicted_primary_stable_key,
                        expected_related_stable_keys=prediction.predicted_related_stable_keys,
                        expected_path=prediction.predicted_path,
                    )
                )
            else:
                records.append(
                    TaxonomyGoldRecord(
                        **common,
                        expected_disposition="abstain",
                    )
                )
    if not records:
        raise PilotArtifactError("pilot_calibration_gold_empty")
    return TaxonomyGoldSet(
        schema_version=1,
        corpus_id=corpus.corpus_id,
        dataset_hash=dataset_hash,
        review_method="model_assisted_provisional",
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        records=records,
    )


async def _resolve_calibration(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    requirement_paths = verify_pilot_requirement_artifacts(
        root=root,
        corpus=corpus,
        splits={"calibration"},
    )
    extractions = {
        document_key: RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        for document_key, path in requirement_paths.items()
    }
    bundle = build_environment_model_bundle(settings)
    _pin_runtime(root, bundle)
    run_id = _validated_record_id(args.run_id)
    run_root = root / "runs" / "calibration-resolution" / run_id
    dataset_path = root / f"calibration-dataset-{run_id}.json"
    if run_root.exists() or dataset_path.exists():
        raise PilotArtifactError(f"pilot_calibration_run_already_exists:{run_id}")

    base_policy_path = (
        root / "runs" / "taxonomy-bootstrap" / bootstrap.event.run_id / "policies" / "base-resolution-policy.json"
    )
    try:
        base_policy = TaxonomyResolutionPolicy.model_validate_json(base_policy_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - calibration 只能复用 bootstrap 固定策略
        raise PilotArtifactError("pilot_calibration_base_policy_invalid") from exc

    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="calibration_resolution_started",
        corpus=corpus,
        run_id=run_id,
        actor=args.actor,
        payload={
            "bootstrap_event_hash": bootstrap.event.event_hash,
            "systems": sorted(bootstrap.manifests),
        },
    )
    llm_stats.calls.clear()
    try:
        write_json_once(run_root / "policies" / "base-resolution-policy.json", base_policy)
        transformation_set = TaxonomyTransformationSet(
            schema_version=1,
            corpus_id=corpus.corpus_id,
            records=[],
        )
        transformation_path = run_root / "evaluation" / "transformations.json"
        write_json_once(transformation_path, transformation_set)

        output_manifests = bootstrap.receipt.output_manifests
        output_manifest_hashes = bootstrap.receipt.output_manifest_hashes
        runtime_path = root / "runtime" / "model-bundle.json"
        calibration_documents = sorted(
            (item for item in corpus.documents if item.split == "calibration"),
            key=lambda item: item.document_key,
        )
        dataset_seed = TaxonomyDatasetManifest(
            schema_version=2,
            corpus_id=corpus.corpus_id,
            pilot_corpus=True,
            split_strategy="document_level",
            test_locked=True,
            evaluation_split="dev",
            source_commitment_hash=corpus.source_commitment_hash,
            upstream_artifact_hashes={
                "bootstrap_event": bootstrap.event.event_hash,
                "bootstrap_identity": bootstrap.receipt.bootstrap_hash,
                "runtime_manifest": _sha256_file(runtime_path),
                **{
                    f"output_manifest.{system_key}": value
                    for system_key, value in sorted(output_manifest_hashes.items())
                },
            },
            created_at=corpus.frozen_at,
            documents=[
                {
                    "document_key": document.document_key,
                    "document_id": document.document_id,
                    "system_key": document.system_key,
                    "system_id": document.system_id,
                    "split": "dev",
                    "source": document.source,
                    "requirement_units": _artifact(root, requirement_paths[document.document_key]),
                }
                for document in calibration_documents
            ],
            gold_artifact={
                "path": str((run_root / "reviews" / "calibration-gold-provisional.json").relative_to(root)),
                "sha256": "0" * 64,
            },
            prediction_artifact={
                "path": str((run_root / "predictions" / "predictions.json").relative_to(root)),
                "sha256": "0" * 64,
            },
            transformation_artifact=_artifact(root, transformation_path),
            prompt_revisions={
                "candidate_retriever": TAXONOMY_RETRIEVER_REVISION,
                "taxonomy_resolver": TAXONOMY_RESOLVER_PROMPT_REVISION,
            },
            model_revisions={
                "embedding": _model_revision(bundle, ModelRole.EMBEDDING),
                "taxonomy_resolver": _model_revision(bundle, ModelRole.VERIFY),
            },
        )
        dataset_hash = dataset_seed.dataset_hash

        resolutions, concept_ref_set, predictions = await _resolve_split_units(
            corpus=corpus,
            bootstrap=bootstrap,
            documents=calibration_documents,
            extractions=extractions,
            bundle=bundle,
            policy=base_policy,
            dataset_hash=dataset_hash,
            run_id=run_id,
            split="dev",
            prompt_revisions=dataset_seed.prompt_revisions,
            model_revisions=dataset_seed.model_revisions,
        )
        generated_at = resolutions.generated_at
        provisional_gold = _build_calibration_provisional_gold(
            corpus=corpus,
            dataset_hash=dataset_hash,
            predictions=predictions,
            extractions=extractions,
            reviewed_by=f"calibration-derived:{args.actor}",
            reviewed_at=generated_at,
        )

        resolution_path = run_root / "raw" / "resolutions.json"
        concept_ref_path = run_root / "artifacts" / "concept-refs.json"
        prediction_path = run_root / "predictions" / "predictions.json"
        provisional_gold_path = run_root / "reviews" / "calibration-gold-provisional.json"
        write_json_once(resolution_path, resolutions)
        write_json_once(concept_ref_path, concept_ref_set)
        write_json_once(prediction_path, predictions)
        write_json_once(provisional_gold_path, provisional_gold)

        dataset_payload = dataset_seed.model_dump(mode="json")
        dataset_payload["gold_artifact"] = _artifact(root, provisional_gold_path).model_dump(mode="json")
        dataset_payload["prediction_artifact"] = _artifact(root, prediction_path).model_dump(mode="json")
        dataset = TaxonomyDatasetManifest.model_validate(dataset_payload)
        if dataset.dataset_hash != dataset_hash:
            raise PilotArtifactError("pilot_calibration_dataset_hash_drift")
        write_json_atomic_once(dataset_path, dataset)

        degraded_calls = _strict_llm_telemetry_issues(llm_stats.calls)
        if degraded_calls:
            raise PilotArtifactError("pilot_degraded_llm_output:" + json.dumps(degraded_calls, ensure_ascii=False))
        validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=dataset_path)
        load_requirement_unit_index(dataset=dataset, manifest_path=dataset_path, document_splits={"dev"})
        loaded_manifests = load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=dataset_path,
            predictions=predictions,
        )
        if loaded_manifests != bootstrap.manifests:
            raise PilotArtifactError("pilot_calibration_manifest_binding_invalid")

        _telemetry_if_missing(root, run_id)
        _fsync_artifact_tree(run_root)
        ledger.append(
            event_type="calibration_resolution_completed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={
                "schema_version": 1,
                "calibration_dataset_hash": dataset.dataset_hash,
                "dataset": _artifact(root, dataset_path).model_dump(mode="json"),
                "resolutions": _artifact(root, resolution_path).model_dump(mode="json"),
                "concept_refs": _artifact(root, concept_ref_path).model_dump(mode="json"),
                "predictions": _artifact(root, prediction_path).model_dump(mode="json"),
                "provisional_gold": _artifact(root, provisional_gold_path).model_dump(mode="json"),
                "output_manifests": {
                    key: value.model_dump(mode="json") for key, value in sorted(output_manifests.items())
                },
                "output_manifest_hashes": output_manifest_hashes,
            },
        )
        return {
            "dataset_hash": dataset.dataset_hash,
            "artifact_root": str(run_root.relative_to(root)),
            "record_count": len(resolutions.records),
            "system_count": len(resolutions.taxonomy_version_ids),
            "gold_review_method": provisional_gold.review_method,
        }
    except Exception as exc:
        _telemetry_if_missing(root, run_id)
        ledger.append(
            event_type="calibration_resolution_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={"error_type": type(exc).__name__},
        )
        raise


def _freeze_calibration_policy(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    calibration = verify_pilot_calibration_artifacts(root=root, corpus=corpus)
    try:
        independent_gold = TaxonomyGoldSet.model_validate_json(
            args.independent_gold.resolve().read_text(encoding="utf-8")
        )
        coverage_gold = PilotCoverageGoldSet.model_validate_json(
            args.coverage_gold.resolve().read_text(encoding="utf-8")
        )
    except Exception as exc:  # noqa: BLE001 - 操作者输入统一转换为稳定错误码
        raise PilotArtifactError("pilot_calibration_review_input_invalid") from exc
    attestation = PilotGoldReviewAttestation(
        schema_version=1,
        corpus_id=corpus.corpus_id,
        provisional_dataset_hash=calibration.provisional_gold.dataset_hash,
        independent_dataset_hash=independent_gold.dataset_hash,
        provisional_gold_hash=calibration.provisional_gold.canonical_hash,
        independent_gold_hash=independent_gold.canonical_hash,
        independent_coverage_dataset_hash=coverage_gold.dataset_hash,
        independent_coverage_gold_hash=coverage_gold.canonical_hash,
        provisional_reviewed_by=calibration.provisional_gold.reviewed_by,
        reviewed_by=independent_gold.reviewed_by,
        reviewed_at=independent_gold.reviewed_at,
        coverage_reviewed_by=coverage_gold.reviewed_by,
        coverage_reviewed_at=coverage_gold.reviewed_at,
    )
    run_id = _validated_record_id(args.run_id)
    run_root = root / "runs" / "calibration-policy" / run_id
    if run_root.exists():
        raise PilotArtifactError(f"pilot_policy_freeze_run_already_exists:{run_id}")
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="calibration_policy_freeze_started",
        corpus=corpus,
        run_id=run_id,
        actor=args.actor,
        payload={
            "calibration_event_hash": calibration.event.event_hash,
            "independent_gold_hash": independent_gold.canonical_hash,
            "coverage_gold_hash": coverage_gold.canonical_hash,
            "minimum_precision": args.minimum_precision,
            "minimum_auto_decisions": args.minimum_auto_decisions,
        },
    )
    try:
        frozen_policy = build_pilot_frozen_policy(
            root=root,
            corpus=corpus,
            provisional_gold=calibration.provisional_gold,
            independent_gold=independent_gold,
            coverage_gold=coverage_gold,
            attestation=attestation,
            calibrated_at=datetime.now(timezone.utc),
            minimum_precision=args.minimum_precision,
            minimum_auto_decisions=args.minimum_auto_decisions,
        )
        independent_gold_path = run_root / "reviews" / "calibration-gold-independent.json"
        coverage_gold_path = run_root / "reviews" / "calibration-coverage-gold-independent.json"
        attestation_path = run_root / "reviews" / "gold-attestation.json"
        frozen_policy_path = run_root / "policies" / "frozen-policy.json"
        write_json_once(independent_gold_path, independent_gold)
        write_json_once(coverage_gold_path, coverage_gold)
        write_json_once(attestation_path, attestation)
        write_json_once(frozen_policy_path, frozen_policy)
        _fsync_artifact_tree(run_root)
        ledger.append(
            event_type="calibration_policy_freeze_completed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={
                "schema_version": 1,
                "calibration_dataset_hash": calibration.dataset.dataset_hash,
                "frozen_policy_hash": frozen_policy.canonical_hash,
                "minimum_precision": args.minimum_precision,
                "minimum_auto_decisions": args.minimum_auto_decisions,
                "frozen_policy": _artifact(root, frozen_policy_path).model_dump(mode="json"),
                "independent_gold": _artifact(root, independent_gold_path).model_dump(mode="json"),
                "coverage_gold": _artifact(root, coverage_gold_path).model_dump(mode="json"),
                "gold_attestation": _artifact(root, attestation_path).model_dump(mode="json"),
            },
        )
        return {
            "calibration_dataset_hash": calibration.dataset.dataset_hash,
            "frozen_policy_hash": frozen_policy.canonical_hash,
            "minimum_score": frozen_policy.policy.minimum_score,
            "minimum_margin": frozen_policy.policy.minimum_margin,
            "observed_precision": frozen_policy.observed_precision,
            "observed_auto_coverage": frozen_policy.observed_auto_coverage,
            "artifact_root": str(run_root.relative_to(root)),
        }
    except Exception as exc:
        ledger.append(
            event_type="calibration_policy_freeze_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={"error_type": type(exc).__name__},
        )
        raise


async def _run_locked_test(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    policy_freeze = verify_pilot_policy_freeze_artifacts(root=root, corpus=corpus)
    run_id = _validated_record_id(args.run_id)
    run_root = root / "runs" / "locked-test" / run_id
    dataset_path = root / f"locked-test-dataset-{run_id}.json"
    if run_root.exists() or dataset_path.exists():
        raise PilotArtifactError(f"pilot_locked_test_run_already_exists:{run_id}")
    source_gold_path = args.source_gold.resolve()
    source_transformation_path = args.transformation_commitment.resolve()
    gate_path = args.gate.resolve()
    if not source_gold_path.is_file() or not source_transformation_path.is_file() or not gate_path.is_file():
        raise PilotArtifactError("pilot_locked_test_committed_input_missing")
    try:
        preflight_gate = TaxonomyEvaluationGate.model_validate_json(gate_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - gate 配置必须在消费唯一 test 前完成预检
        raise PilotArtifactError("pilot_locked_test_gate_invalid") from exc
    validate_pilot_locked_test_gate(preflight_gate)
    evolution_policy = _locked_test_evolution_policy()
    evolution_policy_path = run_root / "policies" / "evolution-policy.json"
    evolution_policy_sha256 = _json_artifact_sha256(evolution_policy)
    bundle = build_environment_model_bundle(settings)
    _pin_runtime(root, bundle)
    commitment = PilotLockedTestInputCommitment(
        schema_version=3,
        source_gold_sha256=_sha256_file(source_gold_path),
        source_transformation_commitment_sha256=_sha256_file(source_transformation_path),
        evolution_policy_sha256=evolution_policy_sha256,
        gate_sha256=_sha256_file(gate_path),
    )
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    reservation = reserve_locked_test(
        ledger=ledger,
        corpus=corpus,
        run_id=run_id,
        actor=args.actor,
        input_commitment=commitment,
    )
    source_gold_copy_path = run_root / "reviews" / "test-source-gold.json"
    source_transformation_copy_path = run_root / "reviews" / "source-transformations.json"
    frozen_gate_path = run_root / "evaluation" / "gate.json"
    llm_stats.calls.clear()
    try:
        _copy_file_once(source_gold_path, source_gold_copy_path)
        _copy_file_once(source_transformation_path, source_transformation_copy_path)
        _copy_file_once(gate_path, frozen_gate_path)
        write_json_once(evolution_policy_path, evolution_policy)
        if (
            _sha256_file(source_gold_copy_path) != commitment.source_gold_sha256
            or _sha256_file(source_transformation_copy_path) != commitment.source_transformation_commitment_sha256
            or _sha256_file(evolution_policy_path) != commitment.evolution_policy_sha256
            or _sha256_file(frozen_gate_path) != commitment.gate_sha256
        ):
            raise PilotArtifactError("pilot_locked_test_committed_input_changed")
        extractions, extraction_summaries = await _extract_split_requirement_units(
            root=root,
            corpus=corpus,
            split="test",
            output_dir=run_root / "requirements",
            bundle=bundle,
            allow_locked_test=True,
        )
        degraded_calls = _strict_llm_telemetry_issues(llm_stats.calls)
        if degraded_calls:
            raise PilotArtifactError("pilot_degraded_llm_output:" + json.dumps(degraded_calls, ensure_ascii=False))
        transformation_path = run_root / "evaluation" / "transformation-projection.json"
        runtime_path = root / "runtime" / "model-bundle.json"
        test_documents = sorted(
            (item for item in corpus.documents if item.split == "test"),
            key=lambda item: item.document_key,
        )
        prompt_revisions = {
            "candidate_retriever": TAXONOMY_RETRIEVER_REVISION,
            "taxonomy_resolver": TAXONOMY_RESOLVER_PROMPT_REVISION,
            "taxonomy_evolution": EVOLUTION_PROMPT_REVISION,
        }
        model_revisions = {
            "embedding": _model_revision(bundle, ModelRole.EMBEDDING),
            "taxonomy_resolver": _model_revision(bundle, ModelRole.VERIFY),
            "taxonomy_evolution": _model_revision(bundle, ModelRole.VERIFY),
        }
        dataset_seed = TaxonomyDatasetManifest(
            schema_version=3,
            corpus_id=corpus.corpus_id,
            pilot_corpus=True,
            split_strategy="document_level",
            test_locked=True,
            evaluation_split="test",
            source_commitment_hash=corpus.source_commitment_hash,
            upstream_artifact_hashes={
                "bootstrap_event": bootstrap.event.event_hash,
                "bootstrap_identity": bootstrap.receipt.bootstrap_hash,
                "policy_freeze_event": policy_freeze.event.event_hash,
                "calibration_dataset": policy_freeze.frozen_policy.calibration_dataset_hash,
                "frozen_policy": policy_freeze.frozen_policy.canonical_hash,
                "runtime_manifest": _sha256_file(runtime_path),
                "evolution_policy": evolution_policy_sha256,
                **{
                    f"output_manifest.{system_key}": value
                    for system_key, value in sorted(bootstrap.receipt.output_manifest_hashes.items())
                },
            },
            created_at=corpus.frozen_at,
            documents=[
                {
                    "document_key": document.document_key,
                    "document_id": document.document_id,
                    "system_key": document.system_key,
                    "system_id": document.system_id,
                    "split": "test",
                    "source": document.source,
                    "requirement_units": ArtifactRef.model_validate(
                        extraction_summaries[document.document_key]["artifact"]
                    ),
                }
                for document in test_documents
            ],
            gold_artifact={
                "path": str((run_root / "reviews" / "test-gold-derived.json").relative_to(root)),
                "sha256": "0" * 64,
            },
            prediction_artifact={
                "path": str((run_root / "predictions" / "predictions.json").relative_to(root)),
                "sha256": "0" * 64,
            },
            source_transformation_commitment_artifact=_artifact(root, source_transformation_copy_path),
            transformation_projection_artifact={
                "path": str(transformation_path.relative_to(root)),
                "sha256": "0" * 64,
            },
            transformation_projection_revision=PILOT_TRANSFORMATION_PROJECTION_REVISION,
            prompt_revisions=prompt_revisions,
            model_revisions=model_revisions,
        )
        dataset_hash = dataset_seed.dataset_hash
        resolutions, concept_ref_set, _ = await _resolve_split_units(
            corpus=corpus,
            bootstrap=bootstrap,
            documents=test_documents,
            extractions=extractions,
            bundle=bundle,
            policy=policy_freeze.frozen_policy.policy,
            dataset_hash=dataset_hash,
            run_id=run_id,
            split="test",
            prompt_revisions=prompt_revisions,
            model_revisions=model_revisions,
            frozen_policy_hash=policy_freeze.frozen_policy.canonical_hash,
        )
        evolutions = await _evolve_locked_test_novel_units(
            bootstrap=bootstrap,
            extractions=extractions,
            resolutions=resolutions,
            bundle=bundle,
            policy=evolution_policy,
        )
        evolution_requirement_units = {
            unit.unit_id: unit for extraction in extractions.values() for unit in extraction.units
        }
        output_manifest_models = build_evolution_draft_manifests(
            active_manifests=bootstrap.manifests,
            evolution_results=evolutions,
            requirement_units=evolution_requirement_units,
        )
        evolution_paths = {
            system_key: run_root / "raw" / "evolutions" / f"{system_key}.json" for system_key in sorted(evolutions)
        }
        output_manifest_paths = {
            system_key: run_root / "manifests" / f"{system_key}.json" for system_key in sorted(output_manifest_models)
        }
        for system_key, path in evolution_paths.items():
            write_json_once(path, evolutions[system_key])
        for system_key, path in output_manifest_paths.items():
            write_json_once(path, output_manifest_models[system_key])
        evolution_refs = {system_key: _artifact(root, path) for system_key, path in evolution_paths.items()}
        output_manifest_refs = {system_key: _artifact(root, path) for system_key, path in output_manifest_paths.items()}
        predictions = project_resolution_predictions(
            resolutions=resolutions,
            concept_refs=concept_ref_set.by_concept_id,
            manifests=bootstrap.manifests,
            manifest_artifacts=output_manifest_refs,
            evolution_results=evolutions,
            output_manifests=output_manifest_models,
        )
        resolution_path = run_root / "raw" / "resolutions.json"
        concept_ref_path = run_root / "artifacts" / "concept-refs.json"
        prediction_path = run_root / "predictions" / "predictions.json"
        write_json_once(resolution_path, resolutions)
        write_json_once(concept_ref_path, concept_ref_set)
        write_json_once(prediction_path, predictions)
        _fsync_artifact_tree(run_root)

        degraded_calls = _strict_llm_telemetry_issues(llm_stats.calls)
        if degraded_calls:
            raise PilotArtifactError("pilot_degraded_llm_output:" + json.dumps(degraded_calls, ensure_ascii=False))

        # 预测已经不可变落盘后才揭盲 source gold，避免 test 标签影响 resolver。
        try:
            source_gold = PilotCoverageGoldSet.model_validate_json(source_gold_copy_path.read_text(encoding="utf-8"))
            source_transformations = PilotSourceTransformationCommitment.model_validate_json(
                source_transformation_copy_path.read_text(encoding="utf-8")
            )
            gate = TaxonomyEvaluationGate.model_validate_json(frozen_gate_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 揭盲输入统一转换为稳定错误码
            raise PilotArtifactError("pilot_locked_test_committed_input_invalid") from exc
        validate_pilot_locked_test_gate(gate)
        if source_gold.reviewed_at > reservation.occurred_at:
            raise PilotArtifactError("pilot_locked_test_gold_not_frozen_before_reservation")
        if (
            source_transformations.reviewed_at > reservation.occurred_at
            or source_transformations.source_gold_sha256 != commitment.source_gold_sha256
        ):
            raise PilotArtifactError("pilot_locked_test_transformation_commitment_not_frozen")
        derived_gold, coverage_metrics, transformation_set = derive_locked_test_evidence(
            root=root,
            corpus=corpus,
            dataset=dataset_seed,
            extractions=extractions,
            source_gold=source_gold,
            source_transformations=source_transformations,
        )
        derived_gold_path = run_root / "reviews" / "test-gold-derived.json"
        coverage_metrics_path = run_root / "evaluation" / "source-coverage-metrics.json"
        write_json_once(derived_gold_path, derived_gold)
        write_json_once(transformation_path, transformation_set)
        write_json_once(coverage_metrics_path, asdict(coverage_metrics))

        dataset_payload = dataset_seed.model_dump(mode="json")
        dataset_payload["gold_artifact"] = _artifact(root, derived_gold_path).model_dump(mode="json")
        dataset_payload["prediction_artifact"] = _artifact(root, prediction_path).model_dump(mode="json")
        dataset_payload["transformation_projection_artifact"] = _artifact(root, transformation_path).model_dump(
            mode="json"
        )
        dataset = TaxonomyDatasetManifest.model_validate(dataset_payload)
        if dataset.dataset_hash != dataset_hash:
            raise PilotArtifactError("pilot_locked_test_dataset_hash_drift")
        write_json_atomic_once(dataset_path, dataset)
        validate_evaluation_artifact_hashes(dataset=dataset, manifest_path=dataset_path)
        evaluation_requirement_units = load_requirement_unit_index(
            dataset=dataset,
            manifest_path=dataset_path,
            document_splits={"test"},
        )
        loaded_manifests = load_prediction_output_manifests(
            dataset=dataset,
            dataset_path=dataset_path,
            predictions=predictions,
        )
        if loaded_manifests != output_manifest_models:
            raise PilotArtifactError("pilot_locked_test_manifest_binding_invalid")
        evaluation = evaluate_taxonomy_generalization(
            dataset=dataset,
            gold=derived_gold,
            predictions=predictions,
            output_manifests=loaded_manifests,
            requirement_units=evaluation_requirement_units,
            transformations=transformation_set,
            frozen_policy=policy_freeze.frozen_policy,
            gate=gate,
        )
        evaluation_path = run_root / "evaluation" / "evaluation.json"
        report_path = run_root / "evaluation" / "REPORT.md"
        write_json_once(evaluation_path, evaluation)
        write_text_once(report_path, render_taxonomy_evaluation_report(evaluation))
        _telemetry_if_missing(root, run_id)
        _fsync_artifact_tree(run_root)
        ledger.append(
            event_type="locked_test_completed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload={
                "schema_version": 3,
                "test_dataset_hash": dataset.dataset_hash,
                "frozen_policy_hash": policy_freeze.frozen_policy.canonical_hash,
                "dataset": _artifact(root, dataset_path).model_dump(mode="json"),
                "requirement_extractions": extraction_summaries,
                "resolutions": _artifact(root, resolution_path).model_dump(mode="json"),
                "concept_refs": _artifact(root, concept_ref_path).model_dump(mode="json"),
                "predictions": _artifact(root, prediction_path).model_dump(mode="json"),
                "source_gold": _artifact(root, source_gold_copy_path).model_dump(mode="json"),
                "source_transformation_commitment": _artifact(
                    root,
                    source_transformation_copy_path,
                ).model_dump(mode="json"),
                "transformation_projection": _artifact(root, transformation_path).model_dump(mode="json"),
                "transformation_projection_revision": PILOT_TRANSFORMATION_PROJECTION_REVISION,
                "evolution_policy": _artifact(root, evolution_policy_path).model_dump(mode="json"),
                "evolutions": {key: value.model_dump(mode="json") for key, value in sorted(evolution_refs.items())},
                "derived_gold": _artifact(root, derived_gold_path).model_dump(mode="json"),
                "source_coverage_metrics": _artifact(root, coverage_metrics_path).model_dump(mode="json"),
                "gate": _artifact(root, frozen_gate_path).model_dump(mode="json"),
                "evaluation": _artifact(root, evaluation_path).model_dump(mode="json"),
                "report": _artifact(root, report_path).model_dump(mode="json"),
                "output_manifests": {
                    key: value.model_dump(mode="json") for key, value in sorted(output_manifest_refs.items())
                },
                "output_manifest_hashes": predictions.output_manifest_hashes,
            },
        )
        return {
            "dataset_hash": dataset.dataset_hash,
            "frozen_policy_hash": policy_freeze.frozen_policy.canonical_hash,
            "overall_status": evaluation.overall_status,
            "record_count": len(predictions.records),
            "source_coverage_recall": coverage_metrics.extraction_recall,
            "source_coverage_precision": coverage_metrics.extraction_precision,
            "artifact_root": str(run_root.relative_to(root)),
        }
    except PilotSourceCoverageError as exc:
        failure_dataset_payload = dataset_seed.model_dump(mode="json")
        failure_dataset_payload["prediction_artifact"] = _artifact(root, prediction_path).model_dump(mode="json")
        failure_dataset = TaxonomyDatasetManifest.model_validate(failure_dataset_payload)
        if failure_dataset.dataset_hash != dataset_hash:
            raise PilotArtifactError("pilot_locked_test_dataset_hash_drift")
        write_json_atomic_once(dataset_path, failure_dataset)
        coverage_metrics_path = run_root / "evaluation" / "source-coverage-metrics.json"
        report_path = run_root / "evaluation" / "SOURCE-COVERAGE-FAILURE.md"
        write_json_once(coverage_metrics_path, asdict(exc.metrics))
        write_text_once(report_path, render_locked_test_source_coverage_failure(exc.metrics, exc.findings))
        _telemetry_if_missing(root, run_id)
        _fsync_artifact_tree(run_root)
        receipt = PilotLockedTestFailureReceipt(
            schema_version=3,
            error_type=type(exc).__name__,
            failure_kind="source_coverage_quality_gate",
            test_dataset_hash=dataset_hash,
            frozen_policy_hash=policy_freeze.frozen_policy.canonical_hash,
            dataset=_artifact(root, dataset_path),
            requirement_extractions=extraction_summaries,
            resolutions=_artifact(root, resolution_path),
            concept_refs=_artifact(root, concept_ref_path),
            predictions=_artifact(root, prediction_path),
            source_gold=_artifact(root, source_gold_copy_path),
            source_transformation_commitment=_artifact(root, source_transformation_copy_path),
            transformation_projection_revision=PILOT_TRANSFORMATION_PROJECTION_REVISION,
            evolution_policy=_artifact(root, evolution_policy_path),
            evolutions=evolution_refs,
            source_coverage_metrics=_artifact(root, coverage_metrics_path),
            gate=_artifact(root, frozen_gate_path),
            report=_artifact(root, report_path),
            output_manifests=output_manifest_refs,
            output_manifest_hashes=predictions.output_manifest_hashes,
            findings=exc.findings,
        )
        ledger.append(
            event_type="locked_test_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload=receipt.model_dump(mode="json"),
        )
        raise
    except Exception as exc:
        _telemetry_if_missing(root, run_id)
        receipt = PilotLockedTestFailureReceipt(
            schema_version=3,
            error_type=type(exc).__name__,
            failure_kind="execution",
        )
        ledger.append(
            event_type="locked_test_failed",
            corpus=corpus,
            run_id=run_id,
            actor=args.actor,
            payload=receipt.model_dump(mode="json"),
        )
        raise


def _verify_locked_test(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    corpus = load_frozen_corpus(root)
    events = PilotRunLedger(root / "run-ledger.jsonl").read_events()
    if any(event.event_type == "locked_test_completed" for event in events):
        verified = verify_pilot_locked_test_artifacts(root=root, corpus=corpus)
        return {
            "terminal_status": "completed",
            "run_id": verified.completion_event.run_id,
            "dataset_hash": verified.dataset.dataset_hash,
            "evaluation_status": verified.evaluation.overall_status,
            "evidence_replayed": True,
        }
    if any(event.event_type == "locked_test_failed" for event in events):
        verified_failure = verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)
        return {
            "terminal_status": "failed",
            "run_id": verified_failure.failure_event.run_id,
            "dataset_hash": verified_failure.receipt.test_dataset_hash,
            "failure_kind": verified_failure.receipt.failure_kind,
            "error_type": verified_failure.receipt.error_type,
            "evidence_replayed": verified_failure.source_coverage_metrics is not None,
        }
    raise PilotArtifactError("pilot_locked_test_terminal_event_missing")


async def _run_async(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "freeze":
        spec = PilotCorpusSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        corpus = freeze_pilot_corpus(
            spec=spec,
            output_dir=args.output.resolve(),
            actor=args.actor,
            run_id=args.run_id,
        )
        return {
            "corpus_id": corpus.corpus_id,
            "source_commitment_hash": corpus.source_commitment_hash,
            "document_count": len(corpus.documents),
        }
    if args.command == "extract-units":
        return await _extract_units(args)
    if args.command == "bootstrap-taxonomy":
        return await _bootstrap_taxonomy(args)
    if args.command == "resolve-calibration":
        return await _resolve_calibration(args)
    if args.command == "freeze-calibration-policy":
        return _freeze_calibration_policy(args)
    if args.command == "run-locked-test":
        return await _run_locked_test(args)
    if args.command == "verify-locked-test":
        return _verify_locked_test(args)
    raise PilotArtifactError(f"pilot_command_unsupported:{args.command}")


def _result_exit_code(args: argparse.Namespace, result: dict[str, object]) -> int:
    if args.command == "run-locked-test":
        return 0 if result.get("overall_status") == "pass" else 2
    if args.command == "verify-locked-test":
        return 0 if result.get("terminal_status") == "completed" and result.get("evaluation_status") == "pass" else 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run_async(args))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return _result_exit_code(args, result)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ValidationError,
        PilotArtifactError,
        FeatureSegmentationError,
        SectionClassificationError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
