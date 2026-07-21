from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.enums import ReviewStatus
from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System
from src.platform_api.models.taxonomy import (
    RequirementTaxonomyMapping,
    RequirementTaxonomyMappingRelatedConcept,
    TaxonomyBackfillRun,
    TaxonomyConcept,
    TaxonomyNode,
    TaxonomyVersion,
)
from src.platform_api.models.taxonomy import (
    TestCaseRelatedTaxonomyConcept as _CaseRelatedTaxonomyConcept,
)
from src.platform_api.models.testcase import StageArtifact
from src.platform_api.models.testcase import TestBatch as BatchModel
from src.platform_api.models.testcase import TestCase as CaseModel
from src.platform_api.models.testcase import TestPoint as _TestPointModel
from src.platform_api.services.review_service import ReviewService
from src.platform_api.services.taxonomy_admin_service import TaxonomyAdminService
from src.testcase_generator.schemas.taxonomy import TaxonomyAssignmentSet, TaxonomyManifest, TaxonomySelector
from src.testcase_generator.services.iteration_service import IterationService
from src.testcase_generator.services.taxonomy_manifest import manifest_hash
from src.testcase_generator.services.taxonomy_replay import TaxonomyReplayError, TaxonomyReplayService
from src.testcase_generator.services.taxonomy_replay_report import write_replay_artifacts
from src.testcase_generator.tasks import callbacks as callback_tasks
from src.testcase_generator.tasks.pipeline_task import _resume_pipeline
from tests.platform_api.conftest import requires_db, set_taxonomy_immutability_triggers

pytestmark = requires_db


@pytest.fixture
async def db_session() -> AsyncSession:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def replay_source(db_session: AsyncSession):
    system_id = uuid.uuid4()
    document_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    case_ids = (uuid.uuid4(), uuid.uuid4())
    content_hash = hashlib.sha256(str(document_id).encode()).hexdigest()

    db_session.add(System(id=system_id, name=f"taxonomy-replay-{uuid.uuid4()}"))
    await db_session.flush()
    db_session.add(
        Document(
            id=document_id,
            system_id=system_id,
            title="taxonomy replay test",
            doc_type="prd",
            content="# test",
            storage_path=f"test/{document_id}.md",
            content_hash=content_hash,
        )
    )
    await db_session.flush()
    db_session.add(BatchModel(id=batch_id, document_id=document_id, system_id=system_id, status="completed"))
    await db_session.flush()
    for index, case_id in enumerate(case_ids, start=1):
        db_session.add(
            CaseModel(
                id=case_id,
                batch_id=batch_id,
                title=f"回放用例 {index}",
                preconditions=[],
                steps=[{"step": index, "action": "执行", "expected": "成功"}],
                expected_results=["成功"],
                priority="P1",
                dimensions=["functional_correctness"],
                provenance={
                    "source_section": f"prd:test §未知能力-{index}",
                    "derived_from": [f"prd:test §未知能力-{index}"],
                },
                trust_level=1,
                verdict="grounded",
                bucket="main",
            )
        )
    await db_session.commit()

    manifest = TaxonomyManifest.model_validate(
        {
            "schema_version": 1,
            "system_id": str(system_id),
            "version": 1,
            "change_note": "replay test",
            "created_by": "test",
            "nodes": [
                {
                    "stable_key": "asset-center",
                    "node_type": "module",
                    "display_name": "素材中心",
                },
                {
                    "stable_key": "asset-center.filter",
                    "node_type": "capability",
                    "display_name": "筛选与排序",
                    "parent_stable_key": "asset-center",
                },
                {
                    "stable_key": "asset-center.related-a",
                    "node_type": "capability",
                    "display_name": "关联能力 A",
                    "parent_stable_key": "asset-center",
                },
                {
                    "stable_key": "asset-center.related-b",
                    "node_type": "capability",
                    "display_name": "关联能力 B",
                    "parent_stable_key": "asset-center",
                },
            ],
        }
    )
    admin = TaxonomyAdminService(db_session)
    await admin.import_manifest(manifest, actor="test", apply=True)
    await admin.activate(system_id=system_id, version=1, actor="taxonomy-reviewer", apply=True)
    version_id = await db_session.scalar(
        select(TaxonomyVersion.id).where(
            TaxonomyVersion.system_id == system_id,
            TaxonomyVersion.version == 1,
        )
    )
    concept_ids = dict(
        (
            await db_session.execute(
                select(TaxonomyConcept.stable_key, TaxonomyConcept.id).where(TaxonomyConcept.system_id == system_id)
            )
        ).all()
    )
    await db_session.rollback()

    assignment_set = TaxonomyAssignmentSet.model_validate(
        {
            "schema_version": 1,
            "batch_id": str(batch_id),
            "taxonomy_version": 1,
            "manifest_hash": manifest_hash(manifest),
            "prepared_by": "author",
            "prepared_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
            "approval_status": "approved",
            "approved_by": "reviewer",
            "approved_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
            "assignments": [
                {
                    "case_id": str(case_ids[0]),
                    "target_stable_key": "asset-center.filter",
                    "related_stable_keys": ["asset-center.related-b", "asset-center.related-a"],
                    "assignment_source": "reviewed_override",
                    "reason": "人工确认属于筛选能力",
                    "confidence": 1,
                },
                {
                    "case_id": str(case_ids[1]),
                    "assignment_source": "unresolved",
                    "reason": "证据不足",
                    "unresolved_reason": "无法确定能力",
                },
            ],
        }
    )
    yield {
        "system_id": system_id,
        "document_id": document_id,
        "batch_id": batch_id,
        "case_ids": case_ids,
        "manifest": manifest,
        "version_id": version_id,
        "concept_ids": concept_ids,
        "assignments": assignment_set,
    }

    await db_session.rollback()
    await set_taxonomy_immutability_triggers(db_session, enabled=False)
    try:
        await db_session.execute(delete(TaxonomyBackfillRun).where(TaxonomyBackfillRun.batch_id == batch_id))
        await db_session.execute(delete(CaseModel).where(CaseModel.batch_id == batch_id))
        await db_session.execute(delete(BatchModel).where(BatchModel.id == batch_id))
        await db_session.execute(
            delete(RequirementTaxonomyMapping).where(RequirementTaxonomyMapping.system_id == system_id)
        )
        await db_session.execute(delete(TaxonomyNode).where(TaxonomyNode.system_id == system_id))
        await db_session.execute(delete(TaxonomyVersion).where(TaxonomyVersion.system_id == system_id))
        await db_session.execute(delete(TaxonomyConcept).where(TaxonomyConcept.system_id == system_id))
        await db_session.execute(delete(Document).where(Document.id == document_id))
        await db_session.execute(delete(System).where(System.id == system_id))
    finally:
        await set_taxonomy_immutability_triggers(db_session, enabled=True)
    await db_session.commit()


