"""KB 集成：文档上传后发布解析+向量化任务

对 knowledge_base 解析服务的封装，作为 Celery 任务独立运行。
"""

from __future__ import annotations

import logging

from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="platform_api.trigger_kb_parse")
def trigger_kb_parse(document_id: str) -> dict:
    """调用 knowledge_base 解析文档

    触发链路：
    1. 解析文档内容（Markdown → 结构化）
    2. 生成 embedding 向量
    3. 更新 document.embedding_status
    """
    import asyncio

    return asyncio.run(_execute_kb_parse(document_id))


async def _execute_kb_parse(document_id: str) -> dict:
    """内部异步执行逻辑"""
    from uuid import UUID

    from sqlalchemy import update

    from src.platform_api.core.database import get_session_factory
    from src.platform_api.models.knowledge import Document

    session_factory = get_session_factory()

    try:
        # 尝试调用 knowledge_base 解析服务
        try:
            from src.knowledge_base.services.parse_service import ParseService

            parse_service = ParseService()
            await parse_service.parse_document(document_id=UUID(document_id))
        except ImportError:
            logger.warning(
                "knowledge_base.services.parse_service not available, "
                "falling back to status update only for document %s",
                document_id,
            )

        # 更新 embedding_status
        async with session_factory() as session:
            stmt = update(Document).where(Document.id == UUID(document_id)).values(embedding_status="processing")
            await session.execute(stmt)
            await session.commit()

        logger.info("KB parse triggered for document %s", document_id)
        return {"status": "triggered", "document_id": document_id}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.exception("KB parse failed for document %s", document_id)
        return {"status": "failed", "document_id": document_id, "error": error_msg}
