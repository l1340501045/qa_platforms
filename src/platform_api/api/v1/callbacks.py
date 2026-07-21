"""Worker → API 回调端点（内部使用，不对外暴露给前端）

Pipeline worker 通过这些端点通知 API 层阶段完成/失败/挂起等事件。
实际回调逻辑已在 testcase_generator/tasks/callbacks.py 中直接操作 DB，
此处提供 HTTP 端点作为备选通信通道（例如跨进程/跨网络部署场景）。

CHG-20260609-001: 在 pipeline 完成/失败/挂起回调中自动创建通知。
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.stage_names import to_progress_internal
from src.platform_api.models.enums import BatchStatus
from src.platform_api.models.testcase import StageArtifact, TestBatch
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.services.notification_service import NotificationService

router = APIRouter(prefix="/internal/callbacks", tags=["内部回调"])


# ─── Request schemas ───


class StageCompleteRequest(BaseModel):
    batch_id: str
    stage: str
    artifact: dict


class PipelineCompleteRequest(BaseModel):
    batch_id: str
    total_cases: int
    audit_report: dict | None = None


class PipelineFailedRequest(BaseModel):
    batch_id: str
    error: str
    stage: str


class PipelineSuspendedRequest(BaseModel):
    batch_id: str
    open_questions: list


# ─── Endpoints ───


@router.post("/stage-complete")
async def stage_complete_callback(
    data: StageCompleteRequest,
    session: AsyncSession = Depends(get_session),
):
    """单阶段完成回调"""
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(UUID(data.batch_id))
    stage = to_progress_internal(data.stage)
    if batch:
        batch.current_stage = stage
        await session.flush()

    # 写入 stage artifact
    artifact = StageArtifact(
        batch_id=UUID(data.batch_id),
        stage=stage,
        status="completed",
        artifact=data.artifact,
    )
    session.add(artifact)
    await session.flush()

    return {"code": "OK", "message": "stage complete callback received"}


@router.post("/pipeline-complete")
async def pipeline_complete_callback(
    data: PipelineCompleteRequest,
    session: AsyncSession = Depends(get_session),
):
    """流水线完成回调"""
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(UUID(data.batch_id))
    if batch:
        batch.status = BatchStatus.PENDING_REVIEW
        batch.total_cases = data.total_cases
        batch.current_stage = "export"
        await session.flush()

        # 创建通知
        notification_service = NotificationService(session)
        await notification_service.create_notification(
            type="batch_completed",
            title="用例生成完成",
            body=f"共生成 {data.total_cases} 条用例，请前往 Review",
            target_type="batch",
            target_id=batch.id,
        )

    return {"code": "OK", "message": "pipeline complete callback received"}


@router.post("/pipeline-failed")
async def pipeline_failed_callback(
    data: PipelineFailedRequest,
    session: AsyncSession = Depends(get_session),
):
    """流水线失败回调"""
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(UUID(data.batch_id))
    if batch:
        batch.status = BatchStatus.FAILED
        batch.current_stage = data.stage
        await session.flush()

        # 创建通知
        notification_service = NotificationService(session)
        await notification_service.create_notification(
            type="batch_failed",
            title="用例生成失败",
            body=f"在 {data.stage} 阶段发生错误，可尝试重试",
            target_type="batch",
            target_id=batch.id,
        )

    # 写入失败 artifact
    artifact = StageArtifact(
        batch_id=UUID(data.batch_id),
        stage=data.stage,
        status="failed",
        artifact={"error": data.error},
    )
    session.add(artifact)
    await session.flush()

    return {"code": "OK", "message": "pipeline failed callback received"}


@router.post("/pipeline-suspended")
async def pipeline_suspended_callback(
    data: PipelineSuspendedRequest,
    session: AsyncSession = Depends(get_session),
):
    """Gate NO_GO 挂起回调"""
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(UUID(data.batch_id))
    if batch:
        batch.status = BatchStatus.SUSPENDED
        batch.current_stage = "gate"
        await session.flush()

        # 创建通知
        notification_service = NotificationService(session)
        await notification_service.create_notification(
            type="batch_suspended",
            title="用例生成需要人工确认",
            body=f"有 {len(data.open_questions)} 个问题需要确认",
            target_type="batch",
            target_id=batch.id,
        )

    # 写入挂起 artifact
    artifact = StageArtifact(
        batch_id=UUID(data.batch_id),
        stage="comprehend",
        status="suspended",
        open_questions=data.open_questions,
    )
    session.add(artifact)
    await session.flush()

    return {"code": "OK", "message": "pipeline suspended callback received"}