async def test_replay_dry_run_writes_nothing(db_session: AsyncSession, replay_source) -> None:
    service = TaxonomyReplayService(db_session)

    result = await service.replay(replay_source["assignments"], apply=False)

    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    case_concepts = list(
        (
            await db_session.execute(
                select(CaseModel.taxonomy_concept_id).where(CaseModel.batch_id == replay_source["batch_id"])
            )
        ).scalars()
    )
    run_count = await db_session.scalar(
        select(func.count())
        .select_from(TaxonomyBackfillRun)
        .where(TaxonomyBackfillRun.batch_id == replay_source["batch_id"])
    )

    assert result.applied is False
    assert result.total_count == 2
    assert result.mapped_count == 1
    assert result.unresolved_count == 1
    assert result.overall_coverage == 0.5
    assert batch is not None and batch.taxonomy_version_id is None
    assert case_concepts == [None, None]
    assert run_count == 0
    await db_session.rollback()


async def test_replay_apply_and_rollback_preserve_case_content(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    before_cases = list(
        (
            await db_session.execute(
                select(CaseModel).where(CaseModel.batch_id == replay_source["batch_id"]).order_by(CaseModel.id)
            )
        )
        .scalars()
        .all()
    )
    original_provenance = {case.id: case.provenance for case in before_cases}
    await db_session.rollback()
    preview = await service.replay(replay_source["assignments"], apply=False)

    applied = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=preview.baseline_hash,
        expected_plan_hash=preview.plan_hash,
        actor="apply-reviewer",
    )
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    cases = list(
        (
            await db_session.execute(
                select(CaseModel).where(CaseModel.batch_id == replay_source["batch_id"]).order_by(CaseModel.id)
            )
        )
        .scalars()
        .all()
    )
    assert batch is not None and batch.taxonomy_version_id == replay_source["version_id"]
    assert sum(case.taxonomy_concept_id is not None for case in cases) == 1
    mapped_case = next(case for case in cases if case.id == replay_source["case_ids"][0])
    related_ids = list(
        (
            await db_session.execute(
                select(_CaseRelatedTaxonomyConcept.concept_id)
                .where(_CaseRelatedTaxonomyConcept.case_id == mapped_case.id)
                .order_by(_CaseRelatedTaxonomyConcept.concept_id)
            )
        ).scalars()
    )
    assert [str(value) for value in related_ids] == sorted(
        [
            str(replay_source["concept_ids"]["asset-center.related-a"]),
            str(replay_source["concept_ids"]["asset-center.related-b"]),
        ]
    )
    assert {case.id: case.provenance for case in cases} == original_provenance
    assert applied.run_id is not None
    await db_session.rollback()

    rolled_back = await service.rollback(applied.run_id, actor="rollback-reviewer")
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    cases = list(
        (await db_session.execute(select(CaseModel).where(CaseModel.batch_id == replay_source["batch_id"])))
        .scalars()
        .all()
    )
    run = await db_session.get(TaxonomyBackfillRun, applied.run_id)

    assert rolled_back.rolled_back is True
    assert batch is not None and batch.taxonomy_version_id is None
    assert all(
        case.taxonomy_version_id is None and case.taxonomy_concept_id is None and case.taxonomy_resolution is None
        for case in cases
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(_CaseRelatedTaxonomyConcept)
            .where(_CaseRelatedTaxonomyConcept.case_id.in_(replay_source["case_ids"]))
        )
        == 0
    )
    assert {case.id: case.provenance for case in cases} == original_provenance
    assert run is not None and run.status == "rolled_back"
    assert run.rolled_back_by == "rollback-reviewer"
    await db_session.rollback()


