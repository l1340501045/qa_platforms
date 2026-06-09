"""关联服务 — 文档关联的建立与删除"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.association_repo import AssociationRepository
from src.knowledge_base.schemas.common import AssociationDTO

logger = logging.getLogger(__name__)


class AssociationManagementService:
    """管理文档关联关系"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AssociationRepository(session)

    async def create_association(
        self,
        source_doc_id: UUID,
        target_doc_id: UUID,
        relation_type: str,
        created_by: str | None = None,
    ) -> AssociationDTO:
        """建立关联（幂等）"""
        existing = await self.repo.find_active(source_doc_id, target_doc_id, relation_type)
        if existing:
            logger.debug("Association already exists: %s -> %s (%s)", source_doc_id, target_doc_id, relation_type)
            return AssociationDTO.model_validate(existing)

        assoc = await self.repo.create(
            source_doc_id=source_doc_id,
            target_doc_id=target_doc_id,
            relation_type=relation_type,
            created_by=created_by,
        )
        await self.session.flush()
        logger.info("Created association: %s -> %s (%s)", source_doc_id, target_doc_id, relation_type)
        return AssociationDTO.model_validate(assoc)

    async def remove_association(self, assoc_id: UUID) -> bool:
        """软删除关联"""
        result = await self.repo.soft_delete(assoc_id)
        if result:
            logger.info("Soft-deleted association %s", assoc_id)
        return result

    async def remove_by_documents(self, source_doc_id: UUID, target_doc_id: UUID, relation_type: str) -> bool:
        """按源目标文档和关系类型删除关联"""
        assoc = await self.repo.find_active(source_doc_id, target_doc_id, relation_type)
        if assoc is None:
            return False
        return await self.repo.soft_delete(assoc.id)

    async def batch_create(
        self,
        associations: list[dict],
        created_by: str | None = None,
    ) -> list[AssociationDTO]:
        """批量建立关联"""
        results = []
        for item in associations:
            dto = await self.create_association(
                source_doc_id=item["source_doc_id"],
                target_doc_id=item["target_doc_id"],
                relation_type=item["relation_type"],
                created_by=created_by,
            )
            results.append(dto)
        return results
