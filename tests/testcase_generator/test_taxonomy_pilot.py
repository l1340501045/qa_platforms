from __future__ import annotations

import asyncio
import hashlib
import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

import scripts.taxonomy_pilot as taxonomy_pilot_script
import src.testcase_generator.services.taxonomy_pilot as taxonomy_pilot_service
from scripts.taxonomy_pilot import (
    _blocking_extraction_issue_codes,
    _bootstrap_identity,
    _load_bootstrap_extractions,
    _parser,
    _prepare_extraction_run,
    _review_report,
    _runtime_manifest,
    _source_revision,
    _strict_llm_telemetry_issues,
    _validate_bootstrap_results_for_completion,
)
from src.knowledge_base.services.parsers.markdown_parser import (
    MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
    MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
    canonicalize_markdown,
)
from src.platform_api.core.model_runtime import build_environment_model_bundle
from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)
from src.testcase_generator.schemas.taxonomy import TaxonomyExample, TaxonomyManifest, TaxonomyNodeManifest
from src.testcase_generator.schemas.taxonomy_evaluation import (
    ArtifactRef,
    TaxonomyCalibrationSystemMetrics,
    TaxonomyDatasetManifest,
    TaxonomyEvaluationGate,
    TaxonomyFrozenPolicy,
    TaxonomyGoldRecord,
    TaxonomyGoldSet,
    TaxonomyPredictionSet,
    TaxonomyTransformationSet,
)
from src.testcase_generator.schemas.taxonomy_pilot import (
    PilotConceptRef,
    PilotConceptRefEntry,
    PilotConceptRefSet,
    PilotCorpusSpec,
    PilotCoverageGoldFact,
    PilotCoverageGoldRecord,
    PilotCoverageGoldSet,
    PilotGoldReviewAttestation,
    PilotLockedTestFailureReceipt,
    PilotLockedTestInputCommitment,
    PilotResolutionRecord,
    PilotResolutionSet,
    build_pilot_ledger_event,
)
from src.testcase_generator.schemas.taxonomy_resolution import (
    TaxonomyCandidate,
    TaxonomyResolution,
    TaxonomyResolutionPolicy,
)
from src.testcase_generator.services.requirement_unit_service import (
    RequirementChunkCoverage,
    RequirementUnitExtractionResult,
    RequirementUnitIssue,
    build_requirement_coverage_id,
)
from src.testcase_generator.services.taxonomy_bootstrap import (
    BootstrapRequirementAssignment,
    TaxonomyBootstrapPolicy,
    TaxonomyBootstrapResult,
)
from src.testcase_generator.services.taxonomy_manifest import manifest_hash
from src.testcase_generator.services.taxonomy_pilot import (
    LockedTestAlreadyConsumedError,
    PilotArtifactError,
    PilotRunLedger,
    PilotSourceCoverageError,
    build_pilot_frozen_policy,
    build_provisional_bootstrap_gold,
    derive_locked_test_gold,
    freeze_pilot_corpus,
    load_frozen_corpus,
    load_split_snapshots,
    pilot_record_id,
    project_resolution_predictions,
    reserve_locked_test,
    verify_pilot_bootstrap_artifacts,
    verify_pilot_calibration_artifacts,
    verify_pilot_calibration_coverage_gold,
    verify_pilot_locked_test_artifacts,
    verify_pilot_locked_test_failure_artifacts,
    verify_pilot_policy_freeze_artifacts,
    verify_pilot_requirement_artifacts,
    write_json_atomic_once,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
SYSTEM_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SYSTEM_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
DOCUMENT_A = UUID("11111111-1111-1111-1111-111111111111")
CONCEPT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TAXONOMY_VERSION_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
MANIFEST_ARTIFACT = ArtifactRef(path="manifests/motion.json", sha256="f" * 64)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spec(tmp_path: Path) -> PilotCorpusSpec:
    documents = []
    values = (
        ("motion-bootstrap", "漫剧初版功能 PRD", "motion", SYSTEM_A, "bootstrap", "漫剧基线需求"),
        ("motion-calibration", "漫剧 1.5 PRD", "motion", SYSTEM_A, "calibration", "漫剧校准需求"),
        ("motion-test", "漫剧 2.0 PRD", "motion", SYSTEM_A, "test", "漫剧锁定测试需求"),
        (
            "distribution-bootstrap",
            "分销 v1.2 PRD",
            "distribution",
            SYSTEM_B,
            "bootstrap",
            "分销基线需求",
        ),
        (
            "distribution-calibration",
            "分销 v1.3 PRD",
            "distribution",
            SYSTEM_B,
            "calibration",
            "分销校准需求",
        ),
        ("distribution-test", "分销 API 优化 PRD", "distribution", SYSTEM_B, "test", "分销锁定测试需求"),
    )
    for index, (document_key, title, system_key, system_id, split, content) in enumerate(values, start=1):
        path = tmp_path / f"source-{index}.md"
        path.write_text(content, encoding="utf-8")
        documents.append(
            {
                "document_key": document_key,
                "title": title,
                "document_id": f"00000000-0000-0000-0000-00000000000{index}",
                "system_key": system_key,
                "system_id": str(system_id),
                "split": split,
                "source_path": str(path),
                "source_sha256": _sha(content),
                "canonical_sha256": canonicalize_markdown(content).canonical_sha256,
                "canonicalization_revision": MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
                "image_enrichment_revision": MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
            }
        )
    return PilotCorpusSpec(
        schema_version=3,
        corpus_id="taxonomy-pilot-v1",
        created_at=NOW,
        documents=documents,
    )


def _freeze(tmp_path: Path):
    root = tmp_path / "pilot-run"
    corpus = freeze_pilot_corpus(
        spec=_spec(tmp_path),
        output_dir=root,
        actor="pilot-preparer",
        run_id="pilot-run-001",
        frozen_at=NOW + timedelta(minutes=1),
    )
    return root, corpus


def _unit() -> RequirementUnit:
    statement = "系统每天从上游同步商品。"
    source_ref = "prd:商品 §同步"
    quote = "商品库每日从上游同步商品。"
    content_hash = _sha(quote)
    return RequirementUnit(
        unit_id=build_requirement_unit_id(
            document_content_hash=content_hash,
            source_ref=source_ref,
            statement=statement,
        ),
        system_id=SYSTEM_A,
        document_id=DOCUMENT_A,
        document_content_hash=content_hash,
        source_ref=source_ref,
        source_quote=quote,
        source_quote_hash=build_source_quote_hash(quote),
        structural_key="product.sync",
        title="商品同步",
        statement=statement,
        observable_outcome="商品列表展示上游最新数据。",
        scope_status="atomic",
    )


def _extraction_with_units(
    *,
    document_id: UUID,
    document_content_hash: str,
    source_ref: str,
    units: list[RequirementUnit],
    issues: list[RequirementUnitIssue] | None = None,
    disposition: str | None = None,
) -> RequirementUnitExtractionResult:
    resolved_disposition = disposition or ("requirements_extracted" if units else "no_requirement")
    coverage = RequirementChunkCoverage(
        coverage_id=build_requirement_coverage_id(
            document_content_hash=document_content_hash,
            source_ref=source_ref,
            chunk_index=1,
            content_hash=document_content_hash,
        ),
        source_ref=source_ref,
        heading="测试章节",
        section_kind="spec",
        chunk_index=1,
        chunk_count=1,
        content_hash=document_content_hash,
        disposition=resolved_disposition,
        requirement_unit_ids=[unit.unit_id for unit in units],
        reason=None if resolved_disposition == "requirements_extracted" else "测试夹具显式处置。",
    )
    return RequirementUnitExtractionResult(
        document_id=document_id,
        document_content_hash=document_content_hash,
        input_hash="4" * 64,
        prompt_revision="requirement@1",
        model_revision="primary@1",
        chunk_count=1,
        units=units,
        coverage=[coverage],
        issues=issues or [],
    )


def _requirement_artifact_summary(
    *,
    root: Path,
    path: Path,
    extraction: RequirementUnitExtractionResult,
    section_count: int = 1,
) -> dict[str, object]:
    return {
        "artifact": {
            "path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "section_count": section_count,
        "chunk_count": extraction.chunk_count,
        "unit_count": len(extraction.units),
        "atomic_count": sum(unit.scope_status == "atomic" for unit in extraction.units),
        "issue_count": len(extraction.issues),
    }


def _write_artifact_ref(root: Path, relative_path: str, content: str = "{}") -> dict[str, str]:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _manifest(unit: RequirementUnit) -> TaxonomyManifest:
    return TaxonomyManifest(
        schema_version=2,
        system_id=unit.system_id,
        version=1,
        change_note="pilot baseline",
        created_by="pilot-preparer",
        nodes=[
            TaxonomyNodeManifest(
                stable_key="business.assets",
                node_type="module",
                display_name="业务资产",
                sort_order=0,
                node_status="active",
                definition="管理业务资产。",
                scope_note="覆盖商品等业务资产。",
                in_scope_examples=[
                    TaxonomyExample(
                        text=unit.source_quote,
                        document_content_hash=unit.document_content_hash,
                        requirement_unit_id=unit.unit_id,
                    )
                ],
            ),
            TaxonomyNodeManifest(
                stable_key="product.sync",
                node_type="capability",
                display_name="商品同步",
                parent_stable_key="business.assets",
                sort_order=0,
                node_status="active",
                definition="从上游同步商品。",
                scope_note="不包含人工单个新建商品。",
                in_scope_examples=[
                    TaxonomyExample(
                        text=unit.source_quote,
                        document_content_hash=unit.document_content_hash,
                        requirement_unit_id=unit.unit_id,
                    )
                ],
            ),
        ],
        mappings=[],
    )


def _independent_gold(corpus_id: str) -> TaxonomyGoldSet:
    unit = _unit()
    return TaxonomyGoldSet(
        schema_version=1,
        corpus_id=corpus_id,
        dataset_hash="5" * 64,
        review_method="human_independent",
        reviewed_by="independent-reviewer",
        reviewed_at=NOW + timedelta(minutes=3),
        records=[
            TaxonomyGoldRecord(
                record_id=pilot_record_id("motion-calibration", unit.unit_id),
                document_key="motion-calibration",
                system_key="motion",
                split="dev",
                requirement_unit_id=unit.unit_id,
                expected_disposition="abstain",
                gold_evidence=[unit.source_ref],
                eligible_for_auto=True,
            )
        ],
    )


def _resolution_policy() -> TaxonomyResolutionPolicy:
    return TaxonomyResolutionPolicy(
        schema_version=1,
        top_k=5,
        minimum_score=0.8,
        minimum_margin=0.2,
        out_of_scope_conflict_score=0.85,
        decision_context_max_chars=20_000,
        require_grounding=True,
        allowed_node_types=("module", "capability"),
        allowed_node_statuses=("active",),
        model_role="taxonomy_resolver",
        model_revision="verify@1",
        fail_behavior="abstain",
        auto_accept_signal="retrieval_score_margin",
    )


def _frozen_policy(
    gold: TaxonomyGoldSet,
    coverage_gold: PilotCoverageGoldSet | None = None,
) -> TaxonomyFrozenPolicy:
    policy = _resolution_policy()
    metrics = []
    for system_key in sorted({item.system_key for item in gold.records}):
        record_count = sum(item.system_key == system_key for item in gold.records)
        eligible_count = sum(item.system_key == system_key and item.eligible_for_auto for item in gold.records)
        metrics.append(
            TaxonomyCalibrationSystemMetrics(
                system_key=system_key,
                record_count=record_count,
                eligible_record_count=eligible_count,
                auto_decision_count=record_count,
                eligible_auto_decision_count=eligible_count,
                correct_auto_decision_count=eligible_count,
                precision=eligible_count / record_count,
                auto_coverage=1,
            )
        )
    eligible_count = sum(item.eligible_for_auto for item in gold.records)
    coverage_fields = {}
    if coverage_gold is not None:
        expected_fact_count = sum(len(item.facts) for item in coverage_gold.records)
        matched_ids = {
            fact.matched_requirement_unit_id
            for item in coverage_gold.records
            for fact in item.facts
            if fact.matched_requirement_unit_id is not None
        }
        coverage_fields = {
            "calibration_coverage_gold_hash": coverage_gold.canonical_hash,
            "calibration_coverage_gold_review_method": coverage_gold.review_method,
            "calibration_gold_attestation_hash": "7" * 64,
            "calibration_prediction_hash": "8" * 64,
            "calibration_source_commitment_hash": "9" * 64,
            "calibration_coverage_record_count": len(coverage_gold.records),
            "expected_requirement_fact_count": expected_fact_count,
            "matched_requirement_fact_count": len(matched_ids),
            "extracted_requirement_unit_count": len(matched_ids),
            "matched_extracted_requirement_unit_count": len(matched_ids),
            "observed_requirement_extraction_recall": 1,
            "observed_requirement_extraction_precision": 1,
        }
    return TaxonomyFrozenPolicy(
        schema_version=2 if coverage_gold is not None else 1,
        policy=policy,
        policy_hash=policy.canonical_hash,
        calibrated_at=NOW + timedelta(minutes=4),
        calibration_split="dev",
        calibration_dataset_hash=gold.dataset_hash,
        calibration_gold_hash=gold.canonical_hash,
        calibration_gold_review_method="human_independent",
        calibration_input_hash="6" * 64,
        observed_precision=1,
        observed_auto_coverage=1,
        calibration_system_metrics=metrics,
        calibration_record_count=len(gold.records),
        eligible_record_count=eligible_count,
        auto_decision_count=len(gold.records),
        eligible_auto_decision_count=eligible_count,
        correct_auto_decision_count=eligible_count,
        **coverage_fields,
    )


def _provisional_gold(gold: TaxonomyGoldSet) -> TaxonomyGoldSet:
    return gold.model_copy(
        update={
            "dataset_hash": "4" * 64,
            "review_method": "model_assisted_provisional",
            "reviewed_by": "calibration-model:pilot-preparer",
            "reviewed_at": NOW + timedelta(minutes=2),
        }
    )


def _completed_calibration_gold(root: Path) -> tuple[TaxonomyGoldSet, TaxonomyGoldSet]:
    event = next(
        item
        for item in PilotRunLedger(root / "run-ledger.jsonl").read_events()
        if item.event_type == "calibration_resolution_completed"
    )
    reference = ArtifactRef.model_validate(event.payload["provisional_gold"])
    provisional = TaxonomyGoldSet.model_validate_json((root / reference.path).read_text(encoding="utf-8"))
    independent = provisional.model_copy(
        update={
            "review_method": "human_independent",
            "reviewed_by": "independent-reviewer",
            "reviewed_at": NOW + timedelta(minutes=3),
        }
    )
    return provisional, independent


def _calibration_coverage_gold(
    root: Path,
    corpus,
    *,
    dataset_hash: str,
) -> PilotCoverageGoldSet:
    paths = verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"calibration"})
    records = []
    disposition_map = {
        "requirements_extracted": "requirements_present",
        "no_requirement": "no_requirement",
        "excluded_non_spec": "excluded_non_spec",
        "empty_section": "empty_section",
    }
    documents = {item.document_key: item for item in corpus.documents if item.split == "calibration"}
    for document_key, path in sorted(paths.items()):
        document = documents[document_key]
        extraction = RequirementUnitExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        units = {unit.unit_id: unit for unit in extraction.units}
        for coverage in extraction.coverage:
            records.append(
                PilotCoverageGoldRecord(
                    coverage_id=coverage.coverage_id,
                    document_key=document_key,
                    system_key=document.system_key,
                    split="calibration",
                    source_ref=coverage.source_ref,
                    content_hash=coverage.content_hash,
                    expected_disposition=disposition_map[coverage.disposition],
                    facts=[
                        PilotCoverageGoldFact(
                            fact_id=f"fact-{_sha(unit_id)[:24]}",
                            source_quote=units[unit_id].source_quote,
                            source_quote_hash=units[unit_id].source_quote_hash,
                            statement=units[unit_id].statement,
                            matched_requirement_unit_id=unit_id,
                        )
                        for unit_id in coverage.requirement_unit_ids
                    ],
                )
            )
    return PilotCoverageGoldSet(
        schema_version=1,
        corpus_id=corpus.corpus_id,
        dataset_hash=dataset_hash,
        reviewed_by="coverage-reviewer",
        reviewed_at=NOW + timedelta(minutes=3),
        records=records,
    )


