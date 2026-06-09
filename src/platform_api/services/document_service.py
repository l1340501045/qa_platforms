"""文档管理 Service 层 — 文档 CRUD + 触发 KB 解析"""

from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.exceptions import ApiError
from src.platform_api.models.knowledge import Document, DocumentAssociation
from src.platform_api.repositories.base import BaseRepository
from src.platform_api.schemas.document import (
    DOC_RELATION_TYPES,
    CreateDocumentAssociationRequest,
)
from src.platform_api.services.upload_service import UploadService


class DocumentService:
    """文档管理业务逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = BaseRepository(session, Document)
        self.assoc_repo = BaseRepository(session, DocumentAssociation)
        self.upload_service = UploadService()

    # ─── 批量上传 ───

    async def batch_upload(
        self,
        system_id: UUID,
        files: list[UploadFile],
        doc_type: str = "other",
    ) -> dict:
        """
        接收一组文件（zip / 单 .md / 文件夹）→ 解析 → 上传 MinIO → 创建 documents 行

        - .md 文件落库为 document，content 直接写入、content_hash 即时计算
        - 图片按相对路径存入 MinIO（供相对引用解析），不落库
        - 重复内容（content_hash 已存在）跳过，避免唯一约束冲突
        返回契约结构：{uploaded, skipped, failed, summary}
        """
        outcome = await self.upload_service.process_uploads(files=files, system_id=system_id)

        uploaded: list[dict] = []
        skipped: list[dict] = list(outcome.skipped)
        failed: list[dict] = list(outcome.failed)
        created: list[Document] = []
        seen_hashes: set[str] = set()

        for file_info in outcome.documents:
            content_hash = file_info["content_hash"]
            original = file_info["metadata"].get("original_filename", file_info["title"])

            # 批内 + 批间去重
            if content_hash in seen_hashes or await self._hash_exists(content_hash):
                skipped.append({"filename": original, "reason": "内容重复，已跳过"})
                continue

            try:
                doc = await self.repo.create(
                    system_id=system_id,
                    title=file_info["title"],
                    doc_type=doc_type,
                    trust_level=1,
                    content=file_info["content"],
                    storage_path=file_info["storage_path"],
                    image_refs=[],  # KB 解析回填
                    content_hash=content_hash,
                    embedding_status="pending",
                    folder_path=file_info.get("folder_path"),
                    metadata_=file_info.get("metadata"),
                )
                await self.session.flush()
            except Exception as exc:  # noqa: BLE001 — 单文档失败不中断整批
                failed.append({"filename": original, "error": str(exc)})
                continue

            seen_hashes.add(content_hash)
            created.append(doc)
            uploaded.append(
                {
                    "id": str(doc.id),
                    "title": doc.title,
                    "doc_type": doc.doc_type,
                    "folder_path": doc.folder_path,
                    "status": "uploading",
                }
            )

        # 触发 KB 解析任务（异步）
        self._trigger_kb_parsing(created)

        return {
            "uploaded": uploaded,
            "skipped": skipped,
            "failed": failed,
            "image_count": len(outcome.images),
            "summary": {
                "total_files": outcome.total_files,
                "uploaded_count": len(uploaded),
                "skipped_count": len(skipped),
                "failed_count": len(failed),
                "image_count": len(outcome.images),
            },
        }

    async def _hash_exists(self, content_hash: str) -> bool:
        """检查是否已存在相同 content_hash 的未删除文档"""
        stmt = select(func.count()).select_from(Document).where(
            Document.content_hash == content_hash,
            Document.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    # ─── 文档列表 ───

    async def list_documents(self, system_id: UUID, offset: int = 0, limit: int = 50) -> tuple[list[Document], int]:
        """分页获取系统下文档列表"""
        stmt = (
            select(Document)
            .where(Document.system_id == system_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = (
            select(func.count())
            .select_from(Document)
            .where(Document.system_id == system_id, Document.deleted_at.is_(None))
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    # ─── 文档详情 ───

    async def get_document(self, document_id: UUID) -> Document:
        """获取文档详情"""
        doc = await self.repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise ApiError("E4041", "文档不存在")
        return doc

    # ─── 文档删除（软删除） ───

    async def delete_document(self, document_id: UUID) -> None:
        """软删除文档"""
        from datetime import datetime, timezone

        doc = await self.repo.get_by_id(document_id)
        if doc is None or doc.deleted_at is not None:
            raise ApiError("E4041", "文档不存在")
        doc.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    # ─── 文档关联 ───

    async def create_association(self, data: CreateDocumentAssociationRequest) -> DocumentAssociation:
        """创建文档间关联"""
        if data.relation_type not in DOC_RELATION_TYPES:
            raise ApiError("E4001", f"无效的关联类型，允许值：{DOC_RELATION_TYPES}")
        if data.source_doc_id == data.target_doc_id:
            raise ApiError("E4001", "不能创建自关联")
        # 校验文档存在
        await self.get_document(data.source_doc_id)
        await self.get_document(data.target_doc_id)

        return await self.assoc_repo.create(
            source_doc_id=data.source_doc_id,
            target_doc_id=data.target_doc_id,
            relation_type=data.relation_type,
            created_by=data.created_by,
        )

    async def list_associations(
        self, document_id: UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[DocumentAssociation], int]:
        """查询文档的所有关联"""
        stmt = (
            select(DocumentAssociation)
            .where(
                (DocumentAssociation.source_doc_id == document_id) | (DocumentAssociation.target_doc_id == document_id),
                DocumentAssociation.deleted_at.is_(None),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        count_stmt = (
            select(func.count())
            .select_from(DocumentAssociation)
            .where(
                (DocumentAssociation.source_doc_id == document_id) | (DocumentAssociation.target_doc_id == document_id),
                DocumentAssociation.deleted_at.is_(None),
            )
        )
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total

    async def delete_association(self, association_id: UUID) -> None:
        """软删除文档关联"""
        from datetime import datetime, timezone

        assoc = await self.assoc_repo.get_by_id(association_id)
        if assoc is None or assoc.deleted_at is not None:
            raise ApiError("E4041", "文档关联不存在")
        assoc.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    # ─── 私有方法 ───

    def _trigger_kb_parsing(self, documents: list[Document]) -> None:
        """触发 Knowledge Base 解析任务（通过 Celery）"""
        from src.platform_api.core.celery_app import celery_app

        for doc in documents:
            celery_app.send_task(
                "knowledge_base.parse_document",
                kwargs={"document_id": str(doc.id)},
                queue="kb_parsing",
            )
