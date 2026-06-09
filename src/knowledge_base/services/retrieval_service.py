"""统一检索入口 — 供进程内调用"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.services.search.graph_search import GraphSearchService
from src.knowledge_base.services.search.vector_search import VectorSearchService
from src.knowledge_base.services.search.hybrid_search import HybridSearchService
from src.knowledge_base.services.search.external_adapter import ExternalSearchAdapter, NoopExternalAdapter
from src.knowledge_base.schemas.common import SearchRequest, SearchResult, RetrievalContext

logger = logging.getLogger(__name__)


class RetrievalService:
    """统一检索服务 — 组合图遍历、向量召回、跨系统检索"""

    def __init__(
        self,
        session: AsyncSession,
        external_adapter: ExternalSearchAdapter | None = None,
    ):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.graph_search = GraphSearchService(session)
        self.vector_search = VectorSearchService(session)
        self.hybrid_search = HybridSearchService(session)
        self.external_adapter = external_adapter or NoopExternalAdapter()

    async def retrieve_context(
        self,
        document_id: UUID,
        system_id: UUID,
        max_depth: int = 3,
        top_k: int = 10,
        query: str = "",
    ) -> RetrievalContext:
        """完整检索上下文组装"""
        context = RetrievalContext(
            seed_document_id=document_id,
            system_id=system_id,
        )

        # 0. 种子文档自身必须作为首要信源（否则无关联/无向量的文档会得到空上下文，
        #    导致 parse→comprehend 覆盖度为 0、Gate 直接 NO_GO，生成永远产不出用例）
        seed_results: list[SearchResult] = []
        seed_doc = await self.doc_repo.get_by_id(document_id)
        if seed_doc is not None and seed_doc.content:
            seed_results.append(
                SearchResult(
                    document_id=seed_doc.id,
                    title=seed_doc.title,
                    content_snippet=seed_doc.content,
                    score=1.0,
                    source="seed",
                    depth=0,
                )
            )

        # 1. 关联图遍历获取直接关联
        graph_results = await self.graph_search.traverse_graph(
            seed_doc_id=document_id,
            max_depth=max_depth,
        )
        context.graph_results = graph_results

        # 2. 可选：向量召回补充
        vector_results: list[SearchResult] = []
        if query:
            vector_results = await self.vector_search.search(
                query=query,
                top_k=top_k,
                system_id=system_id,
            )
            context.vector_results = vector_results

        # 3. 跨系统关联（如有）
        external_results: list[SearchResult] = []
        if await self.external_adapter.health_check():
            doc = await self.doc_repo.get_by_id(document_id)
            if doc:
                external_results = await self.external_adapter.search(
                    query=doc.title,
                    system_id=system_id,
                    top_k=5,
                )

        # 4. 融合排序（种子文档置于图结果之前，确保最高优先级且不被去重丢弃）
        merged = self._merge_all(seed_results + graph_results, vector_results, external_results, top_k)
        context.merged_results = merged
        context.total_count = len(merged)

        logger.info(
            "Retrieval context for doc=%s: seed=%d, graph=%d, vector=%d, external=%d, merged=%d",
            document_id,
            len(seed_results),
            len(graph_results),
            len(vector_results),
            len(external_results),
            len(merged),
        )
        return context

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """通用检索接口"""
        return await self.hybrid_search.search(request)

    def _merge_all(
        self,
        graph_results: list[SearchResult],
        vector_results: list[SearchResult],
        external_results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """三路融合去重排序"""
        seen: set[UUID] = set()
        merged: list[SearchResult] = []

        # 图结果最高优先
        for r in graph_results:
            if r.document_id not in seen:
                seen.add(r.document_id)
                merged.append(r)

        # 向量结果次之
        for r in vector_results:
            if r.document_id not in seen:
                seen.add(r.document_id)
                merged.append(
                    SearchResult(
                        document_id=r.document_id,
                        title=r.title,
                        content_snippet=r.content_snippet,
                        score=r.score * 0.8,
                        source="vector",
                    )
                )

        # 外部结果补充
        for r in external_results:
            if r.document_id not in seen:
                seen.add(r.document_id)
                merged.append(
                    SearchResult(
                        document_id=r.document_id,
                        title=r.title,
                        content_snippet=r.content_snippet,
                        score=r.score * 0.6,
                        source="external",
                    )
                )

        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:top_k]
