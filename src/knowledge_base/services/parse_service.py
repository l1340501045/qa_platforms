"""文档解析编排服务 — 读 document → 解析 → 填充字段 → 触发 vectorize"""

import hashlib
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.services.parsers.markdown_parser import MarkdownParser
from src.knowledge_base.services.embedding.vectorize_pipeline import VectorizePipeline

logger = logging.getLogger(__name__)


class ParseService:
    """文档解析编排"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DocumentRepository(session)
        self.parser = MarkdownParser()
        self.vectorize_pipeline = VectorizePipeline(session)

    async def parse_document(self, document_id: UUID) -> bool:
        """解析文档并自动触发向量化"""
        doc = await self.repo.get_by_id(document_id)
        if doc is None:
            logger.warning("Document %s not found, skipping parse", document_id)
            return False

        # 读取原始内容（storage_path 指向的 md 内容已存于 content 字段或需从存储读取）
        raw_text = doc.content
        if not raw_text:
            logger.warning("Document %s has empty content, skipping", document_id)
            return False

        # 解析 markdown
        parsed = self.parser.parse(raw_text)

        # 计算 content_hash
        content_hash = hashlib.sha256(parsed.content.encode("utf-8")).hexdigest()

        # 去重检查
        existing = await self.repo.find_by_content_hash(content_hash)
        if existing and existing.id != document_id:
            logger.info("Duplicate content detected (hash=%s), document %s", content_hash, document_id)
            return False

        # 更新文档字段
        await self.repo.update(
            document_id,
            content=parsed.content,
            image_refs=parsed.image_refs,
            content_hash=content_hash,
            metadata_=parsed.frontmatter if parsed.frontmatter else doc.metadata_,
        )

        await self.session.commit()

        # 自动触发向量化
        logger.info("Parse complete for %s, triggering vectorize", document_id)
        await self.vectorize_pipeline.vectorize_document(document_id)

        return True

    async def parse_batch(self, document_ids: list[UUID]) -> dict[UUID, bool]:
        """批量解析文档"""
        results: dict[UUID, bool] = {}
        for doc_id in document_ids:
            try:
                results[doc_id] = await self.parse_document(doc_id)
            except Exception as e:
                logger.error("Failed to parse document %s: %s", doc_id, e)
                results[doc_id] = False
        return results