def _locked_test_source_gold_and_dataset(root: Path, corpus):
    extractions = {}
    dataset_documents = []
    source_gold_records = []
    for document in sorted(
        (item for item in corpus.documents if item.split == "test"),
        key=lambda item: item.document_key,
    ):
        snapshot = (root / document.source.path).read_text(encoding="utf-8")
        source_ref = f"prd:{document.title} §测试章节"
        unit = RequirementUnit(
            unit_id=build_requirement_unit_id(
                document_content_hash=document.source.sha256,
                source_ref=source_ref,
                statement=snapshot,
            ),
            system_id=document.system_id,
            document_id=document.document_id,
            document_content_hash=document.source.sha256,
            source_ref=source_ref,
            source_quote=snapshot,
            source_quote_hash=build_source_quote_hash(snapshot),
            structural_key=f"{document.system_key}.fixture",
            title="测试需求",
            statement=snapshot,
            observable_outcome=snapshot,
            scope_status="atomic",
        )
        extraction = _extraction_with_units(
            document_id=document.document_id,
            document_content_hash=document.source.sha256,
            source_ref=source_ref,
            units=[unit],
        )
        extraction_path = root / "runs" / "locked-test" / "fixture" / "requirements" / f"{document.document_key}.json"
        extraction_path.parent.mkdir(parents=True, exist_ok=True)
        extraction_path.write_text(extraction.model_dump_json(), encoding="utf-8")
        extractions[document.document_key] = extraction
        dataset_documents.append(
            {
                "document_key": document.document_key,
                "document_id": document.document_id,
                "system_key": document.system_key,
                "system_id": document.system_id,
                "split": "test",
                "source": document.source,
                "requirement_units": {
                    "path": str(extraction_path.relative_to(root)),
                    "sha256": hashlib.sha256(extraction_path.read_bytes()).hexdigest(),
                },
            }
        )
        coverage = extraction.coverage[0]
        source_gold_records.append(
            PilotCoverageGoldRecord(
                coverage_id=coverage.coverage_id,
                document_key=document.document_key,
                system_key=document.system_key,
                split="test",
                source_ref=coverage.source_ref,
                content_hash=coverage.content_hash,
                expected_disposition="requirements_present",
                facts=[
                    PilotCoverageGoldFact(
                        fact_id=f"fact-{_sha(document.document_key)[:24]}",
                        source_quote=unit.source_quote,
                        source_quote_hash=unit.source_quote_hash,
                        statement=unit.statement,
                        taxonomy_expectation={
                            "expected_disposition": "reuse",
                            "expected_primary_stable_key": "product.sync",
                            "expected_path": ["business.assets", "product.sync"],
                            "eligible_for_auto": True,
                        },
                    )
                ],
            )
        )
    transformation_path = root / "runs" / "locked-test" / "fixture" / "evaluation" / "transformations.json"
    transformation_path.parent.mkdir(parents=True, exist_ok=True)
    transformation_path.write_text(
        TaxonomyTransformationSet(
            schema_version=1,
            corpus_id=corpus.corpus_id,
            records=[],
        ).model_dump_json(),
        encoding="utf-8",
    )
    dataset = TaxonomyDatasetManifest(
        schema_version=2,
        corpus_id=corpus.corpus_id,
        pilot_corpus=True,
        split_strategy="document_level",
        test_locked=True,
        evaluation_split="test",
        source_commitment_hash=corpus.source_commitment_hash,
        upstream_artifact_hashes={"frozen_policy": "a" * 64},
        created_at=corpus.frozen_at,
        documents=dataset_documents,
        gold_artifact={"path": "test-gold.json", "sha256": "b" * 64},
        prediction_artifact={"path": "test-predictions.json", "sha256": "c" * 64},
        transformation_artifact={
            "path": str(transformation_path.relative_to(root)),
            "sha256": hashlib.sha256(transformation_path.read_bytes()).hexdigest(),
        },
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )
    source_gold = PilotCoverageGoldSet(
        schema_version=2,
        corpus_id=corpus.corpus_id,
        source_commitment_hash=corpus.source_commitment_hash,
        reviewed_by="locked-test-reviewer",
        reviewed_at=NOW + timedelta(minutes=2),
        records=source_gold_records,
    )
    return extractions, dataset, source_gold


def _gold_attestation(
    corpus_id: str,
    provisional_gold: TaxonomyGoldSet,
    independent_gold: TaxonomyGoldSet,
    coverage_gold: PilotCoverageGoldSet,
) -> PilotGoldReviewAttestation:
    return PilotGoldReviewAttestation(
        schema_version=1,
        corpus_id=corpus_id,
        provisional_dataset_hash=provisional_gold.dataset_hash,
        independent_dataset_hash=independent_gold.dataset_hash,
        provisional_gold_hash=provisional_gold.canonical_hash,
        independent_gold_hash=independent_gold.canonical_hash,
        independent_coverage_dataset_hash=coverage_gold.dataset_hash,
        independent_coverage_gold_hash=coverage_gold.canonical_hash,
        provisional_reviewed_by=provisional_gold.reviewed_by,
        reviewed_by=independent_gold.reviewed_by,
        reviewed_at=independent_gold.reviewed_at,
        coverage_reviewed_by=coverage_gold.reviewed_by,
        coverage_reviewed_at=coverage_gold.reviewed_at,
    )


def _locked_test_commitment() -> PilotLockedTestInputCommitment:
    return PilotLockedTestInputCommitment(
        schema_version=1,
        source_gold_sha256="a" * 64,
        gate_sha256="b" * 64,
    )


