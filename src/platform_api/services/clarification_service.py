"""Gate NO_GO 澄清 service — 提交人工澄清答案并恢复流水线"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.celery_app import celery_app
from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.enums import BatchStatus
from src.platform_api.models.testcase import StageArtifact, TestBatch
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.batch import BatchStatusResponse


class ClarificationService:
    """Gate NO_GO 澄清服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, TestBatch)

    async def submit_clarification(self, batch_id: UUID, answers: list[dict]) -> BatchStatusResponse:
        """
        1. 验证 batch status = suspended
        2. 写入 answers 到 stage_artifacts（type=clarification）
        3. 发布 resume_pipeline_task.delay(batch_id, answers)
        4. 更新 status=running
        """
        # 1. 验证状态
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise ApiError("E4041", "批次不存在")

        if batch.status != BatchStatus.SUSPENDED:
            raise ApiError("E4001", f"批次当前状态为 '{batch.status}'，仅 suspended 状态可提交澄清")

        # 2. 写入 clarification artifact
        clarification_artifact = StageArtifact(
            batch_id=batch_id,
            stage="clarification",
            status="completed",
            clarification_answers=answers,
        )
        self.session.add(clarification_artifact)

        # 3. 发布恢复任务
        celery_app.send_task(
            "testcase_generator.resume_pipeline",
            kwargs={
                "batch_id": str(batch_id),
                "clarification_answers": answers,
            },
            queue="testcase_generation",
        )

        # 4. 更新 batch 状态
        batch.status = BatchStatus.RUNNING
        await self.session.flush()
        await self.session.refresh(batch)

        return BatchStatusResponse(
            id=batch.id,
            status=batch.status,
            current_stage=batch.current_stage,
            total_cases=batch.total_cases,
            open_questions=None,
        )
