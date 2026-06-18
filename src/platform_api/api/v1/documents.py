"""文档管理 API — 批量上传、列表、详情、删除、关联 CRUD

路由对齐契约：
- 文档列表/上传挂在 systems 路由下（由 __init__.py 包含时路径前缀处理）
- 文档关联用嵌套路径 /documents/:id/associations
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.schemas.document import CreateDocumentAssociationRequest
from src.platform_api.services.document_service import DocumentService
from src.platform_api.services.batch_list_service import BatchListService

router = APIRouter(prefix="/documents", tags=["文档管理"])

# 挂在 /systems 下的子路由（文档列表 + 上传）
systems_doc_router = APIRouter(prefix="/systems", tags=["文档管理"])


def _get_service(session: AsyncSession = Depends(get_session)) -> DocumentService:
    return DocumentService(session)


def _get_batch_list_service(session: AsyncSession = Depends(get_session)) -> BatchListService:
    return BatchListService(session)


# ─── 文档列表（契约: GET /systems/:id/documents） ───


@systems_doc_router.get("/{system_id}/documents")
async def list_documents(
    system_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: DocumentService = Depends(_get_service),
):
    """获取系统下文档列表"""
    params = PaginationParams(page=page, per_page=per_page)
    items, total = await service.list_documents(system_id=system_id, offset=params.offset, limit=params.limit)
    return success(paginated_response(items, total, params))


# ─── 批量上传（契约: POST /systems/:id/documents/batch） ───


@systems_doc_router.post("/{system_id}/documents/batch", status_code=201)
async def batch_upload_documents(
    system_id: UUID,
    files: list[UploadFile] = File(..., description="zip / .md / 文件夹内文件（可多个）"),
    doc_type: str = Query("other", description="文档类型"),
    service: DocumentService = Depends(_get_service),
):
    """批量上传文档：支持 zip 压缩包、单个 .md、文件夹（含图片，相对路径可解析）"""
    result = await service.batch_upload(system_id=system_id, files=files, doc_type=doc_type)
    return success(result)


# ─── 文档详情 ───


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    service: DocumentService = Depends(_get_service),
):
    """获取文档详情"""
    doc = await service.get_document(document_id)
    return success(doc)


# ─── 文档删除 ───


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    service: DocumentService = Depends(_get_service),
):
    """删除文档（软删除）"""
    await service.delete_document(document_id)


# ─── 文档关联 CRUD（契约: POST/GET /documents/:id/associations） ───


@router.post("/{document_id}/associations", status_code=201)
async def create_document_association(
    document_id: UUID,
    data: CreateDocumentAssociationRequest,
    service: DocumentService = Depends(_get_service),
):
    """创建文档间关联"""
    assoc = await service.create_association(data)
    return success(assoc)


@router.get("/{document_id}/associations")
async def list_document_associations(
    document_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: DocumentService = Depends(_get_service),
):
    """获取文档关联列表"""
    params = PaginationParams(page=page, per_page=per_page)
    items, total = await service.list_associations(document_id, offset=params.offset, limit=params.limit)
    return success(paginated_response(items, total, params))


@router.delete("/{document_id}/associations/{association_id}", status_code=204)
async def delete_document_association(
    document_id: UUID,
    association_id: UUID,
    service: DocumentService = Depends(_get_service),
):
    """删除文档关联（软删除）"""
    await service.delete_association(association_id)


# ─── 文档批次列表 ───


@router.get("/{document_id}/batches")
async def list_document_batches(
    document_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="状态筛选"),
    service: BatchListService = Depends(_get_batch_list_service),
):
    """获取文档的生成批次列表"""
    items, total = await service.list_by_document(document_id, status=status, page=page, per_page=per_page)
    params = PaginationParams(page=page, per_page=per_page)
    return success(paginated_response(items, total, params))