async def _fake_locked_test_resolve(
    *,
    corpus,
    bootstrap,
    documents,
    extractions,
    bundle,
    policy,
    dataset_hash,
    run_id,
    split,
    prompt_revisions,
    model_revisions,
    frozen_policy_hash=None,
):
    assert split == "test"
    systems = sorted(bootstrap.manifests)
    version_ids = {system: UUID(int=500 + index) for index, system in enumerate(systems)}
    references = [
        PilotConceptRefEntry(
            concept_id=UUID(int=600 + index),
            system_key=system,
            stable_key="product.sync",
        )
        for index, system in enumerate(systems)
    ]
    concept_refs = PilotConceptRefSet(schema_version=1, records=references)
    concept_ids = {item.system_key: item.concept_id for item in references}
    records = []
    for document in documents:
        for unit in extractions[document.document_key].units:
            version_id = version_ids[document.system_key]
            concept_id = concept_ids[document.system_key]
            manifest_hash_value = manifest_hash(bootstrap.manifests[document.system_key])
            records.append(
                PilotResolutionRecord(
                    document_key=document.document_key,
                    system_key=document.system_key,
                    split="test",
                    requirement_unit_id=unit.unit_id,
                    latency_ms=10,
                    resolution=TaxonomyResolution(
                        schema_version=1,
                        status="mapped",
                        method="policy_auto",
                        taxonomy_version_id=version_id,
                        primary_concept_id=concept_id,
                        candidates=[
                            TaxonomyCandidate(
                                taxonomy_version_id=version_id,
                                concept_id=concept_id,
                                stable_key="product.sync",
                                score=0.95,
                                rank=1,
                                evidence=[unit.source_ref],
                            )
                        ],
                        confidence=0.95,
                        margin=0.95,
                        reason_code="fixture_match",
                        reason="测试夹具中的确定匹配。",
                        input_hash=_sha(f"locked:{unit.unit_id}"),
                        taxonomy_manifest_hash=manifest_hash_value,
                        policy_version=policy.canonical_hash,
                        model_revision=policy.model_revision,
                        requirement_unit_ids=[unit.unit_id],
                    ),
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
        taxonomy_version_ids=version_ids,
        output_manifest_hashes=bootstrap.receipt.output_manifest_hashes,
        records=records,
    )
    predictions = project_resolution_predictions(
        resolutions=resolutions,
        concept_refs=concept_refs.by_concept_id,
        manifests=bootstrap.manifests,
        manifest_artifacts=bootstrap.receipt.output_manifests,
    )
    return resolutions, concept_refs, predictions


def _append_locked_test_prerequisites(
    ledger: PilotRunLedger,
    corpus,
    *,
    placeholder_bootstrap: bool = False,
    placeholder_calibration: bool = False,
) -> None:
    root = ledger.path.parent
    extractions_by_document: dict[str, RequirementUnitExtractionResult] = {}
    extraction_stages = (
        ("bootstrap", "extract-bootstrap-001"),
        ("calibration", "extract-calibration-001"),
    )
    for split, run_id in extraction_stages:
        run_root = root / "runs" / "requirement-extraction" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        documents = {}
        for document in (item for item in corpus.documents if item.split == split):
            path = run_root / f"{document.document_key}.json"
            snapshot = (root / document.source.path).read_text(encoding="utf-8")
            source_ref = f"prd:{document.title} §测试章节"
            unit = RequirementUnit(
                unit_id=build_requirement_unit_id(
                    document_content_hash=document.source.sha256,
                    source_ref=source_ref,
                    statement=snapshot,
                ),
                system_id=document.system_id,
                document_id=document.document_id,
                document_content_hash=document.source.sha256,
                source_ref=source_ref,
                source_quote=snapshot,
                source_quote_hash=build_source_quote_hash(snapshot),
                structural_key=f"{document.system_key}.fixture",
                title="测试需求",
                statement=snapshot,
                observable_outcome=snapshot,
                scope_status="atomic",
            )
            extraction = _extraction_with_units(
                document_id=document.document_id,
                document_content_hash=document.source.sha256,
                source_ref=source_ref,
                units=[unit],
            )
            extractions_by_document[document.document_key] = extraction
            path.write_text(extraction.model_dump_json(), encoding="utf-8")
            documents[document.document_key] = _requirement_artifact_summary(
                root=root,
                path=path,
                extraction=extraction,
            )
        ledger.append(
            event_type="requirement_extraction_started",
            corpus=corpus,
            run_id=run_id,
            actor="pilot-operator",
            payload={"split": split},
        )
        ledger.append(
            event_type="requirement_extraction_completed",
            corpus=corpus,
            run_id=run_id,
            actor="pilot-operator",
            payload={"schema_version": 1, "split": split, "documents": documents},
        )

    bootstrap_run_id = "bootstrap-dev-001"
    bootstrap_root = f"runs/taxonomy-bootstrap/{bootstrap_run_id}"
    bootstrap_policy = TaxonomyBootstrapPolicy(
        schema_version=1,
        max_units_per_batch=20,
        max_batch_chars=60_000,
        max_consolidation_chars=100_000,
        max_nodes=1_000,
        fail_behavior="draft_only",
    )
    resolution_policy = _resolution_policy()
    _write_artifact_ref(
        root,
        f"{bootstrap_root}/policies/bootstrap-policy.json",
        bootstrap_policy.model_dump_json(),
    )
    _write_artifact_ref(
        root,
        f"{bootstrap_root}/policies/base-resolution-policy.json",
        resolution_policy.model_dump_json(),
    )
    runtime_ref = ArtifactRef.model_validate(
        _write_artifact_ref(root, "runtime/model-bundle.json", '{"schema_version":1}')
    )
    bootstrap_systems = sorted({item.system_key for item in corpus.documents if item.split == "bootstrap"})
    bootstrap_result_models: dict[str, TaxonomyBootstrapResult] = {}
    bootstrap_manifest_models: dict[str, TaxonomyManifest] = {}
    bootstrap_results: dict[str, dict[str, str]] = {}
    bootstrap_manifests: dict[str, dict[str, str]] = {}
    for system in bootstrap_systems:
        document = next(item for item in corpus.documents if item.split == "bootstrap" and item.system_key == system)
        unit = extractions_by_document[document.document_key].units[0]
        manifest = _manifest(unit)
        result = TaxonomyBootstrapResult(
            input_hash=_sha(f"bootstrap-input:{system}"),
            policy_version=_sha("bootstrap-policy"),
            proposal_prompt_revision="proposal@1",
            consolidation_prompt_revision="consolidation@1",
            proposal_model_revision="primary@1",
            consolidation_model_revision="verify@1",
            draft_manifest=manifest,
            draft_manifest_hash=manifest_hash(manifest),
            assignments=[
                BootstrapRequirementAssignment(
                    requirement_unit_id=unit.unit_id,
                    proposal_id=f"bp_{_sha(f'proposal:{system}')}",
                    target_stable_key="product.sync",
                )
            ],
        )
        bootstrap_result_models[system] = result
        bootstrap_manifest_models[system] = manifest
        bootstrap_results[system] = _write_artifact_ref(
            root,
            f"{bootstrap_root}/raw/{system}.json",
            result.model_dump_json(),
        )
        bootstrap_manifests[system] = _write_artifact_ref(
            root,
            f"{bootstrap_root}/manifests/{system}.json",
            manifest.model_dump_json(),
        )
    bootstrap_identity = _bootstrap_identity(
        root=root,
        corpus=corpus,
        extraction_paths={
            document.document_key: (
                root / "runs" / "requirement-extraction" / "extract-bootstrap-001" / f"{document.document_key}.json"
            )
            for document in corpus.documents
            if document.split == "bootstrap"
        },
        bundle=build_environment_model_bundle(settings),
        bootstrap_policy=bootstrap_policy,
        resolution_policy=resolution_policy,
    )
    bootstrap_hash = bootstrap_identity.bootstrap_hash
    bootstrap_gold = build_provisional_bootstrap_gold(
        corpus_id=corpus.corpus_id,
        dataset_hash=bootstrap_hash,
        bootstrap_results=bootstrap_result_models,
        requirement_units={
            item.document_key: extractions_by_document[item.document_key]
            for item in corpus.documents
            if item.split == "bootstrap"
        },
        documents={item.document_key: item for item in corpus.documents},
        reviewed_by="bootstrap-derived:pilot-operator",
        reviewed_at=NOW + timedelta(minutes=2),
    )
    if placeholder_bootstrap:
        bootstrap_results = {
            system: _write_artifact_ref(root, f"{bootstrap_root}/raw/{system}.json") for system in bootstrap_systems
        }
    bootstrap_payload = {
        "schema_version": 1,
        "bootstrap_hash": bootstrap_hash,
        "identity": _write_artifact_ref(
            root,
            f"{bootstrap_root}/artifacts/bootstrap-identity.json",
            bootstrap_identity.model_dump_json(),
        ),
        "provisional_gold": _write_artifact_ref(
            root,
            f"{bootstrap_root}/reviews/dev-gold-provisional.json",
            bootstrap_gold.model_dump_json(),
        ),
        "review_report": _write_artifact_ref(
            root,
            f"{bootstrap_root}/reviews/BOOTSTRAP-REVIEW.md",
            "# Review\n",
        ),
        "results": bootstrap_results,
        "output_manifests": bootstrap_manifests,
        "output_manifest_hashes": {
            system: manifest_hash(bootstrap_manifest_models[system]) for system in bootstrap_systems
        },
    }
    ledger.append(
        event_type="taxonomy_bootstrap_started",
        corpus=corpus,
        run_id=bootstrap_run_id,
        actor="pilot-operator",
    )
    bootstrap_event = ledger.append(
        event_type="taxonomy_bootstrap_completed",
        corpus=corpus,
        run_id=bootstrap_run_id,
        actor="pilot-operator",
        payload=bootstrap_payload,
    )

    resolution_run_id = "resolve-dev-001"
    resolution_root = f"runs/calibration-resolution/{resolution_run_id}"
    _write_artifact_ref(
        root,
        f"{resolution_root}/policies/base-resolution-policy.json",
        resolution_policy.model_dump_json(),
    )
    manifest_artifacts = {
        system: ArtifactRef.model_validate(reference) for system, reference in bootstrap_manifests.items()
    }
    output_manifest_hashes = {system: manifest_hash(bootstrap_manifest_models[system]) for system in bootstrap_systems}
    calibration_documents = [item for item in corpus.documents if item.split == "calibration"]
    transformation_set = TaxonomyTransformationSet(schema_version=1, corpus_id=corpus.corpus_id, records=[])
    transformation_ref = ArtifactRef.model_validate(
        _write_artifact_ref(
            root,
            f"{resolution_root}/evaluation/transformations.json",
            transformation_set.model_dump_json(),
        )
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
            "bootstrap_event": bootstrap_event.event_hash,
            "bootstrap_identity": bootstrap_hash,
            "runtime_manifest": runtime_ref.sha256,
            **{f"output_manifest.{system}": output_manifest_hashes[system] for system in bootstrap_systems},
        },
        created_at=NOW + timedelta(minutes=1),
        documents=[
            {
                "document_key": document.document_key,
                "document_id": document.document_id,
                "system_key": document.system_key,
                "system_id": document.system_id,
                "split": "dev",
                "source": document.source,
                "requirement_units": {
                    "path": (f"runs/requirement-extraction/extract-{document.split}-001/{document.document_key}.json"),
                    "sha256": hashlib.sha256(
                        (
                            root
                            / f"runs/requirement-extraction/extract-{document.split}-001/"
                            / f"{document.document_key}.json"
                        ).read_bytes()
                    ).hexdigest(),
                },
            }
            for document in calibration_documents
        ],
        gold_artifact={
            "path": f"{resolution_root}/reviews/calibration-gold-provisional.json",
            "sha256": "0" * 64,
        },
        prediction_artifact={
            "path": f"{resolution_root}/predictions/predictions.json",
            "sha256": "0" * 64,
        },
        transformation_artifact=transformation_ref,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
    )
    calibration_dataset_hash = dataset_seed.dataset_hash
    taxonomy_version_ids = {system: UUID(int=100 + index) for index, system in enumerate(bootstrap_systems, start=1)}
    concept_entries = [
        PilotConceptRefEntry(
            concept_id=UUID(int=200 + index),
            system_key=system,
            stable_key="product.sync",
        )
        for index, system in enumerate(bootstrap_systems, start=1)
    ]
    concept_ref_set = PilotConceptRefSet(schema_version=1, records=concept_entries)
    concept_ids = {item.system_key: item.concept_id for item in concept_entries}
    raw_records = []
    provisional_records = []
    for document in sorted(calibration_documents, key=lambda item: item.document_key):
        unit = extractions_by_document[document.document_key].units[0]
        version_id = taxonomy_version_ids[document.system_key]
        concept_id = concept_ids[document.system_key]
        raw_records.append(
            PilotResolutionRecord(
                document_key=document.document_key,
                system_key=document.system_key,
                split="dev",
                requirement_unit_id=unit.unit_id,
                latency_ms=10,
                cost_usd=None,
                resolution=TaxonomyResolution(
                    schema_version=1,
                    status="mapped",
                    method="policy_auto",
                    taxonomy_version_id=version_id,
                    primary_concept_id=concept_id,
                    candidates=[
                        TaxonomyCandidate(
                            taxonomy_version_id=version_id,
                            concept_id=concept_id,
                            stable_key="product.sync",
                            score=0.95,
                            rank=1,
                            evidence=[unit.source_ref],
                        )
                    ],
                    confidence=0.95,
                    margin=0.95,
                    reason_code="fixture_match",
                    reason="测试夹具中的确定匹配。",
                    input_hash=_sha(f"resolution:{unit.unit_id}"),
                    taxonomy_manifest_hash=output_manifest_hashes[document.system_key],
                    policy_version=resolution_policy.canonical_hash,
                    model_revision="verify@1",
                    requirement_unit_ids=[unit.unit_id],
                ),
            )
        )
        provisional_records.append(
            TaxonomyGoldRecord(
                record_id=pilot_record_id(document.document_key, unit.unit_id),
                document_key=document.document_key,
                system_key=document.system_key,
                split="dev",
                requirement_unit_id=unit.unit_id,
                expected_disposition="reuse",
                expected_primary_stable_key="product.sync",
                expected_path=["business.assets", "product.sync"],
                gold_evidence=[unit.source_ref],
                eligible_for_auto=True,
            )
        )
    resolutions = PilotResolutionSet(
        schema_version=1,
        run_id=resolution_run_id,
        generated_at=NOW + timedelta(minutes=2),
        dataset_hash=calibration_dataset_hash,
        policy_hash=resolution_policy.canonical_hash,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
        taxonomy_version_ids=taxonomy_version_ids,
        output_manifest_hashes=output_manifest_hashes,
        records=raw_records,
    )
    predictions = project_resolution_predictions(
        resolutions=resolutions,
        concept_refs=concept_ref_set.by_concept_id,
        manifests=bootstrap_manifest_models,
        manifest_artifacts=manifest_artifacts,
    )
    calibration_provisional_gold = TaxonomyGoldSet(
        schema_version=1,
        corpus_id=corpus.corpus_id,
        dataset_hash=calibration_dataset_hash,
        review_method="model_assisted_provisional",
        reviewed_by="calibration-model:pilot-operator",
        reviewed_at=NOW + timedelta(minutes=2),
        records=provisional_records,
    )
    resolution_ref = _write_artifact_ref(
        root,
        f"{resolution_root}/raw/resolutions.json",
        "{}" if placeholder_calibration else resolutions.model_dump_json(),
    )
    concept_ref = _write_artifact_ref(
        root,
        f"{resolution_root}/artifacts/concept-refs.json",
        concept_ref_set.model_dump_json(),
    )
    prediction_ref = _write_artifact_ref(
        root,
        f"{resolution_root}/predictions/predictions.json",
        predictions.model_dump_json(),
    )
    provisional_gold_ref = _write_artifact_ref(
        root,
        f"{resolution_root}/reviews/calibration-gold-provisional.json",
        calibration_provisional_gold.model_dump_json(),
    )
    final_dataset_payload = dataset_seed.model_dump(mode="json")
    final_dataset_payload["gold_artifact"] = provisional_gold_ref
    final_dataset_payload["prediction_artifact"] = prediction_ref
    final_dataset = TaxonomyDatasetManifest.model_validate(final_dataset_payload)
    assert final_dataset.dataset_hash == calibration_dataset_hash
    dataset_ref = _write_artifact_ref(
        root,
        f"calibration-dataset-{resolution_run_id}.json",
        final_dataset.model_dump_json(),
    )
    calibration_payload = {
        "schema_version": 1,
        "calibration_dataset_hash": calibration_dataset_hash,
        "dataset": dataset_ref,
        "resolutions": resolution_ref,
        "concept_refs": concept_ref,
        "predictions": prediction_ref,
        "provisional_gold": provisional_gold_ref,
        "output_manifests": bootstrap_manifests,
        "output_manifest_hashes": output_manifest_hashes,
    }
    ledger.append(
        event_type="calibration_resolution_started",
        corpus=corpus,
        run_id=resolution_run_id,
        actor="pilot-operator",
    )
    ledger.append(
        event_type="calibration_resolution_completed",
        corpus=corpus,
        run_id=resolution_run_id,
        actor="pilot-operator",
        payload=calibration_payload,
    )


def _append_policy_freeze(ledger: PilotRunLedger, corpus):
    root = ledger.path.parent
    provisional_gold, independent_gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=independent_gold.dataset_hash,
    )
    attestation = _gold_attestation(
        corpus.corpus_id,
        provisional_gold,
        independent_gold,
        coverage_gold,
    )
    frozen_policy = build_pilot_frozen_policy(
        root=root,
        corpus=corpus,
        provisional_gold=provisional_gold,
        independent_gold=independent_gold,
        coverage_gold=coverage_gold,
        attestation=attestation,
        calibrated_at=NOW + timedelta(minutes=4),
        minimum_precision=0.95,
    )
    run_id = "freeze-policy-001"
    run_root = f"runs/calibration-policy/{run_id}"
    frozen_policy_ref = _write_artifact_ref(
        root,
        f"{run_root}/policies/frozen-policy.json",
        frozen_policy.model_dump_json(),
    )
    independent_gold_ref = _write_artifact_ref(
        root,
        f"{run_root}/reviews/calibration-gold-independent.json",
        independent_gold.model_dump_json(),
    )
    coverage_gold_ref = _write_artifact_ref(
        root,
        f"{run_root}/reviews/calibration-coverage-gold-independent.json",
        coverage_gold.model_dump_json(),
    )
    attestation_ref = _write_artifact_ref(
        root,
        f"{run_root}/reviews/gold-attestation.json",
        attestation.model_dump_json(),
    )
    ledger.append(
        event_type="calibration_policy_freeze_started",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
    )
    ledger.append(
        event_type="calibration_policy_freeze_completed",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={
            "schema_version": 1,
            "calibration_dataset_hash": independent_gold.dataset_hash,
            "frozen_policy_hash": frozen_policy.canonical_hash,
            "minimum_precision": 0.95,
            "minimum_auto_decisions": 1,
            "frozen_policy": frozen_policy_ref,
            "independent_gold": independent_gold_ref,
            "coverage_gold": coverage_gold_ref,
            "gold_attestation": attestation_ref,
        },
    )
    return verify_pilot_policy_freeze_artifacts(root=root, corpus=corpus)


