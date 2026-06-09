"""Worker → API 回调端点（内部使用，不对外暴露给前端）

Pipeline worker 通过这些端点通知 API 层阶段完成/失败/挂起等事件。
实际回调逻辑已在 testcase_generator/tasks/callbacks.py 中直接操作 DB，
此处提供 HTTP 端点作为备选通信通道（例如跨进程/跨网络部署场景）。
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.models.enums import BatchStatus
from src.platform_api.models.testcase import StageArtifact, TestBatch
from src.platform_api.repositories.base import BaseRepository

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
    if batch:
        batch.current_stage = data.stage
        await session.flush()

    # 写入 stage artifact
    artifact = StageArtifact(
        batch_id=UUID(data.batch_id),
        stage=data.stage,
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
        batch.current_stage = "comprehend"
        await session.flush()

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
