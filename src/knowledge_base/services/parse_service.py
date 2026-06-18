"""文档解析编排服务 — 读 document → 解析 → 填充字段 → 触发 vectorize"""

import hashlib
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge_base.repositories.document_repo import DocumentRepository
from src.knowledge_base.services.parsers.markdown_parser import MarkdownParser
from src.knowledge_base.services.embedding.vectorize_pipeline import VectorizePipeline
from src.platform_api.core.settings import settings

logger = logging.getLogger(__name__)


async def run_image_caption_pipeline(doc, parsed_content: str) -> tuple[str, dict]:
    """图解析流水线：收集图 → 视觉描述 → 注入 content。

    返回 (enriched_content, image_captions_dict)。
    仅在 image_caption_enabled=True 时被调用。
    """
    from src.knowledge_base.services.image_caption.caption_service import caption_images
    from src.knowledge_base.services.image_caption.content_injector import inject_captions
    from src.knowledge_base.services.image_caption.image_collector import collect_images
    from src.testcase_generator.services.llm_client import get_llm_client

    from minio import Minio

    minio_client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    prefix = f"systems/{doc.system_id}/documents/"
    if doc.folder_path:
        prefix = f"systems/{doc.system_id}/documents/{doc.folder_path}/"

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
    minio_objects = [
        obj for obj in minio_client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
        if any(obj.object_name.lower().endswith(ext) for ext in image_exts)
    ]

    image_refs_list = collect_images(
        system_id=str(doc.system_id),
        folder_path=doc.folder_path,
        image_refs=doc.image_refs or [],
        minio_objects=minio_objects,
    )

    if not image_refs_list:
        return parsed_content, {}

    image_bytes_map: dict[str, bytes] = {}
    for ref in image_refs_list:
        try:
            response = minio_client.get_object(settings.minio_bucket, ref.object_key)
            image_bytes_map[ref.object_key] = response.read()
            response.close()
            response.release_conn()
        except Exception as e:  # noqa: BLE001
            logger.warning("图片下载失败 %s: %s", ref.object_key, e)

    client = get_llm_client()
    captions = await caption_images(
        image_refs=image_refs_list,
        image_bytes_map=image_bytes_map,
        generate_fn=client.generate_structured,
        concurrency=settings.image_caption_concurrency,
    )

    enriched = inject_captions(parsed_content, captions)
    captions_dict = {c.filename: c.model_dump() for c in captions}

    return enriched, captions_dict


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

        # ── 图解析（image_caption_enabled 开关控制）──────────────────────────
        final_content = parsed.content
        image_captions = None
        if settings.image_caption_enabled:
            logger.info("图解析开关已开，启动图描述流水线: doc=%s", document_id)
            final_content, image_captions = await run_image_caption_pipeline(doc, parsed.content)

        # 计算 content_hash（基于最终 content，含图述）
        content_hash = hashlib.sha256(final_content.encode("utf-8")).hexdigest()

        # 去重检查
        existing = await self.repo.find_by_content_hash(content_hash)
        if existing and existing.id != document_id:
            logger.info("Duplicate content detected (hash=%s), document %s", content_hash, document_id)
            return False

        # 更新文档字段
        await self.repo.update(
            document_id,
            content=final_content,
            image_refs=parsed.image_refs,
            content_hash=content_hash,
            metadata_=parsed.frontmatter if parsed.frontmatter else doc.metadata_,
            image_captions=image_captions,
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
