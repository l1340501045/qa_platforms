"""系统管理 API — 系统 CRUD + 关联 CRUD + 批次列表 + 用例树 + 选项"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.response import PaginationParams, paginated_response, success
from src.platform_api.schemas.system import (
    CreateSystemAssociationRequest,
    CreateSystemRequest,
    UpdateSystemRequest,
)
from src.platform_api.services.system_service import SystemService
from src.platform_api.services.batch_list_service import BatchListService
from src.platform_api.services.case_tree_service import CaseTreeService

router = APIRouter(prefix="/systems", tags=["系统管理"])


def _get_service(session: AsyncSession = Depends(get_session)) -> SystemService:
    return SystemService(session)


def _get_batch_list_service(session: AsyncSession = Depends(get_session)) -> BatchListService:
    return BatchListService(session)


def _get_case_tree_service(session: AsyncSession = Depends(get_session)) -> CaseTreeService:
    return CaseTreeService(session)


# ─── 系统 CRUD ───


@router.post("", status_code=201)
async def create_system(
    data: CreateSystemRequest,
    service: SystemService = Depends(_get_service),
):
    """创建系统"""
    system = await service.create_system(data)
    return success(system)


@router.get("")
async def list_systems(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: SystemService = Depends(_get_service),
):
    """分页获取系统列表"""
    params = PaginationParams(page=page, per_page=per_page)
    items, total = await service.list_systems(offset=params.offset, limit=params.limit)
    return success(paginated_response(items, total, params))


@router.get("/options")
async def list_system_options(
    service: BatchListService = Depends(_get_batch_list_service),
):
    """获取系统选项列表（前端下拉选择器）"""
    options = await service.list_system_options()
    return success(options)


@router.get("/{system_id}")
async def get_system(
    system_id: UUID,
    service: SystemService = Depends(_get_service),
):
    """获取系统详情"""
    system = await service.get_system(system_id)
    return success(system)


@router.put("/{system_id}")
async def update_system(
    system_id: UUID,
    data: UpdateSystemRequest,
    service: SystemService = Depends(_get_service),
):
    """更新系统"""
    system = await service.update_system(system_id, data)
    return success(system)


@router.delete("/{system_id}", status_code=204)
async def delete_system(
    system_id: UUID,
    service: SystemService = Depends(_get_service),
):
    """删除系统"""
    await service.delete_system(system_id)


# ─── 系统关联 CRUD ───


@router.post("/{system_id}/associations", status_code=201)
async def create_system_association(
    system_id: UUID,
    data: CreateSystemAssociationRequest,
    service: SystemService = Depends(_get_service),
):
    """创建系统间关联"""
    assoc = await service.create_association(data)
    return success(assoc)


@router.get("/{system_id}/associations")
async def list_system_associations(
    system_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: SystemService = Depends(_get_service),
):
    """获取系统关联列表"""
    params = PaginationParams(page=page, per_page=per_page)
    items, total = await service.list_associations(system_id, offset=params.offset, limit=params.limit)
    return success(paginated_response(items, total, params))


@router.delete("/{system_id}/associations/{association_id}", status_code=204)
async def delete_system_association(
    system_id: UUID,
    association_id: UUID,
    service: SystemService = Depends(_get_service),
):
    """删除系统关联"""
    await service.delete_association(association_id)


# ─── 批次列表 ───


@router.get("/{system_id}/batches")
async def list_system_batches(
    system_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="状态筛选"),
    service: BatchListService = Depends(_get_batch_list_service),
):
    """获取系统下的批次列表"""
    items, total = await service.list_by_system(system_id, status=status, page=page, per_page=per_page)
    params = PaginationParams(page=page, per_page=per_page)
    return success(paginated_response(items, total, params))


# ─── 用例树 ───


@router.get("/{system_id}/case-tree")
async def get_case_tree(
    system_id: UUID,
    batch_id: UUID | None = Query(None, description="指定批次 ID"),
    priority: str | None = Query(None, description="优先级筛选"),
    review_status: str | None = Query(None, description="review 状态筛选"),
    service: CaseTreeService = Depends(_get_case_tree_service),
):
    """获取系统级用例树形聚合数据"""
    tree = await service.get_case_tree(
        system_id=system_id,
        batch_id=batch_id,
        priority=priority,
        review_status=review_status,
    )
    return success({"tree": tree})
