"""T018: 进程内调用 knowledge-base RetrievalService"""

import logging
from uuid import UUID

from src.knowledge_base.db import async_session_factory
from src.knowledge_base.schemas.common import RetrievalContext
from src.knowledge_base.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

_HIGH_VALUE_RELATION_TYPES = frozenset({
    "section_priority",
    "mutually_exclusive",
    "unreachable",
})


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


async def retrieve_entity_graph_hints(
    document_id: UUID,
    system_id: UUID,
) -> list[dict]:
    """查询文档的实体图谱，返回高价值关系摘要（section_priority/mutually_exclusive/unreachable）。

    只取一跳直接关系（get_relations_by_document），不做多跳 traverse——
    避免 depth=2 间接关系被错误归因到 seed 实体（A→B→C 不应产出「A 与 C」）。
    供 parse_node 填充 ParsedContext.entity_graph_hints。
    """
    from src.knowledge_base.repositories.entity_repo import EntityRepository

    async with async_session_factory() as session:
        repo = EntityRepository(session)
        entities = await repo.get_entities_by_document(document_id)

        if not entities:
            return []

        relations = await repo.get_relations_by_document(document_id)
        emap = {e.id: e for e in entities}

        hints: list[dict] = []
        for r in relations:
            if r.relation_type not in _HIGH_VALUE_RELATION_TYPES:
                continue
            s, t = emap.get(r.source_entity_id), emap.get(r.target_entity_id)
            if not s or not t:
                continue
            hints.append({
                "relation_type": r.relation_type,
                "source_entity": s.canonical_key,
                "target_entity": t.canonical_key,
                "source_name": s.name,
                "target_name": t.name,
                "note": r.note or f"{s.name} → {t.name}",
            })

        logger.info(
            "entity_graph_hints: doc=%s entities=%d relations=%d hints=%d",
            document_id, len(entities), len(relations), len(hints),
        )
        return hints
