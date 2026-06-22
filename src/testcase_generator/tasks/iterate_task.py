"""批量迭代 Celery 任务 — 异步执行 iteration_service.iterate"""

from __future__ import annotations

import asyncio
import logging

from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="testcase_generator.iterate_batch", bind=True)
def iterate_batch_task(
    self,
    batch_id: str,
    modified_case_ids: list[str],
    feedback: dict | None = None,
) -> dict:
    """批量迭代重生成（从 HTTP 请求中解耦，异步执行）"""
    return asyncio.run(_iterate(batch_id, modified_case_ids, feedback or {}))


async def _iterate(batch_id: str, modified_case_ids: list[str], feedback: dict) -> dict:
    from uuid import UUID

    from src.testcase_generator.services.iteration_service import IterationService

    service = IterationService()
    try:
        merged = await service.iterate(
            batch_id=UUID(batch_id),
            modified_case_ids=modified_case_ids,
            feedback=feedback,
        )
        logger.info("iterate_batch 完成: batch=%s regenerated=%d", batch_id, len(merged))
        return {"batch_id": batch_id, "status": "completed", "total_cases": len(merged)}
    except Exception as exc:
        logger.error("iterate_batch 失败: batch=%s err=%s", batch_id, exc)
        return {"batch_id": batch_id, "status": "failed", "error": str(exc)}
