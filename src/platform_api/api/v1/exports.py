"""导出 API — 创建导出任务、查询状态、列表、下载文件"""

import logging
from collections.abc import Iterator
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from minio.error import S3Error
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.minio_client import minio_client
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.core.settings import settings
from src.platform_api.models.testcase import ExportTask
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.export import ExportRequest

router = APIRouter(prefix="/exports", tags=["导出管理"])
logger = logging.getLogger(__name__)

EXPORT_CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
EXPORT_EXTENSIONS = {
    "markdown": "md",
    "excel": "xlsx",
}


def _export_object_name(file_url: str) -> str | None:
    """从历史 file_url 中解析 MinIO object_name。"""
    path = file_url.split("?", 1)[0].lstrip("/")
    bucket_prefix = f"{settings.minio_bucket}/"
    if path.startswith(bucket_prefix):
        path = path[len(bucket_prefix) :]
    if not path.startswith("exports/"):
        return None
    return path


def _export_filename(export_task: ExportTask) -> str:
    ext = EXPORT_EXTENSIONS.get(getattr(export_task, "format", ""), "bin")
    return f"qa-export-{str(export_task.id)[:8]}.{ext}"


def _export_download_url(export_task: ExportTask) -> str | None:
    if export_task.status == "completed" and export_task.file_url:
        return f"/api/v1/exports/{export_task.id}/download"
    return export_task.file_url


def _iter_minio_object(response) -> Iterator[bytes]:
    try:
        yield from response.stream(32 * 1024)
    finally:
        response.close()
        response.release_conn()


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
            "file_url": _export_download_url(export_task),
            "total_cases": getattr(export_task, "total_cases", None),
            "created_at": export_task.created_at.isoformat() if export_task.created_at else None,
            "completed_at": export_task.completed_at.isoformat()
            if getattr(export_task, "completed_at", None)
            else None,
        }
    )


@router.get("/{export_id}/download")
async def download_export(
    export_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """下载已完成导出文件。"""
    repo = BaseRepository(session, ExportTask)
    export_task = await repo.get_by_id(export_id)
    if export_task is None:
        raise ApiError("E4041", "导出任务不存在")
    if export_task.status != "completed" or not export_task.file_url:
        raise ApiError("E4092", "导出文件尚未生成，请稍后再试")

    object_name = _export_object_name(export_task.file_url)
    if object_name is None:
        raise ApiError("E4041", "导出文件地址无效")

    try:
        storage_response = minio_client.get_object(settings.minio_bucket, object_name)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
            raise ApiError("E4041", "导出文件不存在或已被清理") from exc
        logger.exception("Failed to download export object %s", object_name)
        raise ApiError("E5031", "导出文件暂时无法下载，请稍后重试") from exc
    except Exception as exc:
        logger.exception("Failed to connect export storage for %s", object_name)
        raise ApiError("E5031", "导出文件暂时无法下载，请稍后重试") from exc

    filename = _export_filename(export_task)
    content_disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        _iter_minio_object(storage_response),
        media_type=EXPORT_CONTENT_TYPES.get(export_task.format, "application/octet-stream"),
        headers={"Content-Disposition": content_disposition},
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
            "file_url": _export_download_url(item),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]

    return success(paginated_response(export_items, total, params))
