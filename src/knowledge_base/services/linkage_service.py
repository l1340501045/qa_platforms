"""落库自动关联服务 — 用例落库时自动建立关联、文档入库时按规则关联"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.models.knowledge import Document, DocumentAssociation
from src.platform_api.models.enums import DocType, DocRelationType
from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.repositories.association_repo import AssociationRepository
from src.knowledge_base.schemas.common import AssociationDTO

logger = logging.getLogger(__name__)


# 文档入库时的自动关联规则：source_type → [(target_type, relation_type)]
_AUTO_LINK_RULES: dict[DocType, list[tuple[DocType, DocRelationType]]] = {
    DocType.PRD: [
        (DocType.TECH_DOC, DocRelationType.REQ_TO_TECH),
        (DocType.TEST_RULE, DocRelationType.GENERAL),
    ],
    DocType.TECH_DOC: [
        (DocType.PRD, DocRelationType.REQ_TO_TECH),  # 反向关联
    ],
    DocType.TEST_RULE: [
        (DocType.PRD, DocRelationType.GENERAL),
    ],
    DocType.BUG_RECORD: [
        (DocType.PRD, DocRelationType.REQ_TO_BUG),
        (DocType.TEST_CASE, DocRelationType.CASE_TO_BUG),
    ],
    DocType.TEST_CASE: [
        (DocType.PRD, DocRelationType.REQ_TO_CASE),
    ],
}


class LinkageService:
    """落库自动关联服务

    两个职责：
    1. auto_link_on_create: 文档入库后按 doc_type 规则自动建立关联
    2. link_testcase_to_requirement: 用例落库时建立 用例文档→需求文档 关联（供 TC T042 调用）
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.assoc_repo = AssociationRepository(session)

    async def auto_link_on_create(self, document_id: UUID) -> list[AssociationDTO]:
        """文档入库后按类型规则自动关联同系统文档"""
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None:
            return []

        rules = _AUTO_LINK_RULES.get(DocType(doc.doc_type), [])
        if not rules:
            return []

        created_links: list[AssociationDTO] = []

        for target_type, relation_type in rules:
            targets = await self._find_same_system_by_type(doc, target_type)
            for target in targets:
                link = await self._ensure_association(
                    source_doc_id=doc.id,
                    target_doc_id=target.id,
                    relation_type=relation_type.value,
                    created_by="system:auto_linkage",
                )
                if link:
                    created_links.append(link)

        if created_links:
            await self.session.flush()
            logger.info(
                "Auto-linked document %s (%s): created %d associations",
                document_id,
                doc.doc_type,
                len(created_links),
            )

        return created_links

    async def link_testcase_to_requirement(
        self,
        requirement_doc_id: UUID,
        test_case_doc_id: UUID,
    ) -> AssociationDTO | None:
        """用例落库时建立 需求→用例 关联（供 testcase-generator T042 调用）

        注意：这里关联的是 knowledge.documents 中的两个文档记录。
        testcase schema 中的 test_cases 通过 batch.document_id FK 隐式关联需求，
        但如果用例同时作为"知识"沉淀到 knowledge.documents 中（doc_type=test_case），
        则通过本方法建立显式关联以供后续检索。
        """
        link = await self._ensure_association(
            source_doc_id=requirement_doc_id,
            target_doc_id=test_case_doc_id,
            relation_type=DocRelationType.REQ_TO_CASE.value,
            created_by="system:settlement",
        )
        if link:
            logger.info(
                "Linked requirement %s → test_case %s",
                requirement_doc_id,
                test_case_doc_id,
            )
        return link

    async def _find_same_system_by_type(self, doc: Document, target_type: DocType) -> list[Document]:
        """查找同系统内指定类型的活跃文档"""
        stmt = (
            select(Document)
            .where(
                Document.system_id == doc.system_id,
                Document.doc_type == target_type.value,
                Document.id != doc.id,
                Document.deleted_at.is_(None),
            )
            .limit(20)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _ensure_association(
        self,
        source_doc_id: UUID,
        target_doc_id: UUID,
        relation_type: str,
        created_by: str,
    ) -> AssociationDTO | None:
        """幂等创建关联（已存在则跳过）"""
        existing = await self.assoc_repo.find_active(source_doc_id, target_doc_id, relation_type)
        if existing:
            return None

        assoc = await self.assoc_repo.create(
            source_doc_id=source_doc_id,
            target_doc_id=target_doc_id,
            relation_type=relation_type,
            created_by=created_by,
        )
        return AssociationDTO.model_validate(assoc)
