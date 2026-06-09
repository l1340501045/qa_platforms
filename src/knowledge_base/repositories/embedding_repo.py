"""Embedding 仓库 — 批量写入 + cosine similarity 查询"""

from uuid import UUID

from sqlalchemy import select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import DocumentEmbedding
from src.platform_api.repositories.base import BaseRepository


class EmbeddingRepository(BaseRepository[DocumentEmbedding]):
    """DocumentEmbedding 专用仓库"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, DocumentEmbedding)

    async def bulk_insert(self, embeddings: list[dict]) -> int:
        """批量写入 embedding 记录，返回写入条数"""
        if not embeddings:
            return 0
        instances = [DocumentEmbedding(**e) for e in embeddings]
        self.session.add_all(instances)
        await self.session.flush()
        return len(instances)

    async def delete_by_document(self, document_id: UUID) -> int:
        """删除某文档的所有 embedding（重新向量化前清理）"""
        stmt = delete(DocumentEmbedding).where(DocumentEmbedding.document_id == document_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def cosine_search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        system_id: UUID | None = None,
    ) -> list[tuple[UUID, str, str, float]]:
        """pgvector cosine similarity top-k 查询，返回 (document_id, chunk_heading, chunk_content, score)"""
        vector_literal = f"[{','.join(str(v) for v in query_vector)}]"

        system_filter = ""
        if system_id:
            system_filter = f"AND d.system_id = '{system_id}'"

        raw_sql = text(f"""
            SELECT
                e.document_id,
                e.chunk_heading,
                e.chunk_content,
                1 - (e.embedding <=> :query_vec::vector) AS score
            FROM knowledge.document_embeddings e
            JOIN knowledge.documents d ON d.id = e.document_id
            WHERE d.deleted_at IS NULL
              {system_filter}
            ORDER BY e.embedding <=> :query_vec::vector
            LIMIT :top_k
        """)

        result = await self.session.execute(raw_sql, {"query_vec": vector_literal, "top_k": top_k})
        return [(row.document_id, row.chunk_heading or "", row.chunk_content, row.score) for row in result.fetchall()]

    async def list_by_document(self, document_id: UUID) -> list[DocumentEmbedding]:
        """列出文档的所有 embedding 分块"""
        stmt = (
            select(DocumentEmbedding)
            .where(DocumentEmbedding.document_id == document_id)
            .order_by(DocumentEmbedding.chunk_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
