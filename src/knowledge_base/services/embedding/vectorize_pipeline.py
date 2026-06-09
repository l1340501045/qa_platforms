"""向量化管道 — 分块 → embedding → 写入 pgvector"""

import logging
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.repositories.embedding_repo import EmbeddingRepository
from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)

# 分块参数
_CHUNK_MAX_CHARS = 1000
_CHUNK_OVERLAP_CHARS = 100


class VectorizePipeline:
    """文档向量化管道"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.embedding_repo = EmbeddingRepository(session)
        self.embedding_client = EmbeddingClient()

    async def vectorize_document(self, document_id: UUID) -> bool:
        """对单个文档执行完整向量化流程"""
        doc = await self.doc_repo.get_by_id(document_id)
        if doc is None:
            logger.warning("Document %s not found for vectorization", document_id)
            return False

        if not doc.content:
            logger.warning("Document %s has no content to vectorize", document_id)
            return False

        try:
            # 更新状态为处理中
            await self.doc_repo.update_embedding_status(document_id, "processing")
            await self.session.commit()

            # 1. 分块
            chunks = self._split_into_chunks(doc.content)
            if not chunks:
                await self.doc_repo.update_embedding_status(document_id, "completed")
                await self.session.commit()
                return True

            # 2. 批量 embedding
            texts = [c["content"] for c in chunks]
            embeddings = await self.embedding_client.embed_batch(texts)

            if len(embeddings) != len(chunks):
                logger.error("Embedding count mismatch for doc %s", document_id)
                await self.doc_repo.update_embedding_status(document_id, "failed")
                await self.session.commit()
                return False

            # 3. 清除旧 embedding
            await self.embedding_repo.delete_by_document(document_id)

            # 4. 批量写入 pgvector
            records = [
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "chunk_heading": chunks[i].get("heading"),
                    "chunk_content": chunks[i]["content"],
                    "embedding": embeddings[i],
                }
                for i in range(len(chunks))
            ]
            await self.embedding_repo.bulk_insert(records)

            # 5. 更新状态为完成
            await self.doc_repo.update_embedding_status(document_id, "completed")
            await self.session.commit()

            logger.info("Vectorized document %s: %d chunks", document_id, len(chunks))
            return True

        except Exception as e:
            logger.error("Vectorization failed for doc %s: %s", document_id, e)
            await self.session.rollback()
            # 尝试标记失败状态
            try:
                await self.doc_repo.update_embedding_status(document_id, "failed")
                await self.session.commit()
            except Exception:
                pass
            return False

    async def vectorize_batch(self, document_ids: list[UUID]) -> dict[UUID, bool]:
        """批量向量化"""
        results: dict[UUID, bool] = {}
        for doc_id in document_ids:
            results[doc_id] = await self.vectorize_document(doc_id)
        return results

    def _split_into_chunks(self, content: str) -> list[dict]:
        """将文档内容按 heading 分块，超长段落再按字符数切分"""
        chunks: list[dict] = []

        # 按 markdown heading 拆分
        sections = re.split(r"(?m)^(#{1,6}\s+.+)$", content)

        current_heading: str | None = None
        current_text = ""

        for part in sections:
            if re.match(r"^#{1,6}\s+", part):
                # 保存前一段
                if current_text.strip():
                    chunks.extend(self._split_long_text(current_text.strip(), current_heading))
                current_heading = part.strip().lstrip("#").strip()
                current_text = ""
            else:
                current_text += part

        # 处理最后一段
        if current_text.strip():
            chunks.extend(self._split_long_text(current_text.strip(), current_heading))

        # 重新编号
        for i, chunk in enumerate(chunks):
            chunk["index"] = i

        return chunks

    def _split_long_text(self, text: str, heading: str | None) -> list[dict]:
        """将超长文本按字符数切分（带 overlap）"""
        if len(text) <= _CHUNK_MAX_CHARS:
            return [{"heading": heading, "content": text}]

        parts: list[dict] = []
        start = 0
        while start < len(text):
            end = start + _CHUNK_MAX_CHARS
            chunk_text = text[start:end]
            parts.append({"heading": heading, "content": chunk_text})
            start = end - _CHUNK_OVERLAP_CHARS

        return parts
