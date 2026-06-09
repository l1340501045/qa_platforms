"""混合检索编排 — 图优先 → 向量降级 → 融合排序"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.services.search.graph_search import GraphSearchService
from src.knowledge_base.services.search.vector_search import VectorSearchService
from src.knowledge_base.schemas.common import SearchRequest, SearchResult

logger = logging.getLogger(__name__)


class HybridSearchService:
    """混合检索 — 组合图检索与向量检索结果"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.graph_search = GraphSearchService(session)
        self.vector_search = VectorSearchService(session)

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """执行混合检索"""
        graph_results: list[SearchResult] = []
        vector_results: list[SearchResult] = []

        # 1. 图检索（如果有种子文档且启用）
        if request.use_graph and request.document_id:
            graph_results = await self.graph_search.traverse_graph(
                seed_doc_id=request.document_id,
                max_depth=request.max_depth,
                type_filter=request.type_filter,
            )

        # 2. 向量检索（如果有查询文本且启用）
        if request.use_vector and request.query:
            vector_results = await self.vector_search.search(
                query=request.query,
                top_k=request.top_k,
                system_id=request.system_id,
            )

        # 3. 融合排序
        merged = self._merge_results(graph_results, vector_results, request.top_k)
        logger.info(
            "Hybrid search: graph=%d, vector=%d, merged=%d",
            len(graph_results),
            len(vector_results),
            len(merged),
        )
        return merged

    def _merge_results(
        self,
        graph_results: list[SearchResult],
        vector_results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """融合排序 — 图优先，向量补充，去重"""
        seen_doc_ids: set[UUID] = set()
        merged: list[SearchResult] = []

        # 图结果优先（结构关联更可靠）
        for r in graph_results:
            if r.document_id not in seen_doc_ids:
                seen_doc_ids.add(r.document_id)
                merged.append(
                    SearchResult(
                        document_id=r.document_id,
                        title=r.title,
                        content_snippet=r.content_snippet,
                        score=r.score,
                        source="hybrid",
                        depth=r.depth,
                        relation_type=r.relation_type,
                    )
                )

        # 向量结果补充
        for r in vector_results:
            if r.document_id not in seen_doc_ids:
                seen_doc_ids.add(r.document_id)
                # 向量结果降权 0.8，保证图结果优先级
                merged.append(
                    SearchResult(
                        document_id=r.document_id,
                        title=r.title,
                        content_snippet=r.content_snippet,
                        score=r.score * 0.8,
                        source="hybrid",
                    )
                )

        # 按 score 排序取 top_k
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged[:top_k]
