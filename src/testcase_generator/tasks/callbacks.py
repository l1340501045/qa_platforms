"""T040: Celery 任务状态回调 — 进度通知 + 异常上报"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.stage_names import to_progress_internal
from src.platform_api.models.enums import BatchStatus, ReviewStatus
from src.platform_api.models.testcase import Rule, StageArtifact, TestBatch, TestCase, TestPoint
from src.testcase_generator.db import async_session_factory

logger = logging.getLogger(__name__)


async def _lock_unfrozen_batch(
    session: AsyncSession,
    batch_id: uuid.UUID,
    *,
    allowed_statuses: frozenset[str],
) -> TestBatch:
    """串行化流水线回调，并拒绝覆盖已固定 taxonomy 的历史批次。"""
    batch = (
        await session.execute(select(TestBatch).where(TestBatch.id == batch_id).with_for_update())
    ).scalar_one_or_none()
    if batch is None:
        raise ValueError(f"Batch {batch_id} not found")
    if batch.taxonomy_version_id is not None:
        raise ValueError(f"Batch {batch_id} taxonomy is frozen")
    if batch.status not in allowed_statuses:
        raise ValueError(f"Batch {batch_id} changed before pipeline callback: status={batch.status}")
    return batch


async def on_stage_progress(batch_id: str, stage: str) -> None:
    """阶段运行中回调：仅推进 batch.current_stage，供前端实时展示。"""
    progress_stage = to_progress_internal(stage)
    batch_uuid = uuid.UUID(batch_id)
    async with async_session_factory() as session:
        batch = await _lock_unfrozen_batch(
            session,
            batch_uuid,
            allowed_statuses=frozenset({BatchStatus.RUNNING}),
        )
        batch.current_stage = progress_stage
        await session.commit()

    logger.info("Stage progress for batch %s → %s", batch_id, progress_stage)


async def on_stage_complete(
    batch_id: str,
    stage: str,
    artifact: dict,
    current_stage: str | None = None,
) -> None:
    """单阶段完成回调：更新 batch.current_stage + 写入 stage_artifacts"""
    artifact_stage = to_progress_internal(stage)
    progress_stage = to_progress_internal(current_stage or stage)
    batch_uuid = uuid.UUID(batch_id)
    async with async_session_factory() as session:
        batch = await _lock_unfrozen_batch(
            session,
            batch_uuid,
            allowed_statuses=frozenset({BatchStatus.RUNNING, BatchStatus.PENDING_REVIEW}),
        )
        batch.current_stage = progress_stage

        # 写入 stage_artifacts
        stage_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=batch_uuid,
            stage=artifact_stage,
            status="completed",
            artifact=artifact,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(stage_artifact)
        await session.commit()

    logger.info("Stage '%s' completed for batch %s; progress → %s", artifact_stage, batch_id, progress_stage)


async def on_pipeline_complete(
    batch_id: str,
    final_cases: list,
    audit_report: dict,
    test_points: list | None = None,
    rules: list | None = None,
) -> None:
    """流水线完成回调：status→pending_review, 写入 rules + test_points + test_cases

    流程（严格顺序）：
    0. 先写入规则台账 testcase.rules，建 rule_code → rules.id(uuid) 映射
    1. 写入 test_points 到 testcase.test_points 表，获取 PK 映射；用规则码映射回填 rule_id
    2. 再写入 test_cases，用 test_point_id 真实 FK 指向落库后的 PK
    3. 更新 batch 状态
    """
    batch_uuid = uuid.UUID(batch_id)

    async with async_session_factory() as session:
        batch = await _lock_unfrozen_batch(
            session,
            batch_uuid,
            allowed_statuses=frozenset({BatchStatus.RUNNING}),
        )

        # ── 0. 写入规则台账 ──────────────────────────────────────────
        # rule_code（如 "R-001"）→ rules 表 UUID PK 映射，供 test_points.rule_id 解析
        rule_code_map: dict[str, uuid.UUID] = {}
        if rules:
            for r in rules:
                if not isinstance(r, dict):
                    continue
                code = r.get("rule_code", "")
                if not code:
                    continue
                rule_pk = uuid.uuid4()
                session.add(
                    Rule(
                        id=rule_pk,
                        batch_id=batch_uuid,
                        rule_code=code,
                        module=r.get("module", ""),
                        rule=r.get("rule", ""),
                        source_quote=r.get("source_quote", ""),
                        category=r.get("category", ""),
                    )
                )
                rule_code_map[code] = rule_pk

        # ── 1. 写入 test_points ──────────────────────────────────────
        # tp_id_str → test_points 表的 UUID PK 映射
        tp_id_map: dict[str, uuid.UUID] = {}

        if test_points:
            for tp_data in test_points:
                if isinstance(tp_data, dict):
                    tp_pk = uuid.uuid4()
                    # rule_id 在 state 里是规则码字符串（如 "R-001"），落库时解析为 rules.id 真实 uuid
                    rule_code = tp_data.get("rule_id")
                    tp_record = TestPoint(
                        id=tp_pk,
                        batch_id=batch_uuid,
                        feature_id=tp_data.get("feature_id", ""),
                        dimension=tp_data.get("dimension", ""),
                        description=tp_data.get("description", ""),
                        priority=tp_data.get("priority", "P2"),
                        derived_from=tp_data.get("derived_from", []),
                        rule_id=rule_code_map.get(rule_code) if rule_code else None,
                    )
                    session.add(tp_record)
                    # 用测试点的逻辑 ID（如 "TP-001"）做映射键
                    tp_logical_id = tp_data.get("id", "")
                    tp_id_map[tp_logical_id] = tp_pk

            # flush 确保 PK 已持久化，后续 FK 可引用
            await session.flush()

        # ── 2. 写入 test_cases ───────────────────────────────────────
        # 预分配 UUID（按用例逻辑 id 建映射），以便把 duplicate_of 的逻辑 id 解析为真实 UUID
        case_uuid_of: dict[str, uuid.UUID] = {}
        for case_data in final_cases:
            if isinstance(case_data, dict):
                logical_id = case_data.get("id", "")
                if logical_id:
                    case_uuid_of[logical_id] = uuid.uuid4()

        for case_data in final_cases:
            if not isinstance(case_data, dict):
                continue

            # 通过 test_point_id 逻辑 ID 查找真实 FK
            tp_logical_id = case_data.get("test_point_id", "")
            test_point_fk = tp_id_map.get(tp_logical_id)

            verification = case_data.get("verification") or {}

            case_uuid = case_uuid_of.get(case_data.get("id", "")) or uuid.uuid4()

            # duplicate_of 逻辑 id → 规范用例真实 UUID（解析不到/指向自身则置空，不写悬空或自引用）
            dup_logical = case_data.get("duplicate_of")
            dup_fk = case_uuid_of.get(dup_logical) if dup_logical else None
            if dup_fk == case_uuid:
                dup_fk = None

            test_case = TestCase(
                id=case_uuid,
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
                duplicate_of=dup_fk,
            )
            session.add(test_case)

        # ── 3. 更新 batch 状态 ───────────────────────────────────────
        total_cases = len(final_cases)
        batch.status = BatchStatus.PENDING_REVIEW
        batch.current_stage = "export"
        batch.total_cases = total_cases
        batch.completed_at = datetime.now(timezone.utc)

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
        "Pipeline completed for batch %s: %d rules, %d test_points, %d test_cases persisted",
        batch_id,
        len(rule_code_map),
        len(tp_id_map),
        len(final_cases),
    )


async def on_pipeline_failed(batch_id: str, error: str, stage: str) -> None:
    """失败回调：status→failed, 记录错误"""
    batch_uuid = uuid.UUID(batch_id)
    async with async_session_factory() as session:
        batch = await _lock_unfrozen_batch(
            session,
            batch_uuid,
            allowed_statuses=frozenset({BatchStatus.RUNNING, BatchStatus.PENDING_REVIEW}),
        )
        batch.status = BatchStatus.FAILED
        batch.current_stage = stage
        batch.completed_at = datetime.now(timezone.utc)

        fail_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=batch_uuid,
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
    batch_uuid = uuid.UUID(batch_id)
    async with async_session_factory() as session:
        batch = await _lock_unfrozen_batch(
            session,
            batch_uuid,
            allowed_statuses=frozenset({BatchStatus.RUNNING}),
        )
        batch.status = BatchStatus.SUSPENDED
        batch.current_stage = "gate"

        suspend_artifact = StageArtifact(
            id=uuid.uuid4(),
            batch_id=batch_uuid,
            stage="comprehend",
            status="suspended",
            open_questions=open_questions,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(suspend_artifact)

        await session.commit()

    logger.warning("Pipeline suspended for batch %s with %d open questions", batch_id, len(open_questions))
