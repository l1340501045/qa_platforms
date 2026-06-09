"""pgvector cosine similarity top-k 向量检索"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.embedding_repo import EmbeddingRepository
from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient
from src.knowledge_base.schemas.common import SearchResult

logger = logging.getLogger(__name__)


class VectorSearchService:
    """基于向量相似度的检索"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.embedding_repo = EmbeddingRepository(session)
        self.embedding_client = EmbeddingClient()

    async def search(
        self,
        query: str,
        top_k: int = 10,
        system_id: UUID | None = None,
    ) -> list[SearchResult]:
        """向量检索 — 将 query embed 后做 cosine similarity top-k"""
        if not query.strip():
            return []

        # 获取 query embedding
        query_vector = await self.embedding_client.embed_single(query)
        if not query_vector:
            logger.warning("Failed to embed query, returning empty results")
            return []

        # cosine similarity 检索
        raw_results = await self.embedding_repo.cosine_search(
            query_vector=query_vector,
            top_k=top_k,
            system_id=system_id,
        )

        results: list[SearchResult] = []
        for document_id, chunk_heading, chunk_content, score in raw_results:
            results.append(
                SearchResult(
                    document_id=document_id,
                    title=chunk_heading or "",
                    content_snippet=chunk_content[:200],
                    score=score,
                    source="vector",
                )
            )

        logger.info("Vector search for query (top_k=%d): found %d results", top_k, len(results))
        return results

    async def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int = 10,
        system_id: UUID | None = None,
    ) -> list[SearchResult]:
        """直接用向量做检索（已有 embedding 时跳过二次 embed）"""
        raw_results = await self.embedding_repo.cosine_search(
            query_vector=query_vector,
            top_k=top_k,
            system_id=system_id,
        )

        return [
            SearchResult(
                document_id=document_id,
                title=chunk_heading or "",
                content_snippet=chunk_content[:200],
                score=score,
                source="vector",
            )
            for document_id, chunk_heading, chunk_content, score in raw_results
        ]
