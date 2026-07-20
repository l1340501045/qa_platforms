"""Celery task 包装 — 文档解析异步任务"""

import asyncio
import logging
from uuid import UUID

# 复用 platform_api 的统一 Celery 应用，避免双 app 导致任务无法被同一 worker 消费
from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


def _safe_task_error(operation: str, exc: Exception) -> RuntimeError:
    """构造不包含上游响应正文的 Celery 错误。"""
    return RuntimeError(f"{type(exc).__name__}: {operation}失败")


def _run_async(coro):
    """在 Celery worker 中运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _parse_document(document_id: str) -> bool:
    """使用本次 Worker 开始时的最新模型配置解析单个文档。"""
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.services.parse_service import ParseService
    from src.platform_api.core.model_runtime import model_runtime_scope
    from src.platform_api.services.model_settings_service import ModelSettingsService

    async with async_session_factory() as session:
        try:
            model_bundle = await ModelSettingsService(session).load_active_bundle()
            with model_runtime_scope(model_bundle):
                result = await ParseService(session).parse_document(UUID(document_id))
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def _parse_batch(document_ids: list[str]) -> dict[str, bool]:
    """使用本次 Worker 开始时的最新模型配置批量解析文档。"""
    from src.knowledge_base.db import async_session_factory
    from src.knowledge_base.services.parse_service import ParseService
    from src.platform_api.core.model_runtime import model_runtime_scope
    from src.platform_api.services.model_settings_service import ModelSettingsService

    async with async_session_factory() as session:
        try:
            model_bundle = await ModelSettingsService(session).load_active_bundle()
            with model_runtime_scope(model_bundle):
                result = await ParseService(session).parse_batch([UUID(document_id) for document_id in document_ids])
            await session.commit()
            return {str(document_id): succeeded for document_id, succeeded in result.items()}
        except Exception:
            await session.rollback()
            raise


@celery_app.task(name="knowledge_base.parse_document", bind=True, max_retries=3)
def parse_document_task(self, document_id: str) -> bool:
    """异步解析文档的 Celery task"""
    try:
        return _run_async(_parse_document(document_id))
    except Exception as exc:
        error_type = type(exc).__name__
        logger.error("Parse task failed for %s error_type=%s", document_id, error_type)
        safe_error = _safe_task_error("文档解析", exc)
        raise self.retry(exc=safe_error, countdown=60 * (self.request.retries + 1)) from None


@celery_app.task(name="knowledge_base.parse_batch", bind=True)
def parse_batch_task(self, document_ids: list[str]) -> dict[str, bool]:
    """批量解析文档的 Celery task"""
    try:
        return _run_async(_parse_batch(document_ids))
    except Exception as exc:
        error_type = type(exc).__name__
        logger.error("Parse batch task failed error_type=%s", error_type)
        raise _safe_task_error("批量文档解析", exc) from None
