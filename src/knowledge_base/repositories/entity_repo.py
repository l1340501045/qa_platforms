"""实体图谱 Repository — entities + entity_relations CRUD + BFS 遍历"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.schemas.entity import EntityGraph
from src.platform_api.models.knowledge import Entity, EntityRelation

logger = logging.getLogger(__name__)


class EntityRepository:
    """实体/关系落库 + 查询"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_graph(
        self, document_id: UUID, system_id: UUID, graph: EntityGraph
    ) -> None:
        """保存实体图谱（幂等：先删该 document 旧数据再写新）。"""
        # 1. 先删旧关系（外键依赖 entities）再删旧实体
        await self.session.execute(
            delete(EntityRelation).where(EntityRelation.document_id == document_id)
        )
        await self.session.execute(
            delete(Entity).where(Entity.document_id == document_id)
        )
        await self.session.flush()

        if not graph.entities:
            return

        # 2. 写入实体，收集 canonical_key → entity_id 映射
        key_to_id: dict[str, UUID] = {}
        for item in graph.entities:
            entity_id = uuid_mod.uuid4()
            entity = Entity(
                id=entity_id,
                document_id=document_id,
                system_id=system_id,
                entity_type=item.entity_type,
                name=item.name,
                canonical_key=item.canonical_key,
                section_ref=item.section_ref,
                description=item.description,
                source_quote=item.source_quote,
                attributes=item.attributes,
            )
            self.session.add(entity)
            key_to_id[item.canonical_key] = entity_id

        await self.session.flush()

        # 3. 写入关系（解析 source/target name → entity_id）
        for rel in graph.relations:
            source_id = key_to_id.get(rel.source_name)
            target_id = key_to_id.get(rel.target_name)
            if not source_id or not target_id:
                logger.warning(
                    "关系引用的实体不存在，跳过: %s -> %s", rel.source_name, rel.target_name
                )
                continue
            if source_id == target_id:
                continue

            relation = EntityRelation(
                id=uuid_mod.uuid4(),
                document_id=document_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type=rel.relation_type,
                note=rel.note,
                source_quote=rel.source_quote,
            )
            self.session.add(relation)

    async def traverse_entities(
        self, seed_entity_id: UUID, max_depth: int = 2
    ) -> list[tuple[UUID, int, str, str]]:
        """WITH RECURSIVE BFS 遍历实体图（有向边，保留关系语义方向）。

        返回 [(entity_id, depth, relation_type, direction)]，direction∈{outgoing,incoming}。
        DISTINCT ON entity_id 取最浅深度。
        """
        raw_sql = text("""
            WITH RECURSIVE graph AS (
                -- 锚点：种子实体的直接关系（出边）
                SELECT
                    er.target_entity_id AS entity_id,
                    1 AS depth,
                    er.relation_type,
                    'outgoing' AS direction
                FROM knowledge.entity_relations er
                WHERE er.source_entity_id = :seed_id

                UNION

                -- 锚点：种子实体的直接关系（入边）
                SELECT
                    er.source_entity_id AS entity_id,
                    1 AS depth,
                    er.relation_type,
                    'incoming' AS direction
                FROM knowledge.entity_relations er
                WHERE er.target_entity_id = :seed_id

                UNION

                -- 递归：沿关系展开（出边）
                SELECT
                    er.target_entity_id AS entity_id,
                    g.depth + 1 AS depth,
                    er.relation_type,
                    'outgoing' AS direction
                FROM knowledge.entity_relations er
                JOIN graph g ON er.source_entity_id = g.entity_id
                WHERE g.depth < :max_depth
                  AND er.target_entity_id != :seed_id

                UNION

                -- 递归：沿关系展开（入边）
                SELECT
                    er.source_entity_id AS entity_id,
                    g.depth + 1 AS depth,
                    er.relation_type,
                    'incoming' AS direction
                FROM knowledge.entity_relations er
                JOIN graph g ON er.target_entity_id = g.entity_id
                WHERE g.depth < :max_depth
                  AND er.source_entity_id != :seed_id
            )
            SELECT DISTINCT ON (entity_id) entity_id, depth, relation_type, direction
            FROM graph
            ORDER BY entity_id, depth ASC
        """)

        result = await self.session.execute(raw_sql, {"seed_id": str(seed_entity_id), "max_depth": max_depth})
        return [
            (row.entity_id, row.depth, row.relation_type, row.direction)
            for row in result.fetchall()
        ]

    async def find_entity_by_name(self, name: str, system_id: UUID) -> Entity | None:
        """按名称/canonical_key 模糊匹配定位实体"""
        # 先精确匹配 canonical_key
        result = await self.session.execute(
            select(Entity).where(Entity.system_id == system_id, Entity.canonical_key == name)
        )
        entity = result.scalars().first()
        if entity:
            return entity

        # 再模糊匹配 name (ILIKE)
        result = await self.session.execute(
            select(Entity).where(Entity.system_id == system_id, Entity.name.ilike(f"%{name}%"))
        )
        return result.scalars().first()

    async def get_entities_by_ids(self, entity_ids: list[UUID]) -> list[Entity]:
        """批量获取实体"""
        if not entity_ids:
            return []
        result = await self.session.execute(
            select(Entity).where(Entity.id.in_(entity_ids))
        )
        return list(result.scalars().all())

    async def get_entities_by_document(self, document_id: UUID) -> list[Entity]:
        """获取文档的所有实体"""
        result = await self.session.execute(
            select(Entity).where(Entity.document_id == document_id)
        )
        return list(result.scalars().all())

    async def get_relations_by_document(self, document_id: UUID) -> list[EntityRelation]:
        """获取文档的所有关系"""
        result = await self.session.execute(
            select(EntityRelation).where(EntityRelation.document_id == document_id)
        )
        return list(result.scalars().all())