async def test_manual_case_content_edit_rejects_taxonomy_frozen_batch(
    db_session: AsyncSession,
    replay_source,
) -> None:
    replay = TaxonomyReplayService(db_session)
    preview = await replay.replay(replay_source["assignments"], apply=False)
    await replay.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=preview.baseline_hash,
        expected_plan_hash=preview.plan_hash,
        actor="apply-reviewer",
    )
    review = ReviewService(db_session)

    with pytest.raises(ApiError) as exc_info:
        await review.update_case(replay_source["case_ids"][0], {"title": "分类后不应再改标题"})

    assert exc_info.value.error_code == "E4092"
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    original_status = case.review_status
    reviewed = await review.review_case(case.id, ReviewStatus.CONFIRMED, "只改审核元数据")
    assert reviewed.review_status == ReviewStatus.CONFIRMED
    assert reviewed.review_status != original_status


async def test_replay_rollback_uses_serializable_transaction(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    preview = await service.replay(replay_source["assignments"], apply=False)
    applied = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=preview.baseline_hash,
        expected_plan_hash=preview.plan_hash,
        actor="apply-reviewer",
    )
    assert applied.run_id is not None

    original_get_backfill_run = service.repository.get_backfill_run
    observed_isolation: list[str] = []

    async def get_backfill_run_with_isolation(run_id, *, for_update=False):
        observed_isolation.append(str(await db_session.scalar(text("SHOW transaction_isolation"))))
        return await original_get_backfill_run(run_id, for_update=for_update)

    service.repository.get_backfill_run = get_backfill_run_with_isolation
    await service.rollback(applied.run_id, actor="rollback-reviewer")

    assert observed_isolation == ["serializable"]


async def test_replay_apply_rejects_stale_baseline(db_session: AsyncSession, replay_source) -> None:
    service = TaxonomyReplayService(db_session)
    preview = await service.replay(replay_source["assignments"], apply=False)
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    case.title = "并发修改后的标题"
    await db_session.commit()

    with pytest.raises(TaxonomyReplayError, match="replay_baseline_changed"):
        await service.replay(
            replay_source["assignments"],
            apply=True,
            expected_baseline_hash=preview.baseline_hash,
            expected_plan_hash=preview.plan_hash,
            actor="reviewer",
        )


