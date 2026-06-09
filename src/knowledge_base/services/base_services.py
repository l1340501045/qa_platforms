"""基础 CRUD 服务 — DocumentService / AssociationService"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document, DocumentAssociation
from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.repositories.association_repo import AssociationRepository
from src.knowledge_base.schemas.common import DocumentDTO, AssociationDTO


class DocumentService:
    """文档基础 CRUD 服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)

    async def get_document(self, doc_id: UUID) -> DocumentDTO | None:
        """获取单个文档"""
        doc = await self.repo.get_by_id(doc_id)
        if doc is None:
            return None
        return DocumentDTO.model_validate(doc)

    async def create_document(self, **kwargs) -> DocumentDTO:
        """创建文档（content_hash 去重检查）"""
        content_hash = kwargs.get("content_hash", "")
        if content_hash:
            existing = await self.repo.find_by_content_hash(content_hash)
            if existing:
                return DocumentDTO.model_validate(existing)
        doc = await self.repo.create(**kwargs)
        return DocumentDTO.model_validate(doc)

    async def update_document(self, doc_id: UUID, **kwargs) -> DocumentDTO | None:
        """更新文档字段"""
        doc = await self.repo.update(doc_id, **kwargs)
        if doc is None:
            return None
        return DocumentDTO.model_validate(doc)

    async def soft_delete_document(self, doc_id: UUID) -> bool:
        """软删除文档"""
        return await self.repo.soft_delete(doc_id)

    async def list_by_system(self, system_id: UUID, offset: int = 0, limit: int = 50) -> list[DocumentDTO]:
        """按系统列出文档"""
        docs = await self.repo.list_by_system(system_id, offset, limit)
        return [DocumentDTO.model_validate(d) for d in docs]


class AssociationService:
    """文档关联基础 CRUD 服务"""

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
        """创建关联（幂等：已有则返回现有记录）"""
        existing = await self.repo.find_active(source_doc_id, target_doc_id, relation_type)
        if existing:
            return AssociationDTO.model_validate(existing)
        assoc = await self.repo.create(
            source_doc_id=source_doc_id,
            target_doc_id=target_doc_id,
            relation_type=relation_type,
            created_by=created_by,
        )
        return AssociationDTO.model_validate(assoc)

    async def remove_association(self, assoc_id: UUID) -> bool:
        """软删除关联"""
        return await self.repo.soft_delete(assoc_id)

    async def list_associations(self, doc_id: UUID, direction: str = "both") -> list[AssociationDTO]:
        """列出某文档的关联"""
        assocs = await self.repo.list_by_document(doc_id, direction)
        return [AssociationDTO.model_validate(a) for a in assocs]
