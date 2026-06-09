"""系统管理 API — 系统 CRUD + 关联 CRUD（7 个端点）"""

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

router = APIRouter(prefix="/systems", tags=["系统管理"])


def _get_service(session: AsyncSession = Depends(get_session)) -> SystemService:
    return SystemService(session)


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
