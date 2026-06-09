"""文档仓库 — CRUD + 软删除 + content_hash 去重"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document
from src.platform_api.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    """Document 专用仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Document)

    async def get_by_id(self, id: UUID) -> Document | None:
        """查询未软删除的文档"""
        stmt = select(self.model).where(
            self.model.id == id,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_content_hash(self, content_hash: str) -> Document | None:
        """通过 content_hash 查找已有文档（去重用）"""
        stmt = select(self.model).where(
            self.model.content_hash == content_hash,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, id: UUID) -> bool:
        """软删除文档"""
        stmt = (
            update(self.model)
            .where(self.model.id == id, self.model.deleted_at.is_(None))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def list_by_system(self, system_id: UUID, offset: int = 0, limit: int = 50) -> list[Document]:
        """按系统 ID 列出文档"""
        stmt = (
            select(self.model)
            .where(self.model.system_id == system_id, self.model.deleted_at.is_(None))
            .order_by(self.model.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_embedding(self, limit: int = 100) -> list[Document]:
        """列出待向量化的文档"""
        stmt = (
            select(self.model)
            .where(
                self.model.embedding_status == "pending",
                self.model.deleted_at.is_(None),
            )
            .order_by(self.model.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_embedding_status(self, id: UUID, status: str) -> None:
        """更新文档的向量化状态"""
        stmt = update(self.model).where(self.model.id == id).values(embedding_status=status)
        await self.session.execute(stmt)
        await self.session.flush()
