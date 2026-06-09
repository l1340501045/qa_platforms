"""T018: 进程内调用 knowledge-base RetrievalService"""

from uuid import UUID

from src.knowledge_base.db import async_session_factory
from src.knowledge_base.schemas.common import RetrievalContext
from src.knowledge_base.services.retrieval_service import RetrievalService


async def retrieve_knowledge_context(
    document_id: UUID,
    system_id: UUID,
    max_depth: int = 3,
    query: str = "",
    top_k: int = 10,
) -> RetrievalContext:
    """进程内直接 import 调用 KB 检索（非 HTTP）

    Args:
        document_id: 种子文档 ID
        system_id: 系统 ID
        max_depth: 图遍历最大深度
        query: 可选语义查询；为空则不触发向量召回（只走关联图）
        top_k: 向量召回时返回的最大条数

    Returns:
        RetrievalContext 包含 graph_results / vector_results / merged_results
    """
    async with async_session_factory() as session:
        service = RetrievalService(session)
        return await service.retrieve_context(
            document_id=document_id,
            system_id=system_id,
            max_depth=max_depth,
            top_k=top_k,
            query=query,
        )
