"""CTE 图遍历检索 — BFS N 跳深度"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.association_repo import AssociationRepository
from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.schemas.common import SearchResult

logger = logging.getLogger(__name__)


class GraphSearchService:
    """基于关联图的 BFS 遍历检索"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.assoc_repo = AssociationRepository(session)
        self.doc_repo = DocumentRepository(session)

    async def traverse_graph(
        self,
        seed_doc_id: UUID,
        max_depth: int = 3,
        type_filter: list[str] | None = None,
    ) -> list[SearchResult]:
        """从种子文档出发 BFS 遍历，返回关联文档列表"""
        traversal = await self.assoc_repo.traverse_bfs(
            seed_doc_id=seed_doc_id,
            max_depth=max_depth,
            type_filter=type_filter,
        )

        if not traversal:
            return []

        results: list[SearchResult] = []
        for doc_id, depth, relation_type in traversal:
            doc = await self.doc_repo.get_by_id(doc_id)
            if doc is None:
                continue
            # 分数按深度递减：depth 1 -> 1.0, depth 2 -> 0.67, depth 3 -> 0.5
            score = 1.0 / depth
            snippet = doc.content[:200] if doc.content else ""
            results.append(
                SearchResult(
                    document_id=doc_id,
                    title=doc.title,
                    content_snippet=snippet,
                    score=score,
                    source="graph",
                    depth=depth,
                    relation_type=relation_type,
                )
            )

        # 按 score 降序排列
        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("Graph search from %s: found %d results (max_depth=%d)", seed_doc_id, len(results), max_depth)
        return results
