"""Celery task 包装 — 文档解析异步任务"""

import asyncio
import logging
from uuid import UUID

# 复用 platform_api 的统一 Celery 应用，避免双 app 导致任务无法被同一 worker 消费
from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在 Celery worker 中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="knowledge_base.parse_document", bind=True, max_retries=3)
def parse_document_task(self, document_id: str) -> bool:
    """异步解析文档的 Celery task"""
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.services.parse_service import ParseService

    async def _execute():
        async with async_session_factory() as session:
            try:
                service = ParseService(session)
                result = await service.parse_document(UUID(document_id))
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

    try:
        return _run_async(_execute())
    except Exception as exc:
        logger.error("Parse task failed for %s: %s", document_id, exc)
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@celery_app.task(name="knowledge_base.parse_batch", bind=True)
def parse_batch_task(self, document_ids: list[str]) -> dict[str, bool]:
    """批量解析文档的 Celery task"""
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.services.parse_service import ParseService

    async def _execute():
        async with async_session_factory() as session:
            try:
                service = ParseService(session)
                result = await service.parse_batch([UUID(d) for d in document_ids])
                await session.commit()
                return {str(k): v for k, v in result.items()}
            except Exception:
                await session.rollback()
                raise

    return _run_async(_execute())
