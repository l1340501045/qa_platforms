"""实体级关系查询服务 — 给定实体名，召回相关实体+关系归类应答。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from src.platform_api.core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class EntityContext:
    """关系查询结果"""

    seed_entity: object | None = None
    related: list[dict] = field(default_factory=list)


async def query_entity_context(
    name: str,
    *,
    system_id: UUID,
    repo,
) -> EntityContext:
    """查询实体的关系上下文。

    流程：名称匹配定位 seed 实体 → traverse_entities 多跳 →
    按 relation_type 归类（适用章节/优先级/互斥/约束/状态转移）。

    entity_retrieval_enabled 关时返回空。
    """
    if not settings.entity_retrieval_enabled:
        return EntityContext()

    seed = await repo.find_entity_by_name(name, system_id)
    if seed is None:
        return EntityContext()

    neighbors = await repo.traverse_entities(seed.id, max_depth=2)
    if not neighbors:
        return EntityContext(seed_entity=seed)

    entity_ids = [n[0] for n in neighbors]
    entities = await repo.get_entities_by_ids(entity_ids)
    entity_map = {e.id: e for e in entities}

    related: list[dict] = []
    for entity_id, depth, relation_type, direction in neighbors:
        entity = entity_map.get(entity_id)
        if not entity:
            continue
        related.append({
            "entity_id": entity_id,
            "name": entity.name,
            "canonical_key": entity.canonical_key,
            "entity_type": entity.entity_type,
            "description": entity.description,
            "section_ref": entity.section_ref,
            "relation_type": relation_type,
            "direction": direction,
            "depth": depth,
        })

    return EntityContext(seed_entity=seed, related=related)
