"""TC 集成：封装 testcase_generator 任务调用

这里只是对 run_pipeline_task / resume_pipeline_task 的业务层封装。
真正的 Celery 任务定义在 testcase_generator/tasks/pipeline_task.py。

本模块提供便捷的调用接口，供 platform_api 服务层使用。
"""

from __future__ import annotations

import logging

from src.platform_api.core.celery_app import celery_app

logger = logging.getLogger(__name__)


def trigger_pipeline(
    batch_id: str,
    document_id: str,
    system_id: str,
    config: dict | None = None,
) -> str:
    """触发用例生成流水线

    发布 Celery 任务到 testcase_generator.run_pipeline。

    Args:
        batch_id: 批次 ID
        document_id: 文档 ID
        system_id: 系统 ID
        config: 可选生成配置

    Returns:
        Celery task ID
    """
    result = celery_app.send_task(
        "testcase_generator.run_pipeline",
        kwargs={
            "batch_id": batch_id,
            "document_id": document_id,
            "system_id": system_id,
            "config": config,
        },
        queue="testcase_generation",
    )
    logger.info(
        "Pipeline triggered: batch_id=%s, task_id=%s",
        batch_id,
        result.id,
    )
    return result.id


def resume_pipeline(batch_id: str, clarification_answers: list[dict]) -> str:
    """恢复被 Gate NO_GO 挂起的流水线

    发布 Celery 任务到 testcase_generator.resume_pipeline。

    Args:
        batch_id: 批次 ID
        clarification_answers: 人工澄清答案列表

    Returns:
        Celery task ID
    """
    result = celery_app.send_task(
        "testcase_generator.resume_pipeline",
        kwargs={
            "batch_id": batch_id,
            "clarification_answers": clarification_answers,
        },
        queue="testcase_generation",
    )
    logger.info(
        "Pipeline resumed: batch_id=%s, task_id=%s",
        batch_id,
        result.id,
    )
    return result.id
