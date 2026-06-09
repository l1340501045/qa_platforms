"""导出 API — 创建导出任务、查询状态、列表"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.models.testcase import ExportTask
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.export import ExportRequest

router = APIRouter(prefix="/exports", tags=["导出管理"])


@router.post("", status_code=202)
async def create_export(
    body: ExportRequest,
    session: AsyncSession = Depends(get_session),
):
    """创建导出任务"""
    # 参数校验
    if body.scope == "batch" and body.batch_id is None:
        raise ApiError("E4001", "scope=batch 时 batch_id 不能为空")
    if body.scope == "system" and body.system_id is None:
        raise ApiError("E4001", "scope=system 时 system_id 不能为空")
    if body.scope not in ("batch", "system"):
        raise ApiError("E4001", "scope 必须为 batch 或 system")
    if body.format not in ("markdown", "excel"):
        raise ApiError("E4001", "format 必须为 markdown 或 excel")

    # 创建导出任务记录
    repo = BaseRepository(session, ExportTask)
    export_task = await repo.create(
        batch_id=body.batch_id,
        system_id=body.system_id,
        export_scope=body.scope,
        format=body.format,
        status="processing",
    )

    # 发布 Celery 导出任务
    from src.platform_api.core.celery_app import celery_app

    celery_app.send_task(
        "platform_api.export",
        kwargs={
            "export_id": str(export_task.id),
            "scope": body.scope,
            "batch_id": str(body.batch_id) if body.batch_id else None,
            "system_id": str(body.system_id) if body.system_id else None,
            "format": body.format,
        },
        queue="export",
    )

    return JSONResponse(
        status_code=202,
        content=success(
            {
                "id": str(export_task.id),
                "export_scope": body.scope,
                "format": body.format,
                "status": export_task.status,
                "created_at": export_task.created_at.isoformat() if export_task.created_at else None,
            }
        ),
    )


@router.get("/{export_id}")
async def get_export(
    export_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """查询导出任务状态"""
    repo = BaseRepository(session, ExportTask)
    export_task = await repo.get_by_id(export_id)
    if export_task is None:
        raise ApiError("E4041", "导出任务不存在")
    return success(
        {
            "id": str(export_task.id),
            "export_scope": getattr(export_task, "export_scope", None),
            "format": getattr(export_task, "format", None),
            "status": export_task.status,
            "file_url": export_task.file_url,
            "total_cases": getattr(export_task, "total_cases", None),
            "created_at": export_task.created_at.isoformat() if export_task.created_at else None,
            "completed_at": export_task.completed_at.isoformat()
            if getattr(export_task, "completed_at", None)
            else None,
        }
    )


@router.get("")
async def list_exports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="状态筛选"),
    session: AsyncSession = Depends(get_session),
):
    """导出任务列表"""
    params = PaginationParams(page=page, per_page=per_page)

    filters = []
    if status:
        filters.append(ExportTask.status == status)

    stmt = (
        select(ExportTask)
        .where(*filters)
        .order_by(ExportTask.created_at.desc())
        .offset(params.offset)
        .limit(params.limit)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    count_stmt = select(func.count()).select_from(ExportTask)
    if filters:
        count_stmt = count_stmt.where(*filters)
    count_result = await session.execute(count_stmt)
    total = count_result.scalar_one()

    export_items = [
        {
            "id": str(item.id),
            "export_scope": getattr(item, "export_scope", None),
            "format": getattr(item, "format", None),
            "status": item.status,
            "file_url": item.file_url,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]

    return success(paginated_response(export_items, total, params))
