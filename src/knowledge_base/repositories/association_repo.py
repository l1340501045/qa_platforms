"""关联仓库 — CRUD + CTE 递归查询"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update, text, literal_column, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import DocumentAssociation
from src.platform_api.repositories.base import BaseRepository


class AssociationRepository(BaseRepository[DocumentAssociation]):
    """DocumentAssociation 专用仓库，支持 CTE 递归遍历"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, DocumentAssociation)

    async def find_active(
        self, source_doc_id: UUID, target_doc_id: UUID, relation_type: str
    ) -> DocumentAssociation | None:
        """查找未删除的特定关联"""
        stmt = select(self.model).where(
            self.model.source_doc_id == source_doc_id,
            self.model.target_doc_id == target_doc_id,
            self.model.relation_type == relation_type,
            self.model.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete(self, id: UUID) -> bool:
        """软删除关联"""
        stmt = (
            update(self.model)
            .where(self.model.id == id, self.model.deleted_at.is_(None))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def list_by_document(self, doc_id: UUID, direction: str = "both") -> list[DocumentAssociation]:
        """列出指定文档的所有关联（双向或单向）"""
        conditions = [self.model.deleted_at.is_(None)]
        if direction == "outgoing":
            conditions.append(self.model.source_doc_id == doc_id)
        elif direction == "incoming":
            conditions.append(self.model.target_doc_id == doc_id)
        else:
            conditions.append((self.model.source_doc_id == doc_id) | (self.model.target_doc_id == doc_id))
        stmt = select(self.model).where(*conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def traverse_bfs(
        self,
        seed_doc_id: UUID,
        max_depth: int = 3,
        type_filter: list[str] | None = None,
    ) -> list[tuple[UUID, int, str]]:
        """WITH RECURSIVE BFS 遍历关联图，返回 (doc_id, depth, relation_type)"""
        type_clause = ""
        if type_filter:
            quoted = ", ".join(f"'{t}'" for t in type_filter)
            type_clause = f"AND da.relation_type IN ({quoted})"

        raw_sql = text(f"""
            WITH RECURSIVE graph AS (
                -- 锚点：种子文档的直接关联
                SELECT
                    CASE
                        WHEN da.source_doc_id = :seed_id THEN da.target_doc_id
                        ELSE da.source_doc_id
                    END AS doc_id,
                    1 AS depth,
                    da.relation_type
                FROM knowledge.document_associations da
                WHERE (da.source_doc_id = :seed_id OR da.target_doc_id = :seed_id)
                  AND da.deleted_at IS NULL
                  {type_clause}

                UNION

                -- 递归：沿关联展开
                SELECT
                    CASE
                        WHEN da.source_doc_id = g.doc_id THEN da.target_doc_id
                        ELSE da.source_doc_id
                    END AS doc_id,
                    g.depth + 1 AS depth,
                    da.relation_type
                FROM knowledge.document_associations da
                JOIN graph g ON (da.source_doc_id = g.doc_id OR da.target_doc_id = g.doc_id)
                WHERE da.deleted_at IS NULL
                  AND g.depth < :max_depth
                  {type_clause}
                  AND CASE
                        WHEN da.source_doc_id = g.doc_id THEN da.target_doc_id
                        ELSE da.source_doc_id
                      END != :seed_id
            )
            SELECT DISTINCT ON (doc_id) doc_id, depth, relation_type
            FROM graph
            ORDER BY doc_id, depth ASC
        """)

        result = await self.session.execute(raw_sql, {"seed_id": str(seed_doc_id), "max_depth": max_depth})
        return [(row.doc_id, row.depth, row.relation_type) for row in result.fetchall()]
