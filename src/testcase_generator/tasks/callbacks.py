"""T040: Celery 任务状态回调 — 进度通知 + 异常上报"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import update

from src.testcase_generator.db import async_session_factory
from src.platform_api.models.testcase import TestBatch, TestCase, TestPoint, StageArtifact
from src.platform_api.models.enums import BatchStatus, ReviewStatus

logger = logging.getLogger(__name__)


async def on_stage_complete(batch_id: str, stage: str, artifact: dict) -> None:
    """单阶段完成回调：更新 batch.current_stage + 写入 stage_artifacts"""
    async with async_session_factory() as session:
        # 更新 batch current_stage
        stmt = update(TestBatch).where(TestBatch.id == batch_id).values(current_stage=stage)
        await session.execute(stmt)

        # 写入 stage_artifacts
        stage_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=uuid.UUID(batch_id),
            stage=stage,
            status="completed",
            artifact=artifact,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(stage_artifact)
        await session.commit()

    logger.info("Stage '%s' completed for batch %s", stage, batch_id)


async def on_pipeline_complete(
    batch_id: str,
    final_cases: list,
    audit_report: dict,
    test_points: list | None = None,
) -> None:
    """流水线完成回调：status→pending_review, 写入 test_points + test_cases

    流程（严格顺序）：
    1. 先写入 test_points 到 testcase.test_points 表，获取 PK 映射
    2. 再写入 test_cases，用 test_point_id 真实 FK 指向落库后的 PK
    3. 更新 batch 状态
    """
    batch_uuid = uuid.UUID(batch_id)

    async with async_session_factory() as session:
        # ── 1. 写入 test_points ──────────────────────────────────────
        # tp_id_str → test_points 表的 UUID PK 映射
        tp_id_map: dict[str, uuid.UUID] = {}

        if test_points:
            for tp_data in test_points:
                if isinstance(tp_data, dict):
                    tp_pk = uuid.uuid4()
                    tp_record = TestPoint(
                        id=tp_pk,
                        batch_id=batch_uuid,
                        feature_id=tp_data.get("feature_id", ""),
                        dimension=tp_data.get("dimension", ""),
                        description=tp_data.get("description", ""),
                        priority=tp_data.get("priority", "P2"),
                        derived_from=tp_data.get("derived_from", []),
                    )
                    session.add(tp_record)
                    # 用测试点的逻辑 ID（如 "TP-001"）做映射键
                    tp_logical_id = tp_data.get("id", "")
                    tp_id_map[tp_logical_id] = tp_pk

            # flush 确保 PK 已持久化，后续 FK 可引用
            await session.flush()

        # ── 2. 写入 test_cases ───────────────────────────────────────
        for case_data in final_cases:
            if not isinstance(case_data, dict):
                continue

            # 通过 test_point_id 逻辑 ID 查找真实 FK
            tp_logical_id = case_data.get("test_point_id", "")
            test_point_fk = tp_id_map.get(tp_logical_id)

            verification = case_data.get("verification") or {}

            test_case = TestCase(
                id=uuid.uuid4(),
                batch_id=batch_uuid,
                test_point_id=test_point_fk,
                title=case_data.get("title", ""),
                preconditions=case_data.get("preconditions", []),
                steps=case_data.get("steps", []),
                expected_results=case_data.get("expected_results", []),
                priority=case_data.get("priority", "P2"),
                dimensions=case_data.get("dimensions", []),
                provenance=case_data.get("provenance", {}),
                trust_level=case_data.get("trust_level", 3),
                confidence_note=case_data.get("confidence_note"),
                review_status=ReviewStatus.PENDING,
                iteration=1,
                verdict=verification.get("verdict"),
                bucket=verification.get("bucket"),
                verification=verification or None,
                duplicate_of=case_data.get("duplicate_of"),
            )
            session.add(test_case)

        # ── 3. 更新 batch 状态 ───────────────────────────────────────
        total_cases = len(final_cases)
        stmt = (
            update(TestBatch)
            .where(TestBatch.id == batch_id)
            .values(
                status=BatchStatus.PENDING_REVIEW,
                current_stage="export",
                total_cases=total_cases,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(stmt)

        # 写入审计报告作为 stage artifact
        audit_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=batch_uuid,
            stage="review",
            status="completed",
            artifact=audit_report,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(audit_artifact)

        await session.commit()

    logger.info(
        "Pipeline completed for batch %s: %d test_points, %d test_cases persisted",
        batch_id,
        len(tp_id_map),
        len(final_cases),
    )


async def on_pipeline_failed(batch_id: str, error: str, stage: str) -> None:
    """失败回调：status→failed, 记录错误"""
    async with async_session_factory() as session:
        stmt = (
            update(TestBatch)
            .where(TestBatch.id == batch_id)
            .values(
                status=BatchStatus.FAILED,
                current_stage=stage,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(stmt)

        fail_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=uuid.UUID(batch_id),
            stage=stage,
            status="failed",
            artifact={"error": error},
            completed_at=datetime.now(timezone.utc),
        )
        session.add(fail_artifact)

        await session.commit()

    logger.error("Pipeline failed at stage '%s' for batch %s: %s", stage, batch_id, error)


async def on_pipeline_suspended(batch_id: str, open_questions: list) -> None:
    """Gate NO_GO 挂起回调：status→suspended, 写入 open_questions 到 stage_artifacts"""
    async with async_session_factory() as session:
        stmt = (
            update(TestBatch)
            .where(TestBatch.id == batch_id)
            .values(
                status=BatchStatus.SUSPENDED,
                current_stage="comprehend",
            )
        )
        await session.execute(stmt)

        suspend_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=uuid.UUID(batch_id),
            stage="comprehend",
            status="suspended",
            open_questions=open_questions,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(suspend_artifact)

        await session.commit()

    logger.warning("Pipeline suspended for batch %s with %d open questions", batch_id, len(open_questions))
