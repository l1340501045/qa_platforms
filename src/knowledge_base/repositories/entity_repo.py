"""实体图谱 Repository — entities + entity_relations CRUD"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from uuid import UUID

from sqlalchemy import delete, select
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
