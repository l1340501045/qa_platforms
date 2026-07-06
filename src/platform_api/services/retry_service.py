"""重试 Service — 批次失败重试逻辑"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.celery_app import celery_app
from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.enums import BatchStatus
from src.platform_api.models.testcase import StageArtifact, TestBatch
from src.platform_api.repositories.batch_repo import BatchRepository


class RetryService:
    """批次重试逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.batch_repo = BatchRepository(session)

    async def retry_batch(self, batch_id: UUID) -> dict:
        """
        重试失败的批次

        逻辑：
        1. 验证批次存在且 status == failed
        2. 尝试获取 checkpoint（最后成功的 stage）
        3. 有 checkpoint → 从失败阶段恢复；无 checkpoint → 降级整批重跑
        4. 更新状态为 running，发布 Celery 任务

        Returns:
            dict: {batch_id, status, fallback, resumed_from_stage}
        """
        batch = await self.batch_repo.get_by_id(batch_id)
        if batch is None:
            raise ApiError("E4041", "批次不存在")

        if batch.status == BatchStatus.PENDING:
            await self._redispatch_pending(batch)
            return {
                "batch_id": batch.id,
                "status": batch.status,
                "fallback": True,
                "resumed_from_stage": None,
            }

        if batch.status != BatchStatus.FAILED:
            raise ApiError("E4092", "批次状态非 failed/pending，不可重试")

        # 尝试获取 checkpoint
        checkpoint = await self._get_checkpoint(batch_id)

        if checkpoint:
            # 从失败阶段恢复
            resumed_from_stage = checkpoint["failed_stage"]
            await self._resume_pipeline(batch, resumed_from_stage)
            return {
                "batch_id": batch.id,
                "status": "running",
                "fallback": False,
                "resumed_from_stage": resumed_from_stage,
            }
        else:
            # 降级：重置所有 artifacts，整批重跑
            await self._reset_artifacts(batch_id)
            await self._dispatch_full_pipeline(batch)
            return {
                "batch_id": batch.id,
                "status": "running",
                "fallback": True,
                "resumed_from_stage": None,
            }

    async def _get_checkpoint(self, batch_id: UUID) -> dict | None:
        """
        获取批次的 checkpoint 信息

        查找最后一个 failed 的 stage_artifact，返回 {failed_stage}
        """
        stmt = (
            select(StageArtifact)
            .where(StageArtifact.batch_id == batch_id)
            .where(StageArtifact.status == "failed")
            .order_by(StageArtifact.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        artifact = result.scalar_one_or_none()

        if artifact is None:
            return None

        return {"failed_stage": artifact.stage}

    async def _resume_pipeline(self, batch: TestBatch, from_stage: str):
        """从指定阶段恢复 pipeline"""
        batch.status = BatchStatus.RUNNING
        batch.current_stage = from_stage
        await self.session.flush()

        celery_app.send_task(
            "testcase_generator.run_pipeline",
            kwargs={
                "batch_id": str(batch.id),
                "document_id": str(batch.document_id),
                "system_id": str(batch.system_id),
                "config": batch.generation_config,
                "resume_from": from_stage,
            },
            queue="testcase_generation",
        )

    async def _reset_artifacts(self, batch_id: UUID):
        """清除所有 stage artifacts（降级重跑前）"""
        stmt = select(StageArtifact).where(StageArtifact.batch_id == batch_id)
        result = await self.session.execute(stmt)
        for artifact in result.scalars().all():
            await self.session.delete(artifact)
        await self.session.flush()

    async def _dispatch_full_pipeline(self, batch: TestBatch):
        """降级整批重跑"""
        batch.status = BatchStatus.RUNNING
        batch.current_stage = None
        await self.session.flush()

        self._send_pipeline_task(batch)

    async def _redispatch_pending(self, batch: TestBatch):
        """pending 批次重新入队（worker 未启动或任务丢失时）"""
        task_result = self._send_pipeline_task(batch)
        batch.celery_task_id = task_result.id
        await self.session.flush()

    def _send_pipeline_task(self, batch: TestBatch):
        return celery_app.send_task(
            "testcase_generator.run_pipeline",
            kwargs={
                "batch_id": str(batch.id),
                "document_id": str(batch.document_id),
                "system_id": str(batch.system_id),
                "config": batch.generation_config,
            },
            queue="testcase_generation",
        )
