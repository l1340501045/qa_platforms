"""遗留 KB Celery 入口：安全委托正式解析任务。"""

from __future__ import annotations

import logging

from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="platform_api.trigger_kb_parse")
def trigger_kb_parse(document_id: str) -> dict:
    """将遗留调用安全委托给正式 KB 解析任务。

    正式任务会在 Worker 真正开始执行时读取最新模型版本，并在该次执行期间
    固定运行时作用域。
    """
    try:
        result = celery_app.send_task(
            "knowledge_base.parse_document",
            kwargs={"document_id": document_id},
            queue="kb_parsing",
        )
    except Exception as exc:  # noqa: BLE001 — 遗留任务必须返回固定、可序列化的安全错误
        error_type = type(exc).__name__
        logger.error(
            "KB parse delegation failed for document %s error_type=%s",
            document_id,
            error_type,
        )
        return {
            "status": "failed",
            "document_id": document_id,
            "error": "KB_PARSE_DELEGATION_FAILED",
            "error_type": error_type,
        }

    logger.info(
        "KB parse delegated for document %s task_id=%s",
        document_id,
        result.id,
    )
    return {
        "status": "delegated",
        "document_id": document_id,
        "task_id": result.id,
    }