def test_freeze_copies_exact_snapshots_without_leaking_original_paths(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    root = tmp_path / "pilot-run"

    corpus = freeze_pilot_corpus(
        spec=spec,
        output_dir=root,
        actor="pilot-preparer",
        run_id="pilot-run-001",
        frozen_at=NOW + timedelta(minutes=1),
    )

    serialized = (root / "frozen-corpus.json").read_text(encoding="utf-8")
    assert all(document.source_path not in serialized for document in spec.documents)
    assert load_frozen_corpus(root) == corpus
    assert {item.title for item in corpus.documents} == {
        "漫剧初版功能 PRD",
        "漫剧 1.5 PRD",
        "漫剧 2.0 PRD",
        "分销 v1.2 PRD",
        "分销 v1.3 PRD",
        "分销 API 优化 PRD",
    }
    assert all(item.canonicalization_revision == MARKDOWN_CANONICAL_SNAPSHOT_REVISION for item in corpus.documents)
    assert all(
        item.image_enrichment_revision == MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION for item in corpus.documents
    )
    assert all((root / item.raw_source.path).is_file() for item in corpus.documents)
    assert all((root / item.source.path).is_file() for item in corpus.documents)
    assert len(PilotRunLedger(root / "run-ledger.jsonl").read_events()) == 1
    locked = next(item for item in corpus.documents if item.split == "test")
    locked_mode = stat.S_IMODE((root / locked.source.path).stat().st_mode)
    assert locked_mode == 0o400

    with pytest.raises(PilotArtifactError, match="pilot_output_already_exists"):
        freeze_pilot_corpus(
            spec=spec,
            output_dir=root,
            actor="pilot-preparer",
            run_id="pilot-run-002",
        )


def test_corpus_v3_requires_independent_bootstrap_calibration_and_test_documents(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    without_calibration = [item for item in spec.documents if item.split != "calibration"]

    with pytest.raises(ValueError, match="pilot_system_split_incomplete"):
        PilotCorpusSpec(
            schema_version=3,
            corpus_id="missing-calibration",
            created_at=NOW,
            documents=without_calibration,
        )


def test_freeze_rejects_unimplemented_image_enrichment_revision(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    documents = list(spec.documents)
    documents[0] = documents[0].model_copy(update={"image_enrichment_revision": "vision-caption-v1"})
    mismatched = spec.model_copy(update={"documents": documents})

    with pytest.raises(PilotArtifactError, match="pilot_image_enrichment_revision_mismatch"):
        freeze_pilot_corpus(
            spec=mismatched,
            output_dir=tmp_path / "pilot-image-enrichment-mismatch",
            actor="pilot-preparer",
            run_id="pilot-image-enrichment-mismatch",
        )


def test_load_frozen_corpus_rejects_unbound_freeze_time(tmp_path: Path) -> None:
    root, _ = _freeze(tmp_path)
    corpus_path = root / "frozen-corpus.json"
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    payload["frozen_at"] = (NOW + timedelta(hours=1)).isoformat()
    corpus_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PilotArtifactError, match="pilot_frozen_corpus_ledger_binding_invalid"):
        load_frozen_corpus(root)


def test_freeze_binds_raw_source_and_production_canonical_snapshot(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    target = spec.documents[0]
    raw = "---\ntitle: 原始元数据\n---\n\n# 需求\n\n  正文。  \n"
    source_path = Path(target.source_path)
    source_path.write_text(raw, encoding="utf-8")
    canonical = canonicalize_markdown(raw)
    documents = [
        target.model_copy(
            update={
                "source_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "canonical_sha256": canonical.canonical_sha256,
            }
        ),
        *spec.documents[1:],
    ]
    updated = spec.model_copy(update={"documents": documents})

    root = tmp_path / "canonical-pilot"
    corpus = freeze_pilot_corpus(
        spec=updated,
        output_dir=root,
        actor="pilot-preparer",
        run_id="freeze-canonical",
        frozen_at=NOW + timedelta(minutes=1),
    )
    frozen = next(item for item in corpus.documents if item.document_key == target.document_key)

    assert frozen.raw_source.sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert frozen.source.sha256 == canonical.canonical_sha256
    assert (root / frozen.raw_source.path).read_text(encoding="utf-8") == raw
    assert (root / frozen.source.path).read_text(encoding="utf-8") == canonical.content
    assert frozen.raw_source.sha256 != frozen.source.sha256


def test_freeze_keeps_crlf_raw_bytes_separate_from_canonical_text_hash(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    target = spec.documents[0]
    raw_bytes = b"---\r\ntitle: PRD\r\n---\r\n\r\n# Requirement\r\n\r\nBody\r\n"
    source_path = Path(target.source_path)
    source_path.write_bytes(raw_bytes)
    canonical = canonicalize_markdown(source_path.read_text(encoding="utf-8"))
    documents = [
        target.model_copy(
            update={
                "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "canonical_sha256": canonical.canonical_sha256,
            }
        ),
        *spec.documents[1:],
    ]

    root = tmp_path / "crlf-pilot"
    corpus = freeze_pilot_corpus(
        spec=spec.model_copy(update={"documents": documents}),
        output_dir=root,
        actor="pilot-preparer",
        run_id="freeze-crlf",
        frozen_at=NOW + timedelta(minutes=1),
    )
    frozen = next(item for item in corpus.documents if item.document_key == target.document_key)

    assert (root / frozen.raw_source.path).read_bytes() == raw_bytes
    assert frozen.raw_source.sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert frozen.source.sha256 == canonical.canonical_sha256


def test_cli_cannot_preprocess_locked_test_as_a_standalone_stage(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "extract-units",
                "--root",
                str(tmp_path),
                "--split",
                "test",
                "--actor",
                "pilot-operator",
                "--run-id",
                "forbidden-test-preprocess",
            ]
        )


def test_cli_exposes_calibration_resolution_as_a_separate_stage(tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "resolve-calibration",
            "--root",
            str(tmp_path),
            "--actor",
            "pilot-operator",
            "--run-id",
            "calibration-001",
        ]
    )

    assert args.command == "resolve-calibration"


def test_cli_exposes_calibration_policy_freeze_with_independent_gold(tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "freeze-calibration-policy",
            "--root",
            str(tmp_path),
            "--independent-gold",
            str(tmp_path / "gold.json"),
            "--coverage-gold",
            str(tmp_path / "coverage.json"),
            "--actor",
            "qa-reviewer",
            "--run-id",
            "freeze-policy-001",
        ]
    )

    assert args.command == "freeze-calibration-policy"
    assert args.minimum_precision == 0.95
    assert args.minimum_auto_decisions == 1


def test_cli_exposes_one_shot_locked_test_without_test_preprocessing_command(tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "run-locked-test",
            "--root",
            str(tmp_path),
            "--source-gold",
            str(tmp_path / "test-source-gold.json"),
            "--gate",
            str(tmp_path / "gate.json"),
            "--actor",
            "test-owner",
            "--run-id",
            "locked-test-001",
        ]
    )

    assert args.command == "run-locked-test"
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "extract-units",
                "--root",
                str(tmp_path),
                "--split",
                "test",
                "--actor",
                "test-owner",
                "--run-id",
                "forbidden-test-preprocess",
            ]
        )


def test_bootstrap_snapshot_loader_never_reads_locked_test_path(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    read_paths: list[Path] = []

    def reader(path: Path) -> str:
        read_paths.append(path)
        return path.read_text(encoding="utf-8")

    snapshots = load_split_snapshots(corpus=corpus, root=root, split="bootstrap", reader=reader)

    assert set(snapshots) == {"motion-bootstrap", "distribution-bootstrap"}
    assert all("locked-test" not in str(path) for path in read_paths)
    with pytest.raises(PilotArtifactError, match="locked_test_read_not_authorized"):
        load_split_snapshots(corpus=corpus, root=root, split="test", reader=reader)


def test_bootstrap_artifact_loader_does_not_require_or_read_locked_test_units(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    run_id = "extract-bootstrap-001"
    run_root = root / "runs" / "requirement-extraction" / run_id
    documents = {}
    for document in (item for item in corpus.documents if item.split == "bootstrap"):
        path = run_root / f"{document.document_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        extraction = RequirementUnitExtractionResult(
            document_id=document.document_id,
            document_content_hash=document.source.sha256,
            input_hash="a" * 64,
            prompt_revision="requirement@1",
            model_revision="primary@1",
            chunk_count=0,
            units=[],
            coverage=[],
        )
        path.write_text(extraction.model_dump_json(), encoding="utf-8")
        documents[document.document_key] = _requirement_artifact_summary(
            root=root,
            path=path,
            extraction=extraction,
        )

    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    ledger.append(
        event_type="requirement_extraction_completed",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"schema_version": 1, "split": "bootstrap", "documents": documents},
    )

    extractions, paths = _load_bootstrap_extractions(root, corpus)

    assert set(extractions) == {"motion-bootstrap", "distribution-bootstrap"}
    assert set(paths) == {"motion-bootstrap", "distribution-bootstrap"}
    assert all("locked-test" not in str(path) for path in paths.values())


def test_requirement_completion_recomputes_section_count_from_frozen_snapshot(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    run_id = "extract-bootstrap-wrong-section-count"
    run_root = root / "runs" / "requirement-extraction" / run_id
    documents = {}
    for document in (item for item in corpus.documents if item.split == "bootstrap"):
        path = run_root / f"{document.document_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        extraction = RequirementUnitExtractionResult(
            document_id=document.document_id,
            document_content_hash=document.source.sha256,
            input_hash="a" * 64,
            prompt_revision="requirement@1",
            model_revision="primary@1",
            chunk_count=0,
            units=[],
            coverage=[],
        )
        path.write_text(extraction.model_dump_json(), encoding="utf-8")
        documents[document.document_key] = _requirement_artifact_summary(
            root=root,
            path=path,
            extraction=extraction,
            section_count=0,
        )
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    ledger.append(
        event_type="requirement_extraction_completed",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"schema_version": 1, "split": "bootstrap", "documents": documents},
    )

    with pytest.raises(PilotArtifactError, match="pilot_requirement_completion_summary_mismatch"):
        verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"bootstrap"})


def test_bootstrap_identity_contains_only_bootstrap_inputs(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    runtime_manifest = root / "runtime" / "model-bundle.json"
    runtime_manifest.parent.mkdir(parents=True, exist_ok=True)
    runtime_manifest.write_text('{"schema_version":1}\n', encoding="utf-8")
    extraction_paths = {}
    for document in (item for item in corpus.documents if item.split == "bootstrap"):
        path = root / "runs" / "requirement-extraction" / "extract-bootstrap-001" / f"{document.document_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        extraction_paths[document.document_key] = path
    bootstrap_policy = TaxonomyBootstrapPolicy(
        schema_version=1,
        max_units_per_batch=20,
        max_batch_chars=60_000,
        max_consolidation_chars=100_000,
        max_nodes=1_000,
        fail_behavior="draft_only",
    )
    resolution_policy = _frozen_policy(_independent_gold(corpus.corpus_id)).policy

    identity = _bootstrap_identity(
        root=root,
        corpus=corpus,
        extraction_paths=extraction_paths,
        bundle=build_environment_model_bundle(settings),
        bootstrap_policy=bootstrap_policy,
        resolution_policy=resolution_policy,
    )

    assert identity.artifact_kind == "bootstrap_identity"
    assert {item.document_key for item in identity.documents} == {
        "motion-bootstrap",
        "distribution-bootstrap",
    }
    assert "motion-test" not in identity.model_dump_json()
    assert len(identity.bootstrap_hash) == 64
    assert identity.runtime_manifest.sha256 == hashlib.sha256(runtime_manifest.read_bytes()).hexdigest()


def test_runtime_manifest_pins_strict_preprocessing_contract() -> None:
    manifest = _runtime_manifest(build_environment_model_bundle(settings))

    assert (
        manifest["preprocessing"]["canonical_image_enrichment_revision"] == MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION
    )
    assert manifest["preprocessing"]["feature_segmentation_enabled"] is settings.feature_seg_llm_enabled
    assert manifest["preprocessing"]["feature_segmentation_strict"] is True
    assert manifest["preprocessing"]["section_classification_strict"] is True
    assert manifest["preprocessing"]["taxonomy_source_inventory_revision"] == "markdown-heading-inventory-v1"
    assert manifest["preprocessing"]["feature_segmentation_used_for_taxonomy"] is False
    assert "feature-segmenter@" in manifest["preprocessing"]["feature_segmenter_prompt_revision"]
    assert "section-classifier@" in manifest["preprocessing"]["section_classifier_prompt_revision"]
    assert len(manifest["source_revision"]["git_commit"]) == 40
    assert isinstance(manifest["source_revision"]["worktree_dirty"], bool)
    assert manifest["execution"]["requirement_unit_concurrency"] == min(4, settings.llm_concurrency)


def test_source_revision_treats_untracked_executable_code_as_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            SimpleNamespace(stdout="a" * 40 + "\n"),
            SimpleNamespace(stdout="?? scripts/untracked_runner.py\n"),
        ]
    )
    monkeypatch.setattr(taxonomy_pilot_script.subprocess, "run", lambda *args, **kwargs: next(responses))

    revision = _source_revision()

    assert revision == {"git_commit": "a" * 40, "worktree_dirty": True}


def test_atomic_runtime_manifest_write_never_leaves_partial_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "runtime" / "model-bundle.json"

    def fail_link(source, destination) -> None:
        raise OSError("simulated atomic publish failure")

    monkeypatch.setattr(taxonomy_pilot_service.os, "link", fail_link)

    with pytest.raises(OSError, match="simulated atomic publish failure"):
        write_json_atomic_once(target, {"schema_version": 1})

    assert not target.exists()
    assert list(target.parent.glob(".*.tmp-*")) == []


def test_bootstrap_review_report_handles_multiple_top_level_nodes() -> None:
    unit = _unit()
    base = _manifest(unit)
    second_top = TaxonomyNodeManifest(
        stable_key="task.execution",
        node_type="module",
        display_name="任务执行",
        sort_order=1,
        node_status="active",
        definition="执行已配置任务。",
        scope_note="仅覆盖任务执行。",
        in_scope_examples=[
            TaxonomyExample(
                text=unit.source_quote,
                document_content_hash=unit.document_content_hash,
                requirement_unit_id=unit.unit_id,
            )
        ],
    )
    manifest = base.model_copy(update={"nodes": [*base.nodes, second_top]})
    result = TaxonomyBootstrapResult(
        input_hash="1" * 64,
        policy_version="2" * 64,
        proposal_prompt_revision="proposal@1",
        consolidation_prompt_revision="consolidate@1",
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
        draft_manifest=manifest,
        draft_manifest_hash=manifest_hash(manifest),
    )

    report = _review_report(bootstrap_hash="3" * 64, results={"motion": result})

    assert report.index("`business.assets`") < report.index("`task.execution`")


def test_strict_pilot_rejects_salvaged_truncated_json() -> None:
    issues = _strict_llm_telemetry_issues(
        [
            SimpleNamespace(schema_name="RequirementUnitDraftBatch", error=None),
            SimpleNamespace(schema_name="RequirementUnitDraftBatch", error="salvaged_truncated_json"),
        ]
    )

    assert issues == ["RequirementUnitDraftBatch:salvaged_truncated_json"]


def test_ungrounded_source_quote_blocks_pilot_extraction() -> None:
    extraction = _extraction_with_units(
        document_id=DOCUMENT_A,
        document_content_hash="a" * 64,
        units=[],
        source_ref="prd:商品 §同步",
        disposition="failed",
        issues=[
            RequirementUnitIssue(
                source_ref="prd:商品 §同步",
                chunk_index=1,
                code="source_quote_not_grounded",
            )
        ],
    )

    assert _blocking_extraction_issue_codes(extraction) == ["empty_extraction", "source_quote_not_grounded"]


def test_semantic_entailment_failure_blocks_pilot_extraction() -> None:
    unit = _unit()
    extraction = _extraction_with_units(
        document_id=unit.document_id,
        document_content_hash=unit.document_content_hash,
        source_ref=unit.source_ref,
        units=[unit.model_copy(update={"scope_status": "unsupported"})],
        issues=[
            RequirementUnitIssue(
                source_ref=unit.source_ref,
                code="semantic_evidence_not_entailed",
                details={"unit_id": unit.unit_id},
            )
        ],
    )

    assert _blocking_extraction_issue_codes(extraction) == ["semantic_evidence_not_entailed"]


def test_bootstrap_without_manifest_cannot_emit_completed_event() -> None:
    failed = TaxonomyBootstrapResult(
        input_hash="1" * 64,
        policy_version="2" * 64,
        proposal_prompt_revision="proposal@1",
        consolidation_prompt_revision="consolidate@1",
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
        issues=[
            {
                "code": "consolidation_model_failed",
                "requirement_unit_ids": [],
                "details": {"error_type": "TimeoutError"},
            }
        ],
    )

    with pytest.raises(PilotArtifactError, match="pilot_taxonomy_bootstrap_incomplete:motion"):
        _validate_bootstrap_results_for_completion({"motion": failed})


