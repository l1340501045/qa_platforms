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

    供 parse_node 填充 ParsedContext.entity_graph_hints。
    """
    from src.knowledge_base.repositories.entity_repo import EntityRepository

    async with async_session_factory() as session:
        repo = EntityRepository(session)
        entities = await repo.get_entities_by_document(document_id)

        if not entities:
            return []

        hints: list[dict] = []
        seen_pairs: set[tuple[str, str, str]] = set()

        for entity in entities:
            neighbors = await repo.traverse_entities(entity.id, max_depth=2)
            for neighbor_id, depth, relation_type, direction in neighbors:
                if relation_type not in _HIGH_VALUE_RELATION_TYPES:
                    continue

                neighbor_entities = await repo.get_entities_by_ids([neighbor_id])
                if not neighbor_entities:
                    continue
                neighbor = neighbor_entities[0]

                pair_key = (entity.canonical_key, neighbor.canonical_key, relation_type)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                hints.append({
                    "relation_type": relation_type,
                    "source_entity": entity.canonical_key,
                    "target_entity": neighbor.canonical_key,
                    "source_name": entity.name,
                    "target_name": neighbor.name,
                    "note": f"{entity.name} → {neighbor.name}",
                    "direction": direction,
                    "depth": depth,
                })

        logger.info(
            "entity_graph_hints: doc=%s entities=%d hints=%d",
            document_id, len(entities), len(hints),
        )
        return hints