async def test_replay_apply_rejects_assignment_changed_after_preview(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    preview = await service.replay(replay_source["assignments"], apply=False)
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["target_stable_key"] = "asset-center.related-a"
    assignment_data["assignments"][0]["related_stable_keys"] = []
    changed_assignments = TaxonomyAssignmentSet.model_validate(assignment_data)

    with pytest.raises(TaxonomyReplayError, match="replay_plan_changed"):
        await service.replay(
            changed_assignments,
            apply=True,
            expected_baseline_hash=preview.baseline_hash,
            expected_plan_hash=preview.plan_hash,
            actor="reviewer",
        )


async def test_replay_requires_exact_case_set(db_session: AsyncSession, replay_source) -> None:
    data = replay_source["assignments"].model_dump(mode="json")
    data["assignments"] = data["assignments"][:1]
    incomplete = TaxonomyAssignmentSet.model_validate(data)

    with pytest.raises(TaxonomyReplayError, match="replay_case_set_mismatch"):
        await TaxonomyReplayService(db_session).replay(incomplete, apply=False)


async def test_replay_rejects_drift_from_frozen_legacy_anomaly_set(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    with pytest.raises(TaxonomyReplayError, match="legacy_anomaly_case_set_changed"):
        await service.replay(
            replay_source["assignments"],
            apply=False,
            expected_legacy_anomaly_case_ids=frozenset(),
        )

    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    run_count = await db_session.scalar(
        select(func.count())
        .select_from(TaxonomyBackfillRun)
        .where(TaxonomyBackfillRun.batch_id == replay_source["batch_id"])
    )
    assert batch is not None and batch.taxonomy_version_id is None
    assert run_count == 0


async def test_replay_rollbacks_must_follow_last_applied_first(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    first_preview = await service.replay(replay_source["assignments"], apply=False)
    first = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=first_preview.baseline_hash,
        expected_plan_hash=first_preview.plan_hash,
        actor="first",
    )
    second_preview = await service.replay(replay_source["assignments"], apply=False)
    second = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=second_preview.baseline_hash,
        expected_plan_hash=second_preview.plan_hash,
        actor="second",
    )
    assert first.run_id is not None and second.run_id is not None

    with pytest.raises(TaxonomyReplayError, match="rollback_assignment_drift"):
        await service.rollback(first.run_id, actor="wrong-order")

    await service.rollback(second.run_id, actor="second-rollback")
    await service.rollback(first.run_id, actor="first-rollback")


async def test_backfill_run_rollback_status_requires_audit_metadata(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    preview = await service.replay(replay_source["assignments"], apply=False)
    applied = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=preview.baseline_hash,
        expected_plan_hash=preview.plan_hash,
        actor="apply-reviewer",
    )
    assert applied.run_id is not None
    run = await db_session.get(TaxonomyBackfillRun, applied.run_id)
    assert run is not None
    run.status = "rolled_back"

    with pytest.raises(IntegrityError, match="ck_taxonomy_backfill_runs_rollback_metadata"):
        await db_session.flush()
    await db_session.rollback()


async def test_backfill_run_rejects_before_image_mutation_and_delete(
    db_session: AsyncSession,
    replay_source,
) -> None:
    service = TaxonomyReplayService(db_session)
    preview = await service.replay(replay_source["assignments"], apply=False)
    applied = await service.replay(
        replay_source["assignments"],
        apply=True,
        expected_baseline_hash=preview.baseline_hash,
        expected_plan_hash=preview.plan_hash,
        actor="apply-reviewer",
    )
    assert applied.run_id is not None
    run = await db_session.get(TaxonomyBackfillRun, applied.run_id)
    assert run is not None

    with pytest.raises(DBAPIError, match="taxonomy backfill run is immutable"):
        async with db_session.begin_nested():
            run.before_image = {"tampered": True}
            await db_session.flush()

    await db_session.refresh(run)
    with pytest.raises(DBAPIError, match="taxonomy backfill run cannot be deleted"):
        async with db_session.begin_nested():
            await db_session.execute(delete(TaxonomyBackfillRun).where(TaxonomyBackfillRun.id == run.id))


async def test_replay_report_writes_traceable_artifact_set(
    db_session: AsyncSession,
    replay_source,
    tmp_path,
) -> None:
    result = await TaxonomyReplayService(db_session).replay(replay_source["assignments"], apply=False)

    write_replay_artifacts(
        output_dir=tmp_path,
        result=result,
        assignments=replay_source["assignments"],
        manifest=replay_source["manifest"],
    )

    assert {
        "REPORT.md",
        "assignment-set.json",
        "assignments.jsonl",
        "baseline.json",
        "known-anomalies.jsonl",
        "manifest.json",
        "old-vs-new.json",
        "reviewed-assignments.json",
        "source-trace.json",
        "unresolved.jsonl",
    }.issubset({path.name for path in tmp_path.iterdir()})
    source_trace = json.loads((tmp_path / "source-trace.json").read_text(encoding="utf-8"))
    assert source_trace["total_reference_count"] == 2
    assert source_trace["unique_case_count"] == 2
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "数据来源：`database`" in report
    assert "旧分类器仅作 proposal" in report
    assert "独立抽样精度" in report
    assert "候选定位覆盖" in report
    assert "可复用 approved mapping 覆盖" in report
    assert "不由逐 case assignment 冒充" in report
    assert "PENDING：当前没有 approved mapping" in report
    anomalies = [
        json.loads(line) for line in (tmp_path / "known-anomalies.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(anomalies) == 2
    assert {item["legacy_anomaly_category"] for item in anomalies} == {"source_section_fallback"}


async def test_replay_report_draft_does_not_label_assignment_as_reviewed(
    db_session: AsyncSession,
    replay_source,
    tmp_path,
) -> None:
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["approval_status"] = "draft"
    assignment_data.pop("approved_by")
    assignment_data.pop("approved_at")
    assignments = TaxonomyAssignmentSet.model_validate(assignment_data)
    result = await TaxonomyReplayService(db_session).replay(assignments, apply=False)
    stale_reviewed_path = tmp_path / "reviewed-assignments.json"
    stale_rollback_path = tmp_path / "rollback.json"
    stale_reviewed_path.write_text("{}", encoding="utf-8")
    stale_rollback_path.write_text("{}", encoding="utf-8")

    write_replay_artifacts(
        output_dir=tmp_path,
        result=result,
        assignments=assignments,
        manifest=replay_source["manifest"],
    )

    assert (tmp_path / "assignment-set.json").exists()
    assert not stale_reviewed_path.exists()
    assert not stale_rollback_path.exists()


async def test_replay_report_does_not_overwrite_apply_output_directory(
    db_session: AsyncSession,
    replay_source,
    tmp_path,
) -> None:
    result = await TaxonomyReplayService(db_session).replay(replay_source["assignments"], apply=False)
    output_dir = tmp_path / "existing-apply-output"
    output_dir.mkdir()
    marker = output_dir / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError, match="output already exists"):
        write_replay_artifacts(
            output_dir=output_dir,
            result=result,
            assignments=replay_source["assignments"],
            manifest=replay_source["manifest"],
            replace_existing=False,
        )

    assert marker.read_text(encoding="utf-8") == "keep"


async def test_replay_report_rejects_partial_approved_mapping_coverage(
    db_session: AsyncSession,
    replay_source,
    tmp_path,
) -> None:
    result = await TaxonomyReplayService(db_session).replay(replay_source["assignments"], apply=False)
    first_case = replace(result.cases[0], assignment_source="approved_mapping")
    partial_mapping_result = replace(result, cases=(first_case, *result.cases[1:]))

    write_replay_artifacts(
        output_dir=tmp_path,
        result=partial_mapping_result,
        assignments=replay_source["assignments"],
        manifest=replay_source["manifest"],
    )

    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "overall ≥90%，main ≥95%" in report
    assert "| 可复用 approved mapping | FAIL：覆盖未达标 |" in report


async def test_replay_report_exposes_non_capability_granularity_debt(
    db_session: AsyncSession,
    replay_source,
    tmp_path,
) -> None:
    result = await TaxonomyReplayService(db_session).replay(replay_source["assignments"], apply=False)
    broad_cases = tuple(
        replace(
            case,
            target_node_type="module",
            target_path=("业务资产", "素材中心"),
        )
        if case.target_stable_key is not None
        else case
        for case in result.cases
    )

    write_replay_artifacts(
        output_dir=tmp_path,
        result=replace(result, cases=broad_cases),
        assignments=replay_source["assignments"],
        manifest=replay_source["manifest"],
    )

    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "| 候选 capability 粒度 | 0/1 (0.0%) |" in report
    assert "业务资产 / 素材中心（1）" in report
    assert "| 能力粒度债务 | PENDING：1 条落在 domain/module" in report


async def test_replay_draft_version_can_preview_but_cannot_apply(
    db_session: AsyncSession,
    replay_source,
) -> None:
    manifest_data = replay_source["manifest"].model_dump(mode="json")
    manifest_data["version"] = 2
    manifest_data["change_note"] = "draft v2"
    draft_manifest = TaxonomyManifest.model_validate(manifest_data)
    await TaxonomyAdminService(db_session).import_manifest(draft_manifest, actor="test", apply=True)
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["taxonomy_version"] = 2
    assignment_data["manifest_hash"] = manifest_hash(draft_manifest)
    draft_assignments = TaxonomyAssignmentSet.model_validate(assignment_data)
    service = TaxonomyReplayService(db_session)

    preview = await service.replay(draft_assignments, apply=False)
    with pytest.raises(TaxonomyReplayError, match="replay_version_not_active"):
        await service.replay(
            draft_assignments,
            apply=True,
            expected_baseline_hash=preview.baseline_hash,
            expected_plan_hash=preview.plan_hash,
            actor="reviewer",
        )


async def test_replay_draft_assignments_can_preview_but_cannot_apply(
    db_session: AsyncSession,
    replay_source,
) -> None:
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["approval_status"] = "draft"
    assignment_data["approved_by"] = None
    assignment_data["approved_at"] = None
    draft_assignments = TaxonomyAssignmentSet.model_validate(assignment_data)
    service = TaxonomyReplayService(db_session)

    preview = await service.replay(draft_assignments, apply=False)
    assert preview.total_count == 2

    with pytest.raises(TaxonomyReplayError, match="assignment_set_not_approved"):
        await service.replay(
            draft_assignments,
            apply=True,
            expected_baseline_hash=preview.baseline_hash,
            expected_plan_hash=preview.plan_hash,
            actor="reviewer",
        )


async def test_replay_shadow_snapshot_can_preview_but_cannot_apply(
    db_session: AsyncSession,
    replay_source,
) -> None:
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None
    batch.generation_config = {
        "shadow_snapshot": True,
        "source": "remote_public_api",
        "not_a_production_apply_baseline": True,
    }
    await db_session.commit()
    service = TaxonomyReplayService(db_session)

    preview = await service.replay(replay_source["assignments"], apply=False)

    assert preview.source_scope == "remote_api_shadow"
    with pytest.raises(TaxonomyReplayError, match="replay_shadow_snapshot_apply_forbidden"):
        await service.replay(
            replay_source["assignments"],
            apply=True,
            expected_baseline_hash=preview.baseline_hash,
            expected_plan_hash=preview.plan_hash,
            actor="reviewer",
        )


async def test_replay_rejects_unverifiable_approved_mapping(
    db_session: AsyncSession,
    replay_source,
) -> None:
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["assignment_source"] = "approved_mapping"
    assignment_data["assignments"][0]["mapping_id"] = str(uuid.uuid4())
    unverifiable = TaxonomyAssignmentSet.model_validate(assignment_data)

    with pytest.raises(TaxonomyReplayError, match="assignment_mapping_not_approved"):
        await TaxonomyReplayService(db_session).replay(unverifiable, apply=False)


async def test_replay_approved_mapping_requires_case_test_point_binding(
    db_session: AsyncSession,
    replay_source,
) -> None:
    mapping_id = await _add_approved_mapping(db_session, replay_source, feature_fingerprint="a" * 64)

    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["assignment_source"] = "approved_mapping"
    assignment_data["assignments"][0]["mapping_id"] = str(mapping_id)
    assignments = TaxonomyAssignmentSet.model_validate(assignment_data)

    with pytest.raises(TaxonomyReplayError, match="assignment_mapping_selector_facts_missing"):
        await TaxonomyReplayService(db_session).replay(assignments, apply=False)


async def test_replay_accepts_mapping_matched_from_stable_test_point_facts(
    db_session: AsyncSession,
    replay_source,
) -> None:
    mapping_id = await _add_approved_mapping(db_session, replay_source, feature_fingerprint="b" * 64)
    test_point_id = uuid.uuid4()
    db_session.add(
        _TestPointModel(
            id=test_point_id,
            batch_id=replay_source["batch_id"],
            feature_id="F-001",
            dimension="functional_correctness",
            description="已映射测试点",
            priority="P1",
            derived_from={"source_refs": ["prd:test §5.1"]},
            taxonomy_selector_facts={
                "schema_version": 1,
                "feature_fingerprint": "b" * 64,
            },
            taxonomy_resolution={"mapping_id": str(uuid.uuid4()), "ignored_output_evidence": True},
        )
    )
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    case.test_point_id = test_point_id
    await db_session.commit()

    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["assignment_source"] = "approved_mapping"
    assignment_data["assignments"][0]["mapping_id"] = str(mapping_id)
    assignments = TaxonomyAssignmentSet.model_validate(assignment_data)

    result = await TaxonomyReplayService(db_session).replay(assignments, apply=False)

    assert result.mapped_count == 1


async def test_replay_rejects_mapping_when_feature_fingerprint_does_not_match(
    db_session: AsyncSession,
    replay_source,
) -> None:
    mapping_id = await _add_approved_mapping(db_session, replay_source, feature_fingerprint="b" * 64)
    test_point_id = uuid.uuid4()
    db_session.add(
        _TestPointModel(
            id=test_point_id,
            batch_id=replay_source["batch_id"],
            feature_id="F-001",
            dimension="functional_correctness",
            description="不匹配测试点",
            priority="P1",
            derived_from={},
            taxonomy_selector_facts={"schema_version": 1, "feature_fingerprint": "c" * 64},
        )
    )
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    case.test_point_id = test_point_id
    await db_session.commit()
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["assignment_source"] = "approved_mapping"
    assignment_data["assignments"][0]["mapping_id"] = str(mapping_id)
    assignments = TaxonomyAssignmentSet.model_validate(assignment_data)

    with pytest.raises(TaxonomyReplayError, match="assignment_mapping_no_match"):
        await TaxonomyReplayService(db_session).replay(assignments, apply=False)


async def test_replay_selector_mapping_takes_precedence_over_feature_default(
    db_session: AsyncSession,
    replay_source,
) -> None:
    await _add_approved_mapping(db_session, replay_source, feature_fingerprint="d" * 64)
    selector_mapping_id = await _add_approved_mapping(
        db_session,
        replay_source,
        feature_fingerprint="d" * 64,
        selector={"structural_key": "filter.sort"},
    )
    test_point_id = uuid.uuid4()
    db_session.add(
        _TestPointModel(
            id=test_point_id,
            batch_id=replay_source["batch_id"],
            feature_id="F-001",
            dimension="functional_correctness",
            description="selector 优先级测试点",
            priority="P1",
            derived_from={},
            taxonomy_selector_facts={
                "schema_version": 1,
                "feature_fingerprint": "d" * 64,
                "structural_key": "filter.sort",
            },
        )
    )
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    case.test_point_id = test_point_id
    await db_session.commit()
    assignment_data = replay_source["assignments"].model_dump(mode="json")
    assignment_data["assignments"][0]["assignment_source"] = "approved_mapping"
    assignment_data["assignments"][0]["mapping_id"] = str(selector_mapping_id)
    assignments = TaxonomyAssignmentSet.model_validate(assignment_data)

    result = await TaxonomyReplayService(db_session).replay(assignments, apply=False)

    assert result.mapped_count == 1


async def test_replay_mapping_lineage_uses_version_validity_interval(
    db_session: AsyncSession,
    replay_source,
) -> None:
    feature_fingerprint = "f" * 64
    old_mapping_id = await _add_approved_mapping(
        db_session,
        replay_source,
        feature_fingerprint=feature_fingerprint,
    )
    document = await db_session.get(Document, replay_source["document_id"])
    assert document is not None
    document_content_hash = document.content_hash
    await db_session.rollback()
    v2_data = replay_source["manifest"].model_dump(mode="json")
    v2_data.update(
        {
            "version": 2,
            "change_note": "mapping v2",
            "created_by": "version-two-author",
            "mappings": [
                {
                    "document_id": str(replay_source["document_id"]),
                    "document_content_hash": document_content_hash,
                    "feature_fingerprint": feature_fingerprint,
                    "scope": "feature_default",
                    "target_stable_key": "asset-center.related-a",
                    "related_stable_keys": ["asset-center.filter", "asset-center.related-b"],
                    "mapping_method": "manual",
                    "confidence": 1,
                    "reason": "v2 人工确认调整主能力",
                    "review_status": "approved",
                    "reviewed_by": "mapping-reviewer-v2",
                    "reviewed_at": datetime(2026, 7, 21, 1, tzinfo=timezone.utc).isoformat(),
                    "supersedes_mapping_id": str(old_mapping_id),
                }
            ],
        }
    )
    v2_manifest = TaxonomyManifest.model_validate(v2_data)
    await TaxonomyAdminService(db_session).import_manifest(
        v2_manifest,
        actor="version-two-author",
        apply=True,
    )
    new_mapping_id = await db_session.scalar(
        select(RequirementTaxonomyMapping.id).where(RequirementTaxonomyMapping.supersedes_mapping_id == old_mapping_id)
    )
    assert new_mapping_id is not None
    await db_session.rollback()

    test_point_id = uuid.uuid4()
    db_session.add(
        _TestPointModel(
            id=test_point_id,
            batch_id=replay_source["batch_id"],
            feature_id="F-001",
            dimension="functional_correctness",
            description="mapping lineage 测试点",
            priority="P1",
            derived_from={},
            taxonomy_selector_facts={
                "schema_version": 1,
                "feature_fingerprint": feature_fingerprint,
            },
        )
    )
    case = await db_session.get(CaseModel, replay_source["case_ids"][0])
    assert case is not None
    case.test_point_id = test_point_id
    await db_session.commit()

    old_data = replay_source["assignments"].model_dump(mode="json")
    old_data["assignments"][0].update(
        {
            "assignment_source": "approved_mapping",
            "mapping_id": str(old_mapping_id),
        }
    )
    old_assignments = TaxonomyAssignmentSet.model_validate(old_data)
    old_result = await TaxonomyReplayService(db_session).replay(old_assignments, apply=False)
    assert old_result.mapped_count == 1

    await TaxonomyAdminService(db_session).activate(
        system_id=replay_source["system_id"],
        version=2,
        actor="taxonomy-reviewer-v2",
        apply=True,
    )
    new_data = old_assignments.model_dump(mode="json")
    new_data["taxonomy_version"] = 2
    new_data["manifest_hash"] = manifest_hash(v2_manifest)
    new_data["assignments"][0].update(
        {
            "target_stable_key": "asset-center.related-a",
            "related_stable_keys": ["asset-center.filter", "asset-center.related-b"],
            "mapping_id": str(new_mapping_id),
            "reason": "v2 人工确认调整主能力",
        }
    )
    new_assignments = TaxonomyAssignmentSet.model_validate(new_data)
    new_result = await TaxonomyReplayService(db_session).replay(new_assignments, apply=False)
    assert new_result.mapped_count == 1

    stale_data = old_assignments.model_dump(mode="json")
    stale_data["taxonomy_version"] = 2
    stale_data["manifest_hash"] = manifest_hash(v2_manifest)
    stale_assignments = TaxonomyAssignmentSet.model_validate(stale_data)
    with pytest.raises(TaxonomyReplayError, match="assignment_mapping_case_binding_unverifiable"):
        await TaxonomyReplayService(db_session).replay(stale_assignments, apply=False)


async def test_database_rejects_in_place_mutation_of_reviewed_mapping(
    db_session: AsyncSession,
    replay_source,
) -> None:
    mapping_id = await _add_approved_mapping(db_session, replay_source, feature_fingerprint="e" * 64)
    mapping = await db_session.get(RequirementTaxonomyMapping, mapping_id)
    assert mapping is not None
    mapping.reason = "绕过 supersede 的静默修改"

    with pytest.raises(DBAPIError, match="reviewed taxonomy mapping is immutable"):
        await db_session.commit()
    await db_session.rollback()

    with pytest.raises(DBAPIError, match="related concepts of reviewed mapping are immutable"):
        await db_session.execute(
            delete(RequirementTaxonomyMappingRelatedConcept).where(
                RequirementTaxonomyMappingRelatedConcept.mapping_id == mapping_id
            )
        )
        await db_session.commit()
    await db_session.rollback()


async def test_failed_iteration_releases_batch_for_retry(
    db_session: AsyncSession,
    replay_source,
    monkeypatch,
) -> None:
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None
    batch.status = "pending_review"
    await db_session.commit()
    service = IterationService()

    async def _fail_generation(**_kwargs):
        raise RuntimeError("generation failed")

    monkeypatch.setattr(service, "_rerun_write_cases", _fail_generation)
    with pytest.raises(RuntimeError, match="generation failed"):
        await service.iterate(
            replay_source["batch_id"],
            [str(replay_source["case_ids"][0])],
            {},
        )

    await db_session.rollback()
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None and batch.status == "pending_review"


async def test_iteration_rejects_taxonomy_frozen_batch(
    db_session: AsyncSession,
    replay_source,
) -> None:
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None
    batch.status = "pending_review"
    batch.taxonomy_version_id = replay_source["version_id"]
    await db_session.commit()

    with pytest.raises(ValueError, match="taxonomy is frozen"):
        await IterationService().iterate(
            replay_source["batch_id"],
            [str(replay_source["case_ids"][0])],
            {},
        )


async def test_all_pipeline_callbacks_and_resume_reject_taxonomy_frozen_batch(
    db_session: AsyncSession,
    replay_source,
) -> None:
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None
    batch.status = "running"
    batch.current_stage = "comprehend"
    batch.taxonomy_version_id = replay_source["version_id"]
    await db_session.commit()

    async def invoke(callback_name: str) -> None:
        batch_id = str(replay_source["batch_id"])
        if callback_name == "progress":
            await callback_tasks.on_stage_progress(batch_id, "parse")
        elif callback_name == "stage_complete":
            await callback_tasks.on_stage_complete(batch_id, "parse", {"late": True})
        elif callback_name == "pipeline_complete":
            await callback_tasks.on_pipeline_complete(batch_id, [], {}, [], [])
        elif callback_name == "failed":
            await callback_tasks.on_pipeline_failed(batch_id, "late failure", "parse")
        else:
            await callback_tasks.on_pipeline_suspended(batch_id, [])

    for callback_name in ("progress", "stage_complete", "pipeline_complete", "failed", "suspended"):
        with pytest.raises(ValueError, match="taxonomy is frozen"):
            await invoke(callback_name)

    stored = (
        await db_session.execute(
            select(BatchModel.status, BatchModel.current_stage).where(BatchModel.id == replay_source["batch_id"])
        )
    ).one()
    artifact_count = await db_session.scalar(
        select(func.count()).select_from(StageArtifact).where(StageArtifact.batch_id == replay_source["batch_id"])
    )
    assert stored == ("running", "comprehend")
    assert artifact_count == 0

    batch.status = "suspended"
    await db_session.commit()
    with pytest.raises(ValueError, match="taxonomy is frozen"):
        await _resume_pipeline(str(replay_source["batch_id"]), [])


async def test_iteration_rejects_case_from_another_batch(
    db_session: AsyncSession,
    replay_source,
) -> None:
    batch = await db_session.get(BatchModel, replay_source["batch_id"])
    assert batch is not None
    batch.status = "pending_review"
    other_batch_id = uuid.uuid4()
    other_case_id = uuid.uuid4()
    db_session.add(
        BatchModel(
            id=other_batch_id,
            document_id=replay_source["document_id"],
            system_id=replay_source["system_id"],
            status="pending_review",
        )
    )
    db_session.add(
        CaseModel(
            id=other_case_id,
            batch_id=other_batch_id,
            title="其他批次用例",
            preconditions=[],
            steps=[{"step": 1, "action": "执行", "expected": "成功"}],
            expected_results=["成功"],
            priority="P1",
            dimensions=["functional_correctness"],
            provenance={},
            trust_level=1,
        )
    )
    await db_session.commit()

    try:
        with pytest.raises(ValueError, match="do not all belong to batch"):
            await IterationService().iterate(replay_source["batch_id"], [str(other_case_id)], {})

        review_status = await db_session.scalar(select(CaseModel.review_status).where(CaseModel.id == other_case_id))
        assert review_status == "pending"
    finally:
        await db_session.rollback()
        await db_session.execute(delete(CaseModel).where(CaseModel.id == other_case_id))
        await db_session.execute(delete(BatchModel).where(BatchModel.id == other_batch_id))
        await db_session.commit()


async def _add_approved_mapping(
    db_session: AsyncSession,
    replay_source,
    *,
    feature_fingerprint: str,
    selector: dict | None = None,
) -> uuid.UUID:
    mapping_id = uuid.uuid4()
    document = await db_session.get(Document, replay_source["document_id"])
    assert document is not None
    parsed_selector = TaxonomySelector.model_validate(selector) if selector else None
    mapping = RequirementTaxonomyMapping(
        id=mapping_id,
        system_id=replay_source["system_id"],
        document_id=replay_source["document_id"],
        document_content_hash=document.content_hash,
        feature_fingerprint=feature_fingerprint,
        scope="test_point_selector" if selector else "feature_default",
        selector=selector,
        selector_hash=(parsed_selector.canonical_hash if parsed_selector else hashlib.sha256(b"{}").hexdigest()),
        concept_id=replay_source["concept_ids"]["asset-center.filter"],
        mapping_method="manual",
        confidence=1,
        reason="人工确认属于筛选能力",
        review_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        reviewed_taxonomy_version_id=replay_source["version_id"],
    )
    db_session.add(mapping)
    await db_session.flush()
    db_session.add_all(
        [
            RequirementTaxonomyMappingRelatedConcept(
                mapping_id=mapping.id,
                taxonomy_version_id=replay_source["version_id"],
                concept_id=replay_source["concept_ids"][stable_key],
            )
            for stable_key in ("asset-center.related-a", "asset-center.related-b")
        ]
    )
    await db_session.flush()
    mapping.reviewed_by = "reviewer"
    mapping.reviewed_at = datetime(2026, 7, 21, tzinfo=timezone.utc)
    mapping.review_status = "approved"
    await db_session.commit()
    return mapping_id