def test_ledger_rejects_placeholder_bootstrap_completion_receipt(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="taxonomy_bootstrap_started",
        corpus=corpus,
        run_id="bootstrap-placeholder",
        actor="pilot-operator",
    )

    with pytest.raises(PilotArtifactError, match="pilot_completion_receipt_invalid:taxonomy_bootstrap_completed"):
        ledger.append(
            event_type="taxonomy_bootstrap_completed",
            corpus=corpus,
            run_id="bootstrap-placeholder",
            actor="pilot-operator",
            payload={},
        )

    assert all(event.event_type != "taxonomy_bootstrap_completed" for event in ledger.read_events())


def test_ledger_rejects_untyped_locked_test_failure_receipt(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    reserve_locked_test(
        ledger=ledger,
        corpus=corpus,
        run_id="locked-test-untyped-failure",
        actor="pilot-operator",
        input_commitment=_locked_test_commitment(),
    )

    with pytest.raises(PilotArtifactError, match="pilot_completion_receipt_invalid:locked_test_failed"):
        ledger.append(
            event_type="locked_test_failed",
            corpus=corpus,
            run_id="locked-test-untyped-failure",
            actor="pilot-operator",
            payload={},
        )

    assert ledger.read_events()[-1].event_type == "locked_test_started"


def test_locked_test_quality_failure_findings_must_be_canonically_sorted() -> None:
    artifact = {"path": "runs/locked-test/test/artifact.json", "sha256": "a" * 64}
    payload = {
        "schema_version": 1,
        "failure_kind": "source_coverage_quality_gate",
        "error_type": "PilotSourceCoverageError",
        "test_dataset_hash": "b" * 64,
        "frozen_policy_hash": "c" * 64,
        "dataset": artifact,
        "requirement_extractions": {
            "motion-test": {
                "artifact": artifact,
                "section_count": 1,
                "chunk_count": 1,
                "unit_count": 0,
                "atomic_count": 0,
                "issue_count": 1,
            }
        },
        "resolutions": artifact,
        "concept_refs": artifact,
        "predictions": artifact,
        "source_gold": artifact,
        "source_coverage_metrics": artifact,
        "gate": artifact,
        "report": artifact,
        "output_manifests": {"motion": artifact},
        "output_manifest_hashes": {"motion": "d" * 64},
        "findings": ["z-finding", "a-finding"],
    }

    with pytest.raises(ValidationError, match="pilot_locked_test_quality_failure_findings_invalid"):
        PilotLockedTestFailureReceipt.model_validate(payload)


def test_locked_test_failure_replay_rejects_rehashed_start_payload(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    start = reserve_locked_test(
        ledger=ledger,
        corpus=corpus,
        run_id="locked-test-forged-start",
        actor="pilot-operator",
        input_commitment=_locked_test_commitment(),
    )
    ledger.append(
        event_type="locked_test_failed",
        corpus=corpus,
        run_id=start.run_id,
        actor="pilot-operator",
        payload=PilotLockedTestFailureReceipt(
            schema_version=1,
            failure_kind="execution",
            error_type="RuntimeError",
        ).model_dump(mode="json"),
    )

    rebuilt = []
    previous_hash = None
    for event in ledger.read_events():
        payload = event.payload
        if event.event_id == start.event_id:
            payload = {**payload, "forged_after_the_run": True}
        replacement = build_pilot_ledger_event(
            sequence=event.sequence,
            event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            corpus_id=event.corpus_id,
            source_commitment_hash=event.source_commitment_hash,
            run_id=event.run_id,
            actor=event.actor,
            payload=payload,
            previous_event_hash=previous_hash,
        )
        rebuilt.append(json.dumps(replacement.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        previous_hash = replacement.event_hash
    ledger.path.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")

    with pytest.raises(PilotArtifactError, match="pilot_locked_test_start_binding_invalid"):
        verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)


def test_locked_test_rejects_schema_valid_receipt_with_placeholder_artifacts(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus, placeholder_bootstrap=True)
    provisional_gold, gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(root, corpus, dataset_hash=gold.dataset_hash)

    with pytest.raises(PilotArtifactError, match="pilot_bootstrap_artifact_schema_invalid"):
        build_pilot_frozen_policy(
            root=root,
            corpus=corpus,
            provisional_gold=provisional_gold,
            independent_gold=gold,
            coverage_gold=coverage_gold,
            attestation=_gold_attestation(corpus.corpus_id, provisional_gold, gold, coverage_gold),
            calibrated_at=NOW + timedelta(minutes=4),
            minimum_precision=0.95,
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_bootstrap_completion_replay_binds_actual_resolution_policy_file(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    policy_path = (
        root / "runs" / "taxonomy-bootstrap" / "bootstrap-dev-001" / "policies" / "base-resolution-policy.json"
    )
    policy_path.write_text(
        _resolution_policy().model_copy(update={"minimum_score": 0.1}).model_dump_json(),
        encoding="utf-8",
    )

    with pytest.raises(PilotArtifactError, match="pilot_bootstrap_policy_binding_invalid"):
        verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)


def test_locked_test_rejects_placeholder_calibration_resolution_artifacts(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus, placeholder_calibration=True)
    provisional_gold, gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(root, corpus, dataset_hash=gold.dataset_hash)

    with pytest.raises(PilotArtifactError, match="pilot_calibration_artifact_schema_invalid"):
        build_pilot_frozen_policy(
            root=root,
            corpus=corpus,
            provisional_gold=provisional_gold,
            independent_gold=gold,
            coverage_gold=coverage_gold,
            attestation=_gold_attestation(corpus.corpus_id, provisional_gold, gold, coverage_gold),
            calibrated_at=NOW + timedelta(minutes=4),
            minimum_precision=0.95,
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_locked_test_rejects_gold_that_omits_calibration_units(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    incomplete_gold = _independent_gold(corpus.corpus_id)
    provisional_gold = _provisional_gold(incomplete_gold)
    coverage_gold = _calibration_coverage_gold(root, corpus, dataset_hash=incomplete_gold.dataset_hash)

    with pytest.raises(PilotArtifactError, match="pilot_calibration_gold_unit_coverage_invalid"):
        build_pilot_frozen_policy(
            root=root,
            corpus=corpus,
            provisional_gold=provisional_gold,
            independent_gold=incomplete_gold,
            coverage_gold=coverage_gold,
            attestation=_gold_attestation(
                corpus.corpus_id,
                provisional_gold,
                incomplete_gold,
                coverage_gold,
            ),
            calibrated_at=NOW + timedelta(minutes=4),
            minimum_precision=0.95,
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_locked_test_requires_completed_policy_freeze(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    with pytest.raises(
        PilotArtifactError,
        match="pilot_locked_test_prerequisites_missing:calibration_policy_freeze",
    ):
        reserve_locked_test(
            ledger=ledger,
            corpus=corpus,
            run_id="test-no-coverage-gold",
            actor="pilot-operator",
            input_commitment=_locked_test_commitment(),
        )


def test_frozen_policy_is_rebuilt_from_independent_calibration_evidence(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    provisional_gold, independent_gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=independent_gold.dataset_hash,
    )
    attestation = _gold_attestation(
        corpus.corpus_id,
        provisional_gold,
        independent_gold,
        coverage_gold,
    )

    frozen_policy = build_pilot_frozen_policy(
        root=root,
        corpus=corpus,
        provisional_gold=provisional_gold,
        independent_gold=independent_gold,
        coverage_gold=coverage_gold,
        attestation=attestation,
        calibrated_at=NOW + timedelta(minutes=4),
        minimum_precision=0.95,
    )

    calibration_event = next(
        event for event in ledger.read_events() if event.event_type == "calibration_resolution_completed"
    )
    predictions = TaxonomyPredictionSet.model_validate_json(
        (root / ArtifactRef.model_validate(calibration_event.payload["predictions"]).path).read_text(encoding="utf-8")
    )
    assert frozen_policy.schema_version == 2
    assert frozen_policy.calibration_prediction_hash == predictions.canonical_hash
    assert frozen_policy.calibration_gold_attestation_hash == attestation.canonical_hash
    assert frozen_policy.calibration_source_commitment_hash == corpus.source_commitment_hash
    assert frozen_policy.observed_requirement_extraction_recall == 1
    assert frozen_policy.observed_requirement_extraction_precision == 1


def test_calibration_coverage_verifier_rejects_locked_test_gold_shape(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    calibration = verify_pilot_calibration_artifacts(
        root=root,
        corpus=corpus,
        bootstrap=bootstrap,
    )
    calibration_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=calibration.dataset.dataset_hash,
    )
    locked_test_shape = calibration_gold.model_copy(
        update={
            "schema_version": 2,
            "dataset_hash": None,
            "source_commitment_hash": corpus.source_commitment_hash,
        }
    )

    with pytest.raises(PilotArtifactError, match="pilot_calibration_coverage_gold_binding_invalid"):
        verify_pilot_calibration_coverage_gold(
            root=root,
            corpus=corpus,
            calibration=calibration,
            coverage_gold=locked_test_shape,
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_calibration_coverage_fact_quote_must_match_bound_unit(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    calibration = verify_pilot_calibration_artifacts(root=root, corpus=corpus, bootstrap=bootstrap)
    coverage_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=calibration.dataset.dataset_hash,
    )
    payload = coverage_gold.model_dump(mode="json")
    fact = payload["records"][0]["facts"][0]
    wrong_quote = fact["source_quote"][:1]
    fact["source_quote"] = wrong_quote
    fact["source_quote_hash"] = build_source_quote_hash(wrong_quote)
    mismatched = PilotCoverageGoldSet.model_validate(payload)

    with pytest.raises(PilotArtifactError, match="pilot_calibration_coverage_fact_binding_invalid"):
        verify_pilot_calibration_coverage_gold(
            root=root,
            corpus=corpus,
            calibration=calibration,
            coverage_gold=mismatched,
        )


def test_calibration_overlap_fact_may_be_recovered_from_one_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    bootstrap = verify_pilot_bootstrap_artifacts(root=root, corpus=corpus)
    calibration = verify_pilot_calibration_artifacts(root=root, corpus=corpus, bootstrap=bootstrap)
    coverage_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=calibration.dataset.dataset_hash,
    )
    artifact_paths = verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"calibration"})
    document_key = sorted(artifact_paths)[0]
    extraction = RequirementUnitExtractionResult.model_validate_json(
        artifact_paths[document_key].read_text(encoding="utf-8")
    )
    original_coverage = extraction.coverage[0]
    duplicate_coverage = original_coverage.model_copy(
        update={
            "coverage_id": build_requirement_coverage_id(
                document_content_hash=extraction.document_content_hash,
                source_ref=original_coverage.source_ref,
                chunk_index=2,
                content_hash=original_coverage.content_hash,
            ),
            "chunk_index": 2,
            "chunk_count": 2,
            "disposition": "no_requirement",
            "requirement_unit_ids": [],
            "reason": "重叠窗口未重复抽取该事实。",
        }
    )
    modified_extraction = extraction.model_copy(
        update={
            "chunk_count": 2,
            "coverage": [
                original_coverage.model_copy(update={"chunk_count": 2}),
                duplicate_coverage,
            ],
        }
    )
    modified_path = tmp_path / "calibration-overlap-extraction.json"
    modified_path.write_text(modified_extraction.model_dump_json(), encoding="utf-8")
    artifact_paths[document_key] = modified_path
    source_record = next(item for item in coverage_gold.records if item.coverage_id == original_coverage.coverage_id)
    coverage_gold = PilotCoverageGoldSet.model_validate(
        {
            **coverage_gold.model_dump(mode="json"),
            "records": [
                *coverage_gold.records,
                source_record.model_copy(
                    update={
                        "coverage_id": duplicate_coverage.coverage_id,
                        "content_hash": duplicate_coverage.content_hash,
                    }
                ),
            ],
        }
    )
    monkeypatch.setattr(
        taxonomy_pilot_service,
        "verify_pilot_requirement_artifacts",
        lambda **_: artifact_paths,
    )

    metrics = verify_pilot_calibration_coverage_gold(
        root=root,
        corpus=corpus,
        calibration=calibration,
        coverage_gold=coverage_gold,
    )

    assert metrics.coverage_record_count == 3
    assert metrics.expected_fact_count == 2
    assert metrics.matched_fact_count == 2
    assert metrics.extracted_unit_count == 2


def test_locked_test_gold_is_derived_from_precommitted_source_facts_without_unit_ids(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    extractions, dataset, source_gold = _locked_test_source_gold_and_dataset(root, corpus)

    derived_gold, metrics = derive_locked_test_gold(
        root=root,
        corpus=corpus,
        dataset=dataset,
        extractions=extractions,
        source_gold=source_gold,
    )

    assert all(fact.matched_requirement_unit_id is None for record in source_gold.records for fact in record.facts)
    assert {record.document_key for record in derived_gold.records} == {
        "motion-test",
        "distribution-test",
    }
    assert {record.expected_primary_stable_key for record in derived_gold.records} == {"product.sync"}
    assert metrics.extraction_recall == 1
    assert metrics.extraction_precision == 1


def test_locked_test_overlap_references_count_one_source_fact_and_one_unit_once(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    extractions, dataset, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    document_key = sorted(extractions)[0]
    extraction = extractions[document_key]
    original_coverage = extraction.coverage[0]
    duplicate_coverage = original_coverage.model_copy(
        update={
            "coverage_id": build_requirement_coverage_id(
                document_content_hash=extraction.document_content_hash,
                source_ref=original_coverage.source_ref,
                chunk_index=2,
                content_hash=original_coverage.content_hash,
            ),
            "chunk_index": 2,
            "chunk_count": 2,
        }
    )
    extractions[document_key] = extraction.model_copy(
        update={
            "chunk_count": 2,
            "coverage": [
                original_coverage.model_copy(update={"chunk_count": 2}),
                duplicate_coverage,
            ],
        }
    )
    source_record = next(item for item in source_gold.records if item.coverage_id == original_coverage.coverage_id)
    source_gold = PilotCoverageGoldSet.model_validate(
        {
            **source_gold.model_dump(mode="json"),
            "records": [
                *source_gold.records,
                source_record.model_copy(
                    update={
                        "coverage_id": duplicate_coverage.coverage_id,
                        "content_hash": duplicate_coverage.content_hash,
                    }
                ),
            ],
        }
    )

    derived_gold, metrics = derive_locked_test_gold(
        root=root,
        corpus=corpus,
        dataset=dataset,
        extractions=extractions,
        source_gold=source_gold,
    )

    assert len(derived_gold.records) == 2
    assert metrics.expected_fact_count == 2
    assert metrics.matched_fact_count == 2
    assert metrics.extracted_unit_count == 2


def test_locked_test_overlap_fact_may_be_recovered_from_only_one_window(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    extractions, dataset, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    document_key = sorted(extractions)[0]
    extraction = extractions[document_key]
    original_coverage = extraction.coverage[0]
    duplicate_coverage = original_coverage.model_copy(
        update={
            "coverage_id": build_requirement_coverage_id(
                document_content_hash=extraction.document_content_hash,
                source_ref=original_coverage.source_ref,
                chunk_index=2,
                content_hash=original_coverage.content_hash,
            ),
            "chunk_index": 2,
            "chunk_count": 2,
            "disposition": "no_requirement",
            "requirement_unit_ids": [],
            "reason": "重叠窗口未重复抽取该事实。",
        }
    )
    extractions[document_key] = extraction.model_copy(
        update={
            "chunk_count": 2,
            "coverage": [
                original_coverage.model_copy(update={"chunk_count": 2}),
                duplicate_coverage,
            ],
        }
    )
    source_record = next(item for item in source_gold.records if item.coverage_id == original_coverage.coverage_id)
    source_gold = PilotCoverageGoldSet.model_validate(
        {
            **source_gold.model_dump(mode="json"),
            "records": [
                *source_gold.records,
                source_record.model_copy(
                    update={
                        "coverage_id": duplicate_coverage.coverage_id,
                        "content_hash": duplicate_coverage.content_hash,
                    }
                ),
            ],
        }
    )

    derived_gold, metrics = derive_locked_test_gold(
        root=root,
        corpus=corpus,
        dataset=dataset,
        extractions=extractions,
        source_gold=source_gold,
    )

    assert len(derived_gold.records) == 2
    assert metrics.expected_fact_count == 2
    assert metrics.matched_fact_count == 2
    assert metrics.extracted_unit_count == 2


def test_locked_test_fact_id_reuse_requires_same_overlapping_section(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    extractions, dataset, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    document_key = sorted(extractions)[0]
    extraction = extractions[document_key]
    original_coverage = extraction.coverage[0]
    unrelated_source_ref = f"{original_coverage.source_ref}-另一个章节"
    unrelated_coverage = original_coverage.model_copy(
        update={
            "coverage_id": build_requirement_coverage_id(
                document_content_hash=extraction.document_content_hash,
                source_ref=unrelated_source_ref,
                chunk_index=1,
                content_hash=original_coverage.content_hash,
            ),
            "source_ref": unrelated_source_ref,
            "heading": "另一个章节",
            "disposition": "no_requirement",
            "requirement_unit_ids": [],
            "reason": "无独立需求。",
        }
    )
    extractions[document_key] = extraction.model_copy(
        update={
            "chunk_count": 2,
            "coverage": [original_coverage, unrelated_coverage],
        }
    )
    source_record = next(item for item in source_gold.records if item.coverage_id == original_coverage.coverage_id)
    source_gold = PilotCoverageGoldSet.model_validate(
        {
            **source_gold.model_dump(mode="json"),
            "records": [
                *source_gold.records,
                source_record.model_copy(
                    update={
                        "coverage_id": unrelated_coverage.coverage_id,
                        "source_ref": unrelated_source_ref,
                        "content_hash": unrelated_coverage.content_hash,
                    }
                ),
            ],
        }
    )

    with pytest.raises(PilotArtifactError, match="pilot_locked_test_source_gold_fact_overlap_invalid"):
        derive_locked_test_gold(
            root=root,
            corpus=corpus,
            dataset=dataset,
            extractions=extractions,
            source_gold=source_gold,
        )


def test_coverage_gold_rejects_conflicting_reuse_of_fact_id(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    payload = source_gold.model_dump(mode="json")
    duplicate = json.loads(json.dumps(payload["records"][0]))
    duplicate["coverage_id"] = f"rc_{'f' * 64}"
    duplicate["facts"][0]["statement"] = "与原事实冲突的人工标签。"
    payload["records"].append(duplicate)

    with pytest.raises(ValueError, match="pilot_coverage_gold_fact_identity_conflict"):
        PilotCoverageGoldSet.model_validate(payload)


def test_coverage_gold_rejects_fact_id_reuse_across_documents(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    payload = source_gold.model_dump(mode="json")
    payload["records"][1]["facts"][0] = json.loads(json.dumps(payload["records"][0]["facts"][0]))

    with pytest.raises(ValueError, match="pilot_coverage_gold_fact_cross_document"):
        PilotCoverageGoldSet.model_validate(payload)


def test_locked_test_source_gold_rejects_model_generated_unit_id_binding(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    extractions, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    payload = source_gold.model_dump(mode="json")
    first_document = sorted(extractions)[0]
    payload["records"][0]["facts"][0]["matched_requirement_unit_id"] = extractions[first_document].units[0].unit_id

    with pytest.raises(ValueError, match="pilot_locked_test_gold_must_be_hidden_from_extraction"):
        PilotCoverageGoldSet.model_validate(payload)


@pytest.mark.parametrize(
    ("schema_version", "dataset_hash", "source_commitment_hash", "expected_error"),
    [
        (1, "a" * 64, None, "pilot_coverage_gold_test_schema_invalid"),
        (2, None, "b" * 64, "pilot_coverage_gold_calibration_schema_invalid"),
    ],
)
def test_coverage_gold_schema_version_is_bound_to_split(
    tmp_path: Path,
    schema_version: int,
    dataset_hash: str | None,
    source_commitment_hash: str | None,
    expected_error: str,
) -> None:
    root, corpus = _freeze(tmp_path)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    payload = source_gold.model_dump(mode="json")
    payload.update(
        {
            "schema_version": schema_version,
            "dataset_hash": dataset_hash,
            "source_commitment_hash": source_commitment_hash,
        }
    )
    if "calibration" in expected_error:
        for record in payload["records"]:
            record["split"] = "calibration"
            for fact in record["facts"]:
                fact["taxonomy_expectation"] = None

    with pytest.raises(ValidationError, match=expected_error):
        PilotCoverageGoldSet.model_validate(payload)


def test_policy_freeze_command_persists_replayable_completion_receipt(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _, independent_gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(
        root,
        corpus,
        dataset_hash=independent_gold.dataset_hash,
    )
    independent_path = tmp_path / "independent-gold.json"
    coverage_path = tmp_path / "coverage-gold.json"
    independent_path.write_text(independent_gold.model_dump_json(), encoding="utf-8")
    coverage_path.write_text(coverage_gold.model_dump_json(), encoding="utf-8")

    result = taxonomy_pilot_script._freeze_calibration_policy(
        SimpleNamespace(
            root=root,
            independent_gold=independent_path,
            coverage_gold=coverage_path,
            actor="policy-owner",
            run_id="policy-cli-001",
            minimum_precision=0.95,
            minimum_auto_decisions=1,
        )
    )

    verified = verify_pilot_policy_freeze_artifacts(root=root, corpus=corpus)
    assert result["frozen_policy_hash"] == verified.frozen_policy.canonical_hash
    assert verified.receipt.minimum_precision == 0.95
    assert verified.frozen_policy.schema_version == 2


def test_one_shot_locked_test_completes_with_hidden_source_gold_and_fake_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    source_gold_path = tmp_path / "locked-source-gold.json"
    gate_path = tmp_path / "locked-gate.json"
    source_gold_path.write_text(source_gold.model_dump_json(), encoding="utf-8")
    gate_path.write_text(
        TaxonomyEvaluationGate(
            minimum_semantic_stability=0,
            require_new_node_baseline=False,
            require_operational_thresholds=False,
            require_complete_corpus=True,
        ).model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(taxonomy_pilot_script, "_pin_runtime", lambda root, bundle: None)

    async def fake_extract(*, root, corpus, split, output_dir, bundle, allow_locked_test=False):
        assert split == "test"
        assert allow_locked_test is True
        extractions = {}
        summaries = {}
        for document in sorted(
            (item for item in corpus.documents if item.split == "test"),
            key=lambda item: item.document_key,
        ):
            snapshot = (root / document.source.path).read_text(encoding="utf-8")
            source_ref = f"prd:{document.title} §测试章节"
            unit = RequirementUnit(
                unit_id=build_requirement_unit_id(
                    document_content_hash=document.source.sha256,
                    source_ref=source_ref,
                    statement=snapshot,
                ),
                system_id=document.system_id,
                document_id=document.document_id,
                document_content_hash=document.source.sha256,
                source_ref=source_ref,
                source_quote=snapshot,
                source_quote_hash=build_source_quote_hash(snapshot),
                structural_key=f"{document.system_key}.fixture",
                title="测试需求",
                statement=snapshot,
                observable_outcome=snapshot,
                scope_status="atomic",
            )
            extraction = _extraction_with_units(
                document_id=document.document_id,
                document_content_hash=document.source.sha256,
                source_ref=source_ref,
                units=[unit],
            )
            path = output_dir / f"{document.document_key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(extraction.model_dump_json(), encoding="utf-8")
            extractions[document.document_key] = extraction
            summaries[document.document_key] = _requirement_artifact_summary(
                root=root,
                path=path,
                extraction=extraction,
            )
        return extractions, summaries

    monkeypatch.setattr(taxonomy_pilot_script, "_extract_split_requirement_units", fake_extract)
    monkeypatch.setattr(taxonomy_pilot_script, "_resolve_split_units", _fake_locked_test_resolve)

    result = asyncio.run(
        taxonomy_pilot_script._run_locked_test(
            SimpleNamespace(
                root=root,
                source_gold=source_gold_path,
                gate=gate_path,
                actor="locked-test-owner",
                run_id="locked-test-fake-001",
            )
        )
    )

    events = ledger.read_events()
    assert result["overall_status"] == "pass"
    assert result["source_coverage_recall"] == 1
    assert events[-2].event_type == "locked_test_started"
    assert events[-1].event_type == "locked_test_completed"
    assert events[-1].payload["test_dataset_hash"] == result["dataset_hash"]
    verified = verify_pilot_locked_test_artifacts(root=root, corpus=corpus)
    assert verified.evaluation.overall_status == "pass"
    assert verified.dataset.dataset_hash == result["dataset_hash"]


def test_failed_one_shot_consumes_locked_test_before_test_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    source_gold_path = tmp_path / "locked-source-gold.json"
    gate_path = tmp_path / "locked-gate.json"
    source_gold_path.write_text(source_gold.model_dump_json(), encoding="utf-8")
    gate_path.write_text(TaxonomyEvaluationGate().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(taxonomy_pilot_script, "_pin_runtime", lambda root, bundle: None)

    async def fail_extraction(**kwargs):
        raise RuntimeError("synthetic extraction crash")

    monkeypatch.setattr(taxonomy_pilot_script, "_extract_split_requirement_units", fail_extraction)
    args = SimpleNamespace(
        root=root,
        source_gold=source_gold_path,
        gate=gate_path,
        actor="locked-test-owner",
        run_id="locked-test-failed-001",
    )

    with pytest.raises(RuntimeError, match="synthetic extraction crash"):
        asyncio.run(taxonomy_pilot_script._run_locked_test(args))
    events = ledger.read_events()
    assert [event.event_type for event in events][-2:] == [
        "locked_test_started",
        "locked_test_failed",
    ]
    failure_receipt = PilotLockedTestFailureReceipt.model_validate(events[-1].payload)
    assert failure_receipt.failure_kind == "execution"
    assert failure_receipt.error_type == "RuntimeError"
    verified_failure = verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)
    assert verified_failure.source_coverage_metrics is None

    with pytest.raises(LockedTestAlreadyConsumedError, match="locked_test_already_consumed"):
        asyncio.run(
            taxonomy_pilot_script._run_locked_test(
                SimpleNamespace(**{**vars(args), "run_id": "locked-test-retry-forbidden"})
            )
        )


def test_locked_test_rejects_committed_input_drift_before_model_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    _, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    source_gold_path = tmp_path / "locked-source-gold.json"
    gate_path = tmp_path / "locked-gate.json"
    source_gold_path.write_text(source_gold.model_dump_json(), encoding="utf-8")
    gate_path.write_text(TaxonomyEvaluationGate().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(taxonomy_pilot_script, "_pin_runtime", lambda root, bundle: None)
    original_copy = taxonomy_pilot_script._copy_file_once

    def copy_with_drift(source: Path, target: Path) -> None:
        original_copy(source, target)
        if source == source_gold_path:
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    async def extraction_must_not_run(**kwargs):
        raise AssertionError("输入 commitment 漂移时不得开始模型提取")

    monkeypatch.setattr(taxonomy_pilot_script, "_copy_file_once", copy_with_drift)
    monkeypatch.setattr(taxonomy_pilot_script, "_extract_split_requirement_units", extraction_must_not_run)

    with pytest.raises(PilotArtifactError, match="pilot_locked_test_committed_input_changed"):
        asyncio.run(
            taxonomy_pilot_script._run_locked_test(
                SimpleNamespace(
                    root=root,
                    source_gold=source_gold_path,
                    gate=gate_path,
                    actor="locked-test-owner",
                    run_id="locked-test-input-drift",
                )
            )
        )

    failure = PilotLockedTestFailureReceipt.model_validate(ledger.read_events()[-1].payload)
    assert failure.failure_kind == "execution"
    assert failure.error_type == "PilotArtifactError"


def test_locked_test_does_not_open_hidden_source_gold_before_predictions_are_fixed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    source_extractions, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    source_gold_path = tmp_path / "locked-source-gold.json"
    gate_path = tmp_path / "locked-gate.json"
    source_gold_path.write_text(source_gold.model_dump_json(), encoding="utf-8")
    gate_path.write_text(TaxonomyEvaluationGate().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(taxonomy_pilot_script, "_pin_runtime", lambda root, bundle: None)
    call_order: list[str] = []

    async def fake_extract(*, root, corpus, split, output_dir, bundle, allow_locked_test=False):
        summaries = {}
        for document_key, extraction in sorted(source_extractions.items()):
            path = output_dir / f"{document_key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(extraction.model_dump_json(), encoding="utf-8")
            summaries[document_key] = _requirement_artifact_summary(
                root=root,
                path=path,
                extraction=extraction,
            )
        return source_extractions, summaries

    async def fail_after_prediction_start(**kwargs):
        call_order.append("resolve")
        raise RuntimeError("synthetic resolver crash")

    original_validate_json = PilotCoverageGoldSet.model_validate_json

    def track_source_gold(cls, value, *args, **kwargs):
        decoded = json.loads(value)
        if decoded.get("schema_version") == 2:
            call_order.append("source_gold")
        return original_validate_json(value, *args, **kwargs)

    monkeypatch.setattr(taxonomy_pilot_script, "_extract_split_requirement_units", fake_extract)
    monkeypatch.setattr(taxonomy_pilot_script, "_resolve_split_units", fail_after_prediction_start)
    monkeypatch.setattr(PilotCoverageGoldSet, "model_validate_json", classmethod(track_source_gold))

    with pytest.raises(RuntimeError, match="synthetic resolver crash"):
        asyncio.run(
            taxonomy_pilot_script._run_locked_test(
                SimpleNamespace(
                    root=root,
                    source_gold=source_gold_path,
                    gate=gate_path,
                    actor="locked-test-owner",
                    run_id="locked-test-hidden-gold-order",
                )
            )
        )

    assert call_order == ["resolve"]


def test_locked_test_reports_extraction_recall_failure_instead_of_hiding_missing_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    source_extractions, _, source_gold = _locked_test_source_gold_and_dataset(root, corpus)
    source_gold_path = tmp_path / "locked-source-gold.json"
    gate_path = tmp_path / "locked-gate.json"
    source_gold_path.write_text(source_gold.model_dump_json(), encoding="utf-8")
    gate_path.write_text(TaxonomyEvaluationGate().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(taxonomy_pilot_script, "_pin_runtime", lambda root, bundle: None)

    async def extraction_with_one_missing_fact(*, root, corpus, split, output_dir, bundle, allow_locked_test=False):
        extractions = {}
        summaries = {}
        missing_document = sorted(source_extractions)[0]
        for document_key, source_extraction in sorted(source_extractions.items()):
            extraction = source_extraction
            if document_key == missing_document:
                source_unit = source_extraction.units[0]
                wrong_quote = source_unit.source_quote[:1]
                wrong_statement = f"{wrong_quote}被错误识别为独立需求。"
                wrong_unit = RequirementUnit(
                    unit_id=build_requirement_unit_id(
                        document_content_hash=source_extraction.document_content_hash,
                        source_ref=source_unit.source_ref,
                        statement=wrong_statement,
                    ),
                    system_id=source_unit.system_id,
                    document_id=source_unit.document_id,
                    document_content_hash=source_extraction.document_content_hash,
                    source_ref=source_unit.source_ref,
                    source_quote=wrong_quote,
                    source_quote_hash=build_source_quote_hash(wrong_quote),
                    structural_key="fixture.wrong-extraction",
                    title="错误抽取",
                    statement=wrong_statement,
                    observable_outcome="形成一条与完整来源事实不匹配的 unit。",
                    scope_status="atomic",
                )
                extraction = _extraction_with_units(
                    document_id=source_extraction.document_id,
                    document_content_hash=source_extraction.document_content_hash,
                    source_ref=source_extraction.coverage[0].source_ref,
                    units=[wrong_unit],
                )
            path = output_dir / f"{document_key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(extraction.model_dump_json(), encoding="utf-8")
            extractions[document_key] = extraction
            summaries[document_key] = _requirement_artifact_summary(
                root=root,
                path=path,
                extraction=extraction,
            )
        return extractions, summaries

    monkeypatch.setattr(
        taxonomy_pilot_script,
        "_extract_split_requirement_units",
        extraction_with_one_missing_fact,
    )
    monkeypatch.setattr(taxonomy_pilot_script, "_resolve_split_units", _fake_locked_test_resolve)

    with pytest.raises(PilotSourceCoverageError, match="source_coverage_gate_failed"):
        asyncio.run(
            taxonomy_pilot_script._run_locked_test(
                SimpleNamespace(
                    root=root,
                    source_gold=source_gold_path,
                    gate=gate_path,
                    actor="locked-test-owner",
                    run_id="locked-test-coverage-fail",
                )
            )
        )

    failed = ledger.read_events()[-1]
    assert failed.event_type == "locked_test_failed"
    failure_receipt = PilotLockedTestFailureReceipt.model_validate(failed.payload)
    assert failure_receipt.failure_kind == "source_coverage_quality_gate"
    assert failure_receipt.dataset is not None
    assert failure_receipt.resolutions is not None
    assert failure_receipt.concept_refs is not None
    assert failure_receipt.predictions is not None
    assert failure_receipt.source_coverage_metrics is not None
    assert failure_receipt.report is not None
    metrics_ref = failure_receipt.source_coverage_metrics
    metrics = json.loads((root / metrics_ref.path).read_text(encoding="utf-8"))
    assert metrics["matched_fact_count"] < metrics["expected_fact_count"]
    assert (root / failure_receipt.report.path).is_file()
    verified_failure = verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)
    assert verified_failure.source_coverage_metrics is not None
    assert verified_failure.source_coverage_metrics.matched_fact_count < metrics["expected_fact_count"]
    dataset_path = root / failure_receipt.dataset.path
    original_dataset = dataset_path.read_text(encoding="utf-8")
    original_ledger = ledger.path.read_text(encoding="utf-8")
    forged_dataset = json.loads(original_dataset)
    forged_dataset["prediction_artifact"]["path"] = "runs/locked-test/forged/predictions.json"
    dataset_path.write_text(json.dumps(forged_dataset, ensure_ascii=False), encoding="utf-8")
    rebuilt_events = []
    previous_hash = None
    for event in ledger.read_events():
        payload = event.payload
        if event.event_id == failed.event_id:
            payload = {
                **payload,
                "dataset": {
                    **payload["dataset"],
                    "sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                },
            }
        replacement = build_pilot_ledger_event(
            sequence=event.sequence,
            event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            corpus_id=event.corpus_id,
            source_commitment_hash=event.source_commitment_hash,
            run_id=event.run_id,
            actor=event.actor,
            payload=payload,
            previous_event_hash=previous_hash,
        )
        rebuilt_events.append(json.dumps(replacement.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        previous_hash = replacement.event_hash
    ledger.path.write_text("\n".join(rebuilt_events) + "\n", encoding="utf-8")
    with pytest.raises(PilotArtifactError, match="pilot_locked_test_failure_dataset_binding_invalid"):
        verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)
    dataset_path.write_text(original_dataset, encoding="utf-8")
    ledger.path.write_text(original_ledger, encoding="utf-8")
    prediction_path = root / failure_receipt.predictions.path
    original_prediction = prediction_path.read_text(encoding="utf-8")
    prediction_path.write_text(original_prediction + "\n", encoding="utf-8")
    with pytest.raises(PilotArtifactError, match="pilot_locked_test_failure_prediction_artifact_invalid"):
        verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)
    prediction_path.write_text(original_prediction, encoding="utf-8")
    report_path = root / failure_receipt.report.path
    report_path.write_text(report_path.read_text(encoding="utf-8") + "\n篡改", encoding="utf-8")
    with pytest.raises(PilotArtifactError, match="pilot_locked_test_failure_report_artifact_invalid"):
        verify_pilot_locked_test_failure_artifacts(root=root, corpus=corpus)


def test_failed_extraction_run_does_not_block_a_new_run(tmp_path: Path) -> None:
    root = tmp_path / "pilot-run"
    failed = _prepare_extraction_run(root, "extract-dev-001")
    (failed / "partial.json").write_text("{}", encoding="utf-8")

    retry = _prepare_extraction_run(root, "extract-dev-002")
    (retry / "complete.json").write_text("{}", encoding="utf-8")

    assert failed.is_dir()
    assert retry.is_dir()
    assert failed != retry
    with pytest.raises(PilotArtifactError, match="pilot_requirement_run_already_exists"):
        _prepare_extraction_run(root, "extract-dev-002")


def test_ledger_detects_tampering_and_locked_test_is_one_shot(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    _append_policy_freeze(ledger, corpus)
    reserve_locked_test(
        ledger=ledger,
        corpus=corpus,
        run_id="test-run-001",
        actor="pilot-operator",
        input_commitment=_locked_test_commitment(),
    )

    with pytest.raises(LockedTestAlreadyConsumedError, match="locked_test_already_consumed"):
        reserve_locked_test(
            ledger=ledger,
            corpus=corpus,
            run_id="test-run-002",
            actor="pilot-operator",
            input_commitment=_locked_test_commitment(),
        )

    lines = (root / "run-ledger.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["actor"] = "forged-actor"
    lines[0] = json.dumps(tampered, ensure_ascii=False)
    (root / "run-ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(PilotArtifactError, match="pilot_ledger_event_invalid:1"):
        ledger.read_events()


def test_locked_test_reservation_rejects_unattested_or_self_labeled_gold(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    provisional_gold, gold = _completed_calibration_gold(root)
    coverage_gold = _calibration_coverage_gold(root, corpus, dataset_hash=gold.dataset_hash)
    mismatched_attestation = _gold_attestation(
        corpus.corpus_id,
        provisional_gold,
        gold,
        coverage_gold,
    ).model_copy(update={"independent_gold_hash": "8" * 64})
    self_reviewed = _gold_attestation(
        corpus.corpus_id,
        provisional_gold,
        gold,
        coverage_gold,
    ).model_dump(mode="json")
    self_reviewed["reviewed_by"] = self_reviewed["provisional_reviewed_by"]

    with pytest.raises(ValueError, match="pilot_gold_reviewer_not_independent"):
        PilotGoldReviewAttestation.model_validate(self_reviewed)

    with pytest.raises(PilotArtifactError, match="pilot_independent_gold_attestation_mismatch"):
        build_pilot_frozen_policy(
            root=root,
            corpus=corpus,
            provisional_gold=provisional_gold,
            independent_gold=gold,
            coverage_gold=coverage_gold,
            attestation=mismatched_attestation,
            calibrated_at=NOW + timedelta(minutes=4),
            minimum_precision=0.95,
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_locked_test_reservation_cannot_predate_frozen_policy(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    _append_locked_test_prerequisites(ledger, corpus)
    policy_freeze = _append_policy_freeze(ledger, corpus)
    frozen_policy = policy_freeze.frozen_policy

    with pytest.raises(PilotArtifactError, match="pilot_locked_test_precedes_policy_freeze"):
        reserve_locked_test(
            ledger=ledger,
            corpus=corpus,
            run_id="test-run-too-early",
            actor="pilot-operator",
            input_commitment=_locked_test_commitment(),
            occurred_at=frozen_policy.calibrated_at - timedelta(seconds=1),
        )

    assert all(event.event_type != "locked_test_started" for event in ledger.read_events())


def test_requirement_completion_rejects_placeholder_json_artifact(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    run_id = "extract-placeholder"
    documents = {}
    for item in (item for item in corpus.documents if item.split == "bootstrap"):
        path = root / "runs" / "requirement-extraction" / run_id / f"{item.document_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        documents[item.document_key] = {
            "artifact": {
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            "section_count": 0,
            "chunk_count": 0,
            "unit_count": 0,
            "atomic_count": 0,
            "issue_count": 0,
        }
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    ledger.append(
        event_type="requirement_extraction_completed",
        corpus=corpus,
        run_id=run_id,
        actor="pilot-operator",
        payload={"schema_version": 1, "split": "bootstrap", "documents": documents},
    )

    with pytest.raises(PilotArtifactError, match="pilot_requirement_artifact_schema_invalid"):
        verify_pilot_requirement_artifacts(root=root, corpus=corpus, splits={"bootstrap"})


def test_ledger_append_is_atomic_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    original = ledger.path.read_bytes()
    real_replace = taxonomy_pilot_service.os.replace

    def fail_ledger_replace(source, target) -> None:
        if Path(target) == ledger.path:
            raise OSError("simulated replace failure")
        real_replace(source, target)

    monkeypatch.setattr(taxonomy_pilot_service.os, "replace", fail_ledger_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        ledger.append(
            event_type="requirement_extraction_started",
            corpus=corpus,
            run_id="extract-bootstrap-001",
            actor="pilot-operator",
            payload={"split": "bootstrap"},
        )

    assert ledger.path.read_bytes() == original
    assert len(ledger.read_events()) == 1


def test_ledger_enforces_unique_run_ids_and_start_terminal_lifecycle(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    orphan_ledger = PilotRunLedger(root / "orphan-ledger.jsonl")
    with pytest.raises(PilotArtifactError, match="pilot_ledger_corpus_event_missing"):
        orphan_ledger.append(
            event_type="requirement_extraction_started",
            corpus=corpus,
            run_id="orphan-extract-001",
            actor="pilot-operator",
        )

    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id="extract-bootstrap-001",
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )

    with pytest.raises(PilotArtifactError, match="pilot_run_id_already_used"):
        ledger.append(
            event_type="taxonomy_bootstrap_started",
            corpus=corpus,
            run_id=" extract-bootstrap-001 ",
            actor="pilot-operator",
        )
    with pytest.raises(PilotArtifactError, match="pilot_stage_terminal_without_start"):
        ledger.append(
            event_type="taxonomy_bootstrap_completed",
            corpus=corpus,
            run_id="bootstrap-dev-unknown",
            actor="pilot-operator",
        )
    with pytest.raises(PilotArtifactError, match="pilot_ledger_time_regression"):
        ledger.append(
            event_type="taxonomy_bootstrap_started",
            corpus=corpus,
            run_id="bootstrap-time-regression",
            actor="pilot-operator",
            occurred_at=NOW,
        )
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id="extract-bootstrap-concurrent",
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    completion_payload = {
        "schema_version": 1,
        "split": "bootstrap",
        "documents": {
            "syntactic-fixture": {
                "artifact": {"path": "syntactic.json", "sha256": "a" * 64},
                "section_count": 0,
                "chunk_count": 0,
                "unit_count": 0,
                "atomic_count": 0,
                "issue_count": 0,
            }
        },
    }

    ledger.append(
        event_type="requirement_extraction_completed",
        corpus=corpus,
        run_id="extract-bootstrap-001",
        actor="pilot-operator",
        payload=completion_payload,
    )
    with pytest.raises(PilotArtifactError, match="pilot_requirement_split_already_completed:bootstrap"):
        ledger.append(
            event_type="requirement_extraction_completed",
            corpus=corpus,
            run_id="extract-bootstrap-concurrent",
            actor="pilot-operator",
            payload=completion_payload,
        )
    ledger.append(
        event_type="requirement_extraction_failed",
        corpus=corpus,
        run_id="extract-bootstrap-concurrent",
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    with pytest.raises(PilotArtifactError, match="pilot_requirement_split_already_completed:bootstrap"):
        ledger.append(
            event_type="requirement_extraction_started",
            corpus=corpus,
            run_id="extract-bootstrap-002",
            actor="pilot-operator",
            payload={"split": "bootstrap"},
        )
    with pytest.raises(PilotArtifactError, match="pilot_stage_already_terminal"):
        ledger.append(
            event_type="requirement_extraction_failed",
            corpus=corpus,
            run_id="extract-bootstrap-001",
            actor="pilot-operator",
            payload={"split": "bootstrap"},
        )


def test_ledger_replay_rejects_rehashed_terminal_without_start(tmp_path: Path) -> None:
    root, corpus = _freeze(tmp_path)
    ledger = PilotRunLedger(root / "run-ledger.jsonl")
    ledger.append(
        event_type="requirement_extraction_started",
        corpus=corpus,
        run_id="extract-replay-001",
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    ledger.append(
        event_type="requirement_extraction_failed",
        corpus=corpus,
        run_id="extract-replay-001",
        actor="pilot-operator",
        payload={"split": "bootstrap"},
    )
    original_events = ledger.read_events()
    freeze_event = original_events[0]
    terminal_event = original_events[-1]
    forged_terminal = build_pilot_ledger_event(
        sequence=2,
        event_id=terminal_event.event_id,
        event_type=terminal_event.event_type,
        occurred_at=terminal_event.occurred_at,
        corpus_id=terminal_event.corpus_id,
        source_commitment_hash=terminal_event.source_commitment_hash,
        run_id=terminal_event.run_id,
        actor=terminal_event.actor,
        payload=terminal_event.payload,
        previous_event_hash=freeze_event.event_hash,
    )
    ledger.path.write_text(
        "\n".join(
            json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for event in (freeze_event, forged_terminal)
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PilotArtifactError, match="pilot_stage_terminal_without_start"):
        ledger.read_events()


def test_bootstrap_prelabels_are_explicitly_provisional_and_cover_every_dev_unit() -> None:
    unit = _unit()
    manifest = _manifest(unit)
    bootstrap = TaxonomyBootstrapResult(
        input_hash="1" * 64,
        policy_version="2" * 64,
        proposal_prompt_revision="proposal@1",
        consolidation_prompt_revision="consolidate@1",
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
        draft_manifest=manifest,
        draft_manifest_hash=manifest_hash(manifest),
        assignments=[
            BootstrapRequirementAssignment(
                requirement_unit_id=unit.unit_id,
                proposal_id=f"bp_{'3' * 64}",
                target_stable_key="product.sync",
            )
        ],
    )
    extraction = _extraction_with_units(
        document_id=DOCUMENT_A,
        document_content_hash=unit.document_content_hash,
        units=[unit],
        source_ref=unit.source_ref,
    )
    document = {
        "motion-bootstrap": {
            "document_key": "motion-bootstrap",
            "title": "漫剧初版功能 PRD",
            "document_id": str(DOCUMENT_A),
            "system_key": "motion",
            "system_id": str(SYSTEM_A),
            "split": "bootstrap",
            "raw_source": {
                "path": "sources/bootstrap/motion-bootstrap.md",
                "sha256": unit.document_content_hash,
            },
            "source": {
                "path": "snapshots/bootstrap/motion-bootstrap.md",
                "sha256": unit.document_content_hash,
            },
            "canonicalization_revision": MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
            "image_enrichment_revision": MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
        }
    }

    from src.testcase_generator.schemas.taxonomy_pilot import PilotFrozenDocument

    gold = build_provisional_bootstrap_gold(
        corpus_id="taxonomy-pilot-v1",
        dataset_hash="5" * 64,
        bootstrap_results={"motion": bootstrap},
        requirement_units={"motion-bootstrap": extraction},
        documents={key: PilotFrozenDocument.model_validate(value) for key, value in document.items()},
        reviewed_by="bootstrap-derived:pilot-preparer",
        reviewed_at=NOW,
    )

    assert gold.review_method == "model_assisted_provisional"
    assert len(gold.records) == 1
    assert gold.records[0].record_id == pilot_record_id("motion-bootstrap", unit.unit_id)
    assert gold.records[0].expected_primary_stable_key == "product.sync"
    assert gold.records[0].expected_path == ["business.assets", "product.sync"]
    assert {node.gold_node_key for node in gold.expected_nodes} == {"business.assets", "product.sync"}


def test_bootstrap_prelabels_reject_assignment_without_source_unit() -> None:
    unit = _unit()
    manifest = _manifest(unit)
    unknown_unit_id = build_requirement_unit_id(
        document_content_hash=unit.document_content_hash,
        source_ref="prd:商品 §不存在",
        statement="模型虚构的需求。",
    )
    bootstrap = TaxonomyBootstrapResult(
        input_hash="1" * 64,
        policy_version="2" * 64,
        proposal_prompt_revision="proposal@1",
        consolidation_prompt_revision="consolidate@1",
        proposal_model_revision="primary@1",
        consolidation_model_revision="verify@1",
        draft_manifest=manifest,
        draft_manifest_hash=manifest_hash(manifest),
        assignments=[
            BootstrapRequirementAssignment(
                requirement_unit_id=unknown_unit_id,
                proposal_id=f"bp_{'3' * 64}",
                target_stable_key="product.sync",
            )
        ],
    )
    extraction = _extraction_with_units(
        document_id=DOCUMENT_A,
        document_content_hash=unit.document_content_hash,
        units=[unit],
        source_ref=unit.source_ref,
    )
    from src.testcase_generator.schemas.taxonomy_pilot import PilotFrozenDocument

    document = PilotFrozenDocument(
        document_key="motion-bootstrap",
        title="漫剧初版功能 PRD",
        document_id=DOCUMENT_A,
        system_key="motion",
        system_id=SYSTEM_A,
        split="bootstrap",
        raw_source={"path": "sources/bootstrap/motion-bootstrap.md", "sha256": unit.document_content_hash},
        source={"path": "snapshots/bootstrap/motion-bootstrap.md", "sha256": unit.document_content_hash},
        canonicalization_revision=MARKDOWN_CANONICAL_SNAPSHOT_REVISION,
        image_enrichment_revision=MARKDOWN_CANONICAL_IMAGE_ENRICHMENT_REVISION,
    )

    with pytest.raises(PilotArtifactError, match="pilot_bootstrap_assignment_unit_unknown"):
        build_provisional_bootstrap_gold(
            corpus_id="taxonomy-pilot-v2",
            dataset_hash="5" * 64,
            bootstrap_results={"motion": bootstrap},
            requirement_units={"motion-bootstrap": extraction},
            documents={"motion-bootstrap": document},
            reviewed_by="bootstrap-derived:pilot-preparer",
            reviewed_at=NOW,
        )


def test_resolution_projection_preserves_raw_identity_and_unknown_cost() -> None:
    unit = _unit()
    manifest = _manifest(unit)
    manifest_digest = manifest_hash(manifest)
    candidate = TaxonomyCandidate(
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        concept_id=CONCEPT_ID,
        stable_key="product.sync",
        score=0.93,
        rank=1,
        evidence=["embedding_similarity:0.930000"],
    )
    resolution = TaxonomyResolution(
        schema_version=1,
        status="mapped",
        method="policy_auto",
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=CONCEPT_ID,
        candidates=[candidate],
        confidence=0.93,
        margin=0.93,
        reason_code="candidate_confirmed",
        reason="候选定义与需求一致。",
        input_hash="6" * 64,
        taxonomy_manifest_hash=manifest_digest,
        policy_version="8" * 64,
        model_revision="verify@1",
        requirement_unit_ids=[unit.unit_id],
    )
    raw = PilotResolutionSet(
        schema_version=1,
        run_id="dev-resolution-001",
        generated_at=NOW,
        dataset_hash="9" * 64,
        policy_hash="8" * 64,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
        taxonomy_version_ids={"motion": TAXONOMY_VERSION_ID},
        output_manifest_hashes={"motion": manifest_digest},
        records=[
            PilotResolutionRecord(
                document_key="motion-dev",
                system_key="motion",
                split="dev",
                requirement_unit_id=unit.unit_id,
                latency_ms=123,
                cost_usd=None,
                resolution=resolution,
            )
        ],
    )

    predictions = project_resolution_predictions(
        resolutions=raw,
        concept_refs={CONCEPT_ID: PilotConceptRef(system_key="motion", stable_key="product.sync")},
        manifests={"motion": manifest},
        manifest_artifacts={"motion": MANIFEST_ARTIFACT},
    )

    record = predictions.records[0]
    assert predictions.schema_version == 2
    assert predictions.output_manifest_artifacts == {"motion": MANIFEST_ARTIFACT}
    assert record.record_id == pilot_record_id("motion-dev", unit.unit_id)
    assert record.input_hash == resolution.input_hash
    assert record.predicted_primary_stable_key == "product.sync"
    assert record.predicted_path == ["business.assets", "product.sync"]
    assert record.score == 0.93
    assert record.cost_usd is None


def test_resolution_projection_rejects_cross_system_concept_even_when_key_matches() -> None:
    unit = _unit()
    manifest = _manifest(unit)
    manifest_digest = manifest_hash(manifest)
    resolution = TaxonomyResolution(
        schema_version=1,
        status="mapped",
        method="policy_auto",
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=CONCEPT_ID,
        candidates=[
            TaxonomyCandidate(
                taxonomy_version_id=TAXONOMY_VERSION_ID,
                concept_id=CONCEPT_ID,
                stable_key="product.sync",
                score=0.93,
                rank=1,
                evidence=["embedding_similarity:0.930000"],
            )
        ],
        confidence=0.93,
        margin=0.93,
        reason_code="candidate_confirmed",
        reason="候选定义与需求一致。",
        input_hash="6" * 64,
        taxonomy_manifest_hash=manifest_digest,
        policy_version="8" * 64,
        model_revision="verify@1",
        requirement_unit_ids=[unit.unit_id],
    )
    raw = PilotResolutionSet(
        schema_version=1,
        run_id="dev-resolution-001",
        generated_at=NOW,
        dataset_hash="9" * 64,
        policy_hash="8" * 64,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
        taxonomy_version_ids={"motion": TAXONOMY_VERSION_ID},
        output_manifest_hashes={"motion": manifest_digest},
        records=[
            PilotResolutionRecord(
                document_key="motion-dev",
                system_key="motion",
                split="dev",
                requirement_unit_id=unit.unit_id,
                latency_ms=123,
                resolution=resolution,
            )
        ],
    )

    with pytest.raises(PilotArtifactError, match="pilot_resolution_candidate_cross_system"):
        project_resolution_predictions(
            resolutions=raw,
            concept_refs={CONCEPT_ID: PilotConceptRef(system_key="distribution", stable_key="product.sync")},
            manifests={"motion": manifest},
            manifest_artifacts={"motion": MANIFEST_ARTIFACT},
        )


def test_resolution_projection_rejects_candidate_key_bound_to_another_concept() -> None:
    unit = _unit()
    manifest = _manifest(unit)
    manifest_digest = manifest_hash(manifest)
    resolution = TaxonomyResolution(
        schema_version=1,
        status="mapped",
        method="policy_auto",
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=CONCEPT_ID,
        candidates=[
            TaxonomyCandidate(
                taxonomy_version_id=TAXONOMY_VERSION_ID,
                concept_id=CONCEPT_ID,
                stable_key="business.assets",
                score=0.93,
                rank=1,
                evidence=["embedding_similarity:0.930000"],
            )
        ],
        confidence=0.93,
        margin=0.93,
        reason_code="candidate_confirmed",
        reason="候选 UUID 与 stable key 绑定错误。",
        input_hash="6" * 64,
        taxonomy_manifest_hash=manifest_digest,
        policy_version="8" * 64,
        model_revision="verify@1",
        requirement_unit_ids=[unit.unit_id],
    )
    raw = PilotResolutionSet(
        schema_version=1,
        run_id="dev-resolution-001",
        generated_at=NOW,
        dataset_hash="9" * 64,
        policy_hash="8" * 64,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
        taxonomy_version_ids={"motion": TAXONOMY_VERSION_ID},
        output_manifest_hashes={"motion": manifest_digest},
        records=[
            PilotResolutionRecord(
                document_key="motion-dev",
                system_key="motion",
                split="dev",
                requirement_unit_id=unit.unit_id,
                latency_ms=123,
                resolution=resolution,
            )
        ],
    )

    with pytest.raises(PilotArtifactError, match="pilot_resolution_candidate_concept_mismatch"):
        project_resolution_predictions(
            resolutions=raw,
            concept_refs={CONCEPT_ID: PilotConceptRef(system_key="motion", stable_key="product.sync")},
            manifests={"motion": manifest},
            manifest_artifacts={"motion": MANIFEST_ARTIFACT},
        )


def test_resolution_projection_rejects_deprecated_manifest_candidate() -> None:
    unit = _unit()
    deprecated_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    base = _manifest(unit)
    manifest = base.model_copy(
        update={
            "nodes": [
                *base.nodes,
                TaxonomyNodeManifest(
                    stable_key="product.legacy-create",
                    node_type="capability",
                    display_name="旧商品创建",
                    parent_stable_key="business.assets",
                    sort_order=9,
                    node_status="deprecated",
                    definition="已废弃的商品创建能力。",
                    scope_note="当前系统不再使用。",
                ),
            ]
        }
    )
    digest = manifest_hash(manifest)
    resolution = TaxonomyResolution(
        schema_version=1,
        status="mapped",
        method="policy_auto",
        taxonomy_version_id=TAXONOMY_VERSION_ID,
        primary_concept_id=deprecated_id,
        candidates=[
            TaxonomyCandidate(
                taxonomy_version_id=TAXONOMY_VERSION_ID,
                concept_id=deprecated_id,
                stable_key="product.legacy-create",
                score=0.99,
                rank=1,
                evidence=["embedding_similarity:0.990000"],
            )
        ],
        confidence=0.99,
        margin=0.99,
        reason_code="candidate_confirmed",
        reason="错误选择了已废弃节点。",
        input_hash="6" * 64,
        taxonomy_manifest_hash=digest,
        policy_version="8" * 64,
        model_revision="verify@1",
        requirement_unit_ids=[unit.unit_id],
    )
    raw = PilotResolutionSet(
        schema_version=1,
        run_id="dev-resolution-deprecated",
        generated_at=NOW,
        dataset_hash="9" * 64,
        policy_hash="8" * 64,
        prompt_revisions={"resolver": "resolver@1"},
        model_revisions={"taxonomy_resolver": "verify@1"},
        taxonomy_version_ids={"motion": TAXONOMY_VERSION_ID},
        output_manifest_hashes={"motion": digest},
        records=[
            PilotResolutionRecord(
                document_key="motion-dev",
                system_key="motion",
                split="dev",
                requirement_unit_id=unit.unit_id,
                latency_ms=1,
                resolution=resolution,
            )
        ],
    )

    with pytest.raises(PilotArtifactError, match="pilot_resolution_candidate_not_active"):
        project_resolution_predictions(
            resolutions=raw,
            concept_refs={deprecated_id: PilotConceptRef(system_key="motion", stable_key="product.legacy-create")},
            manifests={"motion": manifest},
            manifest_artifacts={"motion": MANIFEST_ARTIFACT},
        )
