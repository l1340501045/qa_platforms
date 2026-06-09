"""批次 API — 对外暴露给前端

包含：触发生成、获取详情（合并状态+用例）、提交澄清、触发迭代、落库归档、独立用例分页
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.core.stage_names import PIPELINE_STAGES, to_canonical
from src.platform_api.schemas.batch import (
    BatchResponse,
    ClarificationRequest,
    GenerateRequest,
    IterateRequest,
)
from src.platform_api.services.clarification_service import ClarificationService
from src.platform_api.services.generation_service import GenerationService
from src.platform_api.services.review_service import ReviewService

router = APIRouter(tags=["批次管理"])


def _get_generation_service(session: AsyncSession = Depends(get_session)) -> GenerationService:
    return GenerationService(session)


def _get_clarification_service(session: AsyncSession = Depends(get_session)) -> ClarificationService:
    return ClarificationService(session)


def _get_review_service(session: AsyncSession = Depends(get_session)) -> ReviewService:
    return ReviewService(session)


# ─── 触发生成 ───


@router.post("/documents/{document_id}/generate", status_code=202)
async def trigger_generation(
    document_id: UUID,
    body: GenerateRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    """触发用例生成 — 创建批次并启动 pipeline"""
    from src.platform_api.models.knowledge import Document
    from src.platform_api.repositories.base import BaseRepository

    # 验证文档存在
    doc_repo = BaseRepository(session, Document)
    doc = await doc_repo.get_by_id(document_id)
    if doc is None:
        raise ApiError("E4041", "文档不存在")

    service = GenerationService(session)
    config = body.config if body else None
    batch_resp = await service.trigger_generation(
        document_id=document_id,
        system_id=doc.system_id,
        config=config,
    )
    return JSONResponse(status_code=202, content=success({"batch_id": str(batch_resp.id)}))


# ─── 获取批次详情（合并响应：batch + stage_progress + cases + open_questions） ───


@router.get("/batches/{batch_id}")
async def get_batch_detail(
    batch_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    review_status: str | None = Query(None, description="按 review 状态过滤"),
    session: AsyncSession = Depends(get_session),
):
    """获取批次完整详情（合并批次信息、阶段进度、用例列表）"""
    gen_service = GenerationService(session)
    review_service = ReviewService(session)

    # 获取批次基础信息
    batch_resp = await gen_service.get_batch_detail(batch_id)

    # 获取阶段进度（获取 batch_status 含 open_questions）
    status_resp = await gen_service.get_batch_status(batch_id)

    # 构建 stage_progress
    current_stage = batch_resp.current_stage
    stages = _build_stage_progress(current_stage, batch_resp.status)

    # 计算进度汇总字段
    completed_stages = sum(1 for s in stages if s["status"] == "completed")
    total_stages = len(PIPELINE_STAGES)
    progress_pct = round(completed_stages / total_stages * 100) if total_stages > 0 else 0

    # 获取用例分页
    params = PaginationParams(page=page, per_page=per_page)
    cases_resp = await review_service.get_cases_by_batch(
        batch_id=batch_id,
        review_status=review_status,
        offset=params.offset,
        limit=params.limit,
    )

    data = {
        "batch": {
            "id": str(batch_resp.id),
            "document_id": str(batch_resp.document_id),
            "document_title": batch_resp.document_title,
            "system_id": str(batch_resp.system_id),
            "status": batch_resp.status,
            "current_stage": current_stage,
            "total_cases": batch_resp.total_cases,
            "started_at": batch_resp.started_at.isoformat() if batch_resp.started_at else None,
            "completed_at": batch_resp.completed_at.isoformat() if batch_resp.completed_at else None,
            "created_at": batch_resp.created_at.isoformat() if batch_resp.created_at else None,
        },
        "stage_progress": {
            "current_stage": current_stage,
            "stage_progress": progress_pct,
            "total_stages": total_stages,
            "completed_stages": completed_stages,
            "stages": stages,
        },
        "cases": paginated_response(
            items=cases_resp.items,
            total=cases_resp.total,
            params=params,
        ),
        "open_questions": status_resp.open_questions,
    }

    return success(data)


# ─── 提交澄清答案 ───


@router.post("/batches/{batch_id}/clarify")
async def submit_clarification(
    batch_id: UUID,
    body: ClarificationRequest,
    service: ClarificationService = Depends(_get_clarification_service),
):
    """提交 Gate NO_GO 澄清答案"""
    result = await service.submit_clarification(batch_id=batch_id, answers=body.answers)
    return success(
        {
            "batch_id": str(result.id),
            "status": result.status,
            "message": "澄清已提交，生成任务已恢复",
        }
    )


# ─── 触发迭代 ───


@router.post("/batches/{batch_id}/iterate", status_code=202)
async def trigger_iterate(
    batch_id: UUID,
    body: IterateRequest,
    session: AsyncSession = Depends(get_session),
):
    """触发迭代 — 基于人工反馈重跑部分用例生成"""
    from src.platform_api.models.enums import BatchStatus
    from src.platform_api.models.testcase import TestBatch
    from src.platform_api.repositories.base import BaseRepository
    from src.testcase_generator.services.iteration_service import IterationService

    # 验证 batch 存在并检查状态
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(batch_id)
    if batch is None:
        raise ApiError("E4041", "批次不存在")

    if batch.status not in (BatchStatus.PENDING_REVIEW, BatchStatus.REVIEWING):
        raise ApiError("E4001", f"批次当前状态为 '{batch.status}'，仅 pending_review/reviewing 可迭代")

    # 调用迭代服务
    iteration_service = IterationService()
    await iteration_service.iterate(
        batch_id=batch_id,
        modified_case_ids=body.modified_case_ids,
        feedback=body.feedback or {},
    )

    # 刷新 batch 状态
    await session.refresh(batch)
    return JSONResponse(
        status_code=202,
        content=success(
            {
                "batch_id": str(batch.id),
                "status": batch.status,
                "iteration": getattr(batch, "iteration", 2),
                "cases_to_regenerate": len(body.modified_case_ids),
            }
        ),
    )


# ─── 落库归档 ───


@router.post("/batches/{batch_id}/archive")
async def archive_batch(
    batch_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """落库归档 — 所有用例 confirmed 后归档"""
    from src.platform_api.models.testcase import TestBatch
    from src.platform_api.repositories.base import BaseRepository
    from src.testcase_generator.services.persist_service import PersistService

    # 验证 batch 存在
    batch_repo = BaseRepository(session, TestBatch)
    batch = await batch_repo.get_by_id(batch_id)
    if batch is None:
        raise ApiError("E4041", "批次不存在")

    # 调用归档服务
    persist_service = PersistService()
    try:
        await persist_service.archive_batch(batch_id)
    except ValueError as e:
        raise ApiError("E4001", str(e))
    except RuntimeError as e:
        raise ApiError("E4091", str(e))

    # 刷新 batch 状态
    await session.refresh(batch)
    return success(
        {
            "batch_id": str(batch.id),
            "status": batch.status,
            "archived_count": batch.total_cases,
            "archived_at": batch.updated_at.isoformat() if batch.updated_at else None,
        }
    )


# ─── 获取批次用例列表（独立分页端点） ───


@router.get("/batches/{batch_id}/cases")
async def get_batch_cases(
    batch_id: UUID,
    review_status: str | None = Query(None, description="按 review 状态过滤"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: ReviewService = Depends(_get_review_service),
):
    """获取批次用例列表"""
    params = PaginationParams(page=page, per_page=per_page)
    result = await service.get_cases_by_batch(
        batch_id=batch_id,
        review_status=review_status,
        offset=params.offset,
        limit=params.limit,
    )
    return success(paginated_response(result.items, result.total, params))


# ─── 内部辅助函数 ───


def _build_stage_progress(current_stage: str | None, batch_status: str) -> list[dict]:
    """根据当前阶段和批次状态构建阶段进度列表"""
    stages = []
    current_found = False

    for stage_name in PIPELINE_STAGES:
        if batch_status in ("completed", "pending_review", "reviewing", "archived"):
            # 所有阶段都已完成
            stages.append({"name": stage_name, "status": "completed"})
        elif batch_status == "failed":
            if current_stage is None:
                # 无当前阶段信息：无法定位失败点，全部标 pending
                stages.append({"name": stage_name, "status": "pending"})
            elif stage_name == current_stage:
                stages.append({"name": stage_name, "status": "failed"})
                current_found = True
            elif current_found:
                stages.append({"name": stage_name, "status": "pending"})
            else:
                stages.append({"name": stage_name, "status": "completed"})
        else:
            # running / suspended / pending
            if current_stage is None:
                # 无当前阶段（pending 或刚 running 尚未写入）：全部 pending
                stages.append({"name": stage_name, "status": "pending"})
            elif stage_name == current_stage:
                status = "running" if batch_status == "running" else "pending"
                if batch_status == "suspended" and stage_name == "gate":
                    status = "suspended"
                stages.append({"name": stage_name, "status": status})
                current_found = True
            elif current_found:
                stages.append({"name": stage_name, "status": "pending"})
            else:
                stages.append({"name": stage_name, "status": "completed"})

    return stages
