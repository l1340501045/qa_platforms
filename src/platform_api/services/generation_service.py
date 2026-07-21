"""用例生成编排 service — 触发生成、查询状态、获取详情"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.celery_app import celery_app
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.stage_names import to_progress_canonical
from src.platform_api.models.enums import BatchStatus
from src.platform_api.models.knowledge import Document
from src.platform_api.models.testcase import StageArtifact, TestBatch
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.batch import BatchResponse, BatchStatusResponse


class GenerationService:
    """用例生成编排逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, TestBatch)

    async def trigger_generation(self, document_id: UUID, system_id: UUID, config: dict | None) -> BatchResponse:
        """
        1. 创建 test_batches 记录（status=pending）
        2. 发布 Celery 任务 run_pipeline_task.delay(batch_id, document_id, system_id, config)
        3. 更新 status=running, celery_task_id
        4. 返回 BatchResponse
        """
        # 1. 批次不永久绑定模型版本；Worker 真正开始执行时读取当前有效配置。
        batch = await self.repo.create(
            document_id=document_id,
            system_id=system_id,
            status=BatchStatus.PENDING,
            generation_config=config,
        )

        # 2. 发布 Celery 任务
        task_result = celery_app.send_task(
            "testcase_generator.run_pipeline",
            kwargs={
                "batch_id": str(batch.id),
                "document_id": str(document_id),
                "system_id": str(system_id),
                "config": config,
            },
            queue="testcase_generation",
        )

        # 3. 记录 Celery task_id；状态保持 pending（"已入队，等待 worker 拾取"）。
        #    真正的 running/started_at 由 worker 在开始执行时写入，避免无 worker 时
        #    UI 长期显示 running 却零进展的误导。
        batch.celery_task_id = task_result.id
        await self.session.flush()
        await self.session.refresh(batch)

        # 4. 返回响应
        return BatchResponse(
            id=batch.id,
            document_id=batch.document_id,
            system_id=batch.system_id,
            status=batch.status,
            current_stage=to_progress_canonical(batch.current_stage) if batch.current_stage else None,
            total_cases=batch.total_cases,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )

    async def get_batch_status(self, batch_id: UUID) -> BatchStatusResponse:
        """查询批次状态（含 open_questions 如果 suspended）"""
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise ApiError("E4041", "批次不存在")

        open_questions: list[dict] | None = None
        if batch.status == BatchStatus.SUSPENDED:
            # 查询最新的 suspended stage_artifact 获取 open_questions
            stmt = (
                select(StageArtifact)
                .where(
                    StageArtifact.batch_id == batch_id,
                    StageArtifact.status == "suspended",
                )
                .order_by(StageArtifact.created_at.desc())
                .limit(1)
            )
            result = await self.session.execute(stmt)
            artifact = result.scalar_one_or_none()
            if artifact and artifact.open_questions:
                open_questions = artifact.open_questions

        return BatchStatusResponse(
            id=batch.id,
            status=batch.status,
            current_stage=to_progress_canonical(batch.current_stage) if batch.current_stage else None,
            total_cases=batch.total_cases,
            open_questions=open_questions,
        )

    async def get_batch_detail(self, batch_id: UUID) -> BatchResponse:
        """获取批次完整详情（含 document_title）"""
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise ApiError("E4041", "批次不存在")

        # 查询关联文档的 title
        document_title: str | None = None
        if batch.document_id:
            stmt = select(Document.title).where(Document.id == batch.document_id)
            result = await self.session.execute(stmt)
            document_title = result.scalar_one_or_none()

        return BatchResponse(
            id=batch.id,
            document_id=batch.document_id,
            system_id=batch.system_id,
            status=batch.status,
            current_stage=to_progress_canonical(batch.current_stage) if batch.current_stage else None,
            total_cases=batch.total_cases,
            document_title=document_title,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            created_at=batch.created_at,
            updated_at=batch.updated_at,
        )
