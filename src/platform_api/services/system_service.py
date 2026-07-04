"""系统管理 Service 层 — CRUD + 关联管理 + 名称唯一约束校验"""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.knowledge import Document
from src.platform_api.models.public import System, SystemAssociation
from src.platform_api.models.testcase import TestBatch
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.system import (
    SYSTEM_RELATION_TYPES,
    CreateSystemAssociationRequest,
    CreateSystemRequest,
    SystemSummaryResponse,
    UpdateSystemRequest,
)


class SystemService:
    """系统管理业务逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, System)
        self.assoc_repo = BaseRepository(session, SystemAssociation)

    # ─── 系统 CRUD ───

    async def create_system(self, data: CreateSystemRequest) -> System:
        """创建系统，名称唯一校验"""
        await self._check_name_unique(data.name)
        return await self.repo.create(name=data.name, description=data.description)

    async def get_system(self, system_id: UUID) -> System:
        """获取单个系统"""
        system = await self.repo.get_by_id(system_id)
        if system is None:
            raise ApiError("E4041", "系统不存在")
        return system

    async def list_systems(self, offset: int = 0, limit: int = 50) -> tuple[list[SystemSummaryResponse], int]:
        """分页列表 + 文档/批次聚合统计。"""
        doc_counts = (
            select(Document.system_id, func.count(Document.id).label("document_count"))
            .where(Document.deleted_at.is_(None))
            .group_by(Document.system_id)
            .subquery()
        )
        batch_counts = (
            select(TestBatch.system_id, func.count(TestBatch.id).label("batch_count"))
            .group_by(TestBatch.system_id)
            .subquery()
        )
        stmt = (
            select(
                System.id,
                System.name,
                System.description,
                System.created_at,
                System.updated_at,
                func.coalesce(doc_counts.c.document_count, 0).label("document_count"),
                func.coalesce(batch_counts.c.batch_count, 0).label("batch_count"),
            )
            .outerjoin(doc_counts, doc_counts.c.system_id == System.id)
            .outerjoin(batch_counts, batch_counts.c.system_id == System.id)
            .order_by(System.created_at.desc(), System.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = [SystemSummaryResponse(**row._mapping) for row in result.all()]

        count_stmt = select(func.count()).select_from(System)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    async def update_system(self, system_id: UUID, data: UpdateSystemRequest) -> System:
        """更新系统信息"""
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            raise ApiError("E4001", "未提供任何更新字段")
        if "name" in update_data:
            await self._check_name_unique(update_data["name"], exclude_id=system_id)
        system = await self.repo.update(system_id, **update_data)
        if system is None:
            raise ApiError("E4041", "系统不存在")
        return system

    async def delete_system(self, system_id: UUID) -> None:
        """删除系统（存在有效文档/批次时拒绝；仅软删除文档不阻塞）"""
        instance = await self.repo.get_by_id(system_id)
        if instance is None:
            raise ApiError("E4041", "系统不存在")
        blockers = await self._get_delete_blockers(system_id)
        if blockers:
            raise ApiError("E4091", f"该系统下仍有{'或'.join(blockers)}，无法删除。请先删除关联数据")
        try:
            await self._delete_document_tombstones(system_id)
            await self.session.delete(instance)
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            raise ApiError("E4091", "该系统下仍有关联数据，无法删除。请先删除关联数据")

    # ─── 系统关联 CRUD ───

    async def create_association(self, data: CreateSystemAssociationRequest) -> SystemAssociation:
        """创建系统间关联"""
        # 校验关联类型
        if data.relation_type not in SYSTEM_RELATION_TYPES:
            raise ApiError("E4001", f"无效的关联类型，允许值：{SYSTEM_RELATION_TYPES}")
        # 校验源和目标系统存在
        await self.get_system(data.source_system_id)
        await self.get_system(data.target_system_id)
        # 校验不能自关联
        if data.source_system_id == data.target_system_id:
            raise ApiError("E4001", "不能创建自关联")
        return await self.assoc_repo.create(
            source_system_id=data.source_system_id,
            target_system_id=data.target_system_id,
            relation_type=data.relation_type,
            description=data.description,
        )

    async def list_associations(
        self, system_id: UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[SystemAssociation], int]:
        """查询某系统的所有关联（作为 source 或 target）"""
        stmt = (
            select(SystemAssociation)
            .where(
                (SystemAssociation.source_system_id == system_id) | (SystemAssociation.target_system_id == system_id)
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = (
            select(func.count())
            .select_from(SystemAssociation)
            .where(
                (SystemAssociation.source_system_id == system_id) | (SystemAssociation.target_system_id == system_id)
            )
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    async def delete_association(self, association_id: UUID) -> None:
        """删除系统关联"""
        deleted = await self.assoc_repo.delete(association_id)
        if not deleted:
            raise ApiError("E4041", "系统关联不存在")

    # ─── 私有方法 ───

    async def _check_name_unique(self, name: str, exclude_id: UUID | None = None) -> None:
        """校验系统名称唯一"""
        stmt = select(System).where(System.name == name)
        if exclude_id:
            stmt = stmt.where(System.id != exclude_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise ApiError("E4091", f"系统名称 '{name}' 已存在")

    async def _get_delete_blockers(self, system_id: UUID) -> list[str]:
        """返回仍应阻止系统删除的有效业务资产。"""
        active_doc_count = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.system_id == system_id, Document.deleted_at.is_(None))
        )
        batch_count = await self.session.scalar(
            select(func.count()).select_from(TestBatch).where(TestBatch.system_id == system_id)
        )

        blockers: list[str] = []
        if active_doc_count:
            blockers.append("文档")
        if batch_count:
            blockers.append("批次")
        return blockers

    async def _delete_document_tombstones(self, system_id: UUID) -> None:
        """物理清理软删除文档，避免 tombstone 外键阻止空系统删除。"""
        await self.session.execute(
            delete(Document).where(Document.system_id == system_id, Document.deleted_at.is_not(None))
        )
