"""T039: Celery 任务定义 — 启动流水线 / 挂起(Gate NO_GO) / 恢复(用户回答后)"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.platform_api.core.celery_app import celery_app
from src.platform_api.models.enums import BatchStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="testcase_generator.run_pipeline", bind=True)
def run_pipeline_task(
    self,
    batch_id: str,
    document_id: str,
    system_id: str,
    config: dict | None = None,
    resume_from: str | None = None,
) -> dict:
    """启动 LangGraph 流水线 Celery 任务

    1. 更新 batch status → running
    2. 构建初始 PipelineState
    3. 调用 run_pipeline()
    4. 每阶段完成回调更新 batch.current_stage
    5. 完成后 status → completed；Gate NO_GO → status=suspended
    6. 失败 → status=failed + 错误信息
    """
    _ = resume_from  # 兼容 RetryService 的历史任务参数；恢复点仍由 checkpoint 决定。
    return asyncio.run(
        _execute_pipeline(
            celery_task_id=self.request.id,
            batch_id=batch_id,
            document_id=document_id,
            system_id=system_id,
            config=config,
        )
    )


async def _execute_pipeline(
    celery_task_id: str | None,
    batch_id: str,
    document_id: str,
    system_id: str,
    config: dict | None,
) -> dict:
    """内部异步执行逻辑

    LangGraph interrupt 机制说明：
    - interrupt() 调用后，astream 正常结束（不抛异常）
    - 需要通过 app.aget_state(config) 检查 snapshot.next 和 snapshot.tasks
      来判断是否处于中断状态
    """
    from sqlalchemy import update

    from src.platform_api.core.model_runtime import model_runtime_scope
    from src.platform_api.models.testcase import TestBatch
    from src.platform_api.services.task_model_runtime import load_active_model_bundle
    from src.testcase_generator.db import async_session_factory

    # 1. 更新 batch status → running
    async with async_session_factory() as session:
        model_bundle = await load_active_model_bundle(session)
        stmt = (
            update(TestBatch)
            .where(TestBatch.id == batch_id)
            .values(
                status=BatchStatus.RUNNING,
                celery_task_id=celery_task_id,
                started_at=datetime.now(timezone.utc),
                generation_config=config,
            )
        )
        await session.execute(stmt)
        await session.commit()

    with model_runtime_scope(model_bundle):
        return await _execute_pipeline_graph(batch_id, document_id, system_id, config)


async def _execute_pipeline_graph(
    batch_id: str,
    document_id: str,
    system_id: str,
    config: dict | None,
) -> dict:
    """在已绑定模型配置版本的上下文中运行完整流水线。"""

    from src.testcase_generator.pipeline.persistence import open_async_checkpointer
    from src.testcase_generator.pipeline.runner import compile_pipeline
    from src.testcase_generator.tasks.callbacks import (
        on_pipeline_complete,
        on_pipeline_failed,
        on_pipeline_suspended,
        on_stage_complete,
    )

    try:
        # 2-4. 在任务自身事件循环内打开 checkpointer，编译并运行流水线
        async with open_async_checkpointer() as checkpointer:
            app = compile_pipeline(checkpointer=checkpointer)
            initial_state = {
                "document_id": document_id,
                "system_id": system_id,
                "batch_id": batch_id,
                "generation_config": config or {},
            }
            run_config = {"configurable": {"thread_id": batch_id}}

            # 异步流式执行
            final_state: dict = {}
            async for event in app.astream(initial_state, config=run_config):
                # LangGraph astream 输出格式: {"node_name": {state_updates}}
                for _node_name, node_output in event.items():
                    if isinstance(node_output, dict):
                        final_state.update(node_output)

            # 5. 检查是否被 interrupt 挂起
            # LangGraph 的 interrupt() 不抛异常，stream 正常结束后需检查 state
            snapshot = await app.aget_state(run_config)

        if snapshot.next:
            # next 非空说明图还有待执行节点 → 被 interrupt 挂起
            open_questions = _extract_open_questions_from_snapshot(snapshot)
            await on_pipeline_suspended(batch_id=batch_id, open_questions=open_questions)
            return {"status": "suspended", "batch_id": batch_id, "open_questions": open_questions}

        # 检查错误
        error = final_state.get("error")
        if error:
            current_stage = final_state.get("current_stage", "")
            await on_pipeline_failed(batch_id=batch_id, error=error, stage=current_stage)
            return {"status": "failed", "error": error}

        # 正常完成 — 提取 test_points 和 test_cases
        final_cases = final_state.get("final_test_cases", [])
        audit_report = final_state.get("audit_report")
        test_points = final_state.get("test_points", [])
        rules = final_state.get("rules", [])

        audit_dict: dict = {}
        if audit_report is not None:
            audit_dict = audit_report.model_dump() if hasattr(audit_report, "model_dump") else audit_report

        await on_pipeline_complete(
            batch_id=batch_id,
            final_cases=[c.model_dump() if hasattr(c, "model_dump") else c for c in final_cases],
            audit_report=audit_dict,
            test_points=[tp.model_dump() if hasattr(tp, "model_dump") else tp for tp in test_points],
            rules=[r.model_dump() if hasattr(r, "model_dump") else r for r in rules],
        )

        # 阶段产物回调
        for stage_name in ("parse", "comprehend", "rule_extract", "test_points", "write_cases", "review", "export"):
            artifact_key = f"{stage_name}_artifact"
            if artifact_key in final_state:
                await on_stage_complete(batch_id=batch_id, stage=stage_name, artifact=final_state[artifact_key])

        return {"status": "completed", "batch_id": batch_id}

    except Exception as e:
        error_type = type(e).__name__
        error_msg = f"{error_type}: 模型流水线执行失败"
        logger.error("Pipeline failed for batch %s error_type=%s", batch_id, error_type)
        await on_pipeline_failed(batch_id=batch_id, error=error_msg, stage="unknown")
        return {"status": "failed", "error": error_msg}


@celery_app.task(name="testcase_generator.resume_pipeline")
def resume_pipeline_task(batch_id: str, clarification_answers: list[dict]) -> dict:
    """Gate NO_GO 后恢复流水线

    1. 从 Redis checkpoint 加载挂起状态
    2. 注入 clarification_answers via Command(resume=...)
    3. 恢复执行
    4. 更新 status → running
    """
    return asyncio.run(_resume_pipeline(batch_id, clarification_answers))


async def _resume_pipeline(batch_id: str, clarification_answers: list[dict]) -> dict:
    """内部异步恢复逻辑"""
    from sqlalchemy import update

    from src.platform_api.core.model_runtime import model_runtime_scope
    from src.platform_api.models.testcase import TestBatch
    from src.platform_api.services.task_model_runtime import load_active_model_bundle
    from src.testcase_generator.db import async_session_factory

    # 1. 更新 status → running
    async with async_session_factory() as session:
        model_bundle = await load_active_model_bundle(session)
        stmt = update(TestBatch).where(TestBatch.id == batch_id).values(status=BatchStatus.RUNNING)
        await session.execute(stmt)
        await session.commit()

    with model_runtime_scope(model_bundle):
        return await _resume_pipeline_graph(batch_id, clarification_answers)


async def _resume_pipeline_graph(batch_id: str, clarification_answers: list[dict]) -> dict:
    """在本次恢复开始时读取的最新模型配置上下文中执行流水线。"""
    from langgraph.types import Command

    from src.testcase_generator.pipeline.persistence import open_async_checkpointer
    from src.testcase_generator.pipeline.runner import compile_pipeline
    from src.testcase_generator.tasks.callbacks import (
        on_pipeline_complete,
        on_pipeline_failed,
        on_pipeline_suspended,
    )

    try:
        # 2-3. 在任务自身事件循环内打开 checkpointer，使用 Command(resume=...) 恢复 LangGraph
        async with open_async_checkpointer() as checkpointer:
            app = compile_pipeline(checkpointer=checkpointer)
            run_config = {"configurable": {"thread_id": batch_id}}

            # LangGraph resume: 传入 Command 对象恢复中断
            resume_input = Command(resume={"clarification_answers": clarification_answers})

            final_state: dict = {}
            async for event in app.astream(resume_input, config=run_config):
                for _node_name, node_output in event.items():
                    if isinstance(node_output, dict):
                        final_state.update(node_output)

            # 检查是否再次 interrupt
            snapshot = await app.aget_state(run_config)

        if snapshot.next:
            open_questions = _extract_open_questions_from_snapshot(snapshot)
            await on_pipeline_suspended(batch_id=batch_id, open_questions=open_questions)
            return {"status": "suspended", "batch_id": batch_id, "open_questions": open_questions}

        error = final_state.get("error")
        if error:
            await on_pipeline_failed(batch_id=batch_id, error=error, stage=final_state.get("current_stage", ""))
            return {"status": "failed", "error": error}

        final_cases = final_state.get("final_test_cases", [])
        audit_report = final_state.get("audit_report")
        test_points = final_state.get("test_points", [])
        rules = final_state.get("rules", [])

        audit_dict_r: dict = {}
        if audit_report is not None:
            audit_dict_r = audit_report.model_dump() if hasattr(audit_report, "model_dump") else audit_report

        await on_pipeline_complete(
            batch_id=batch_id,
            final_cases=[c.model_dump() if hasattr(c, "model_dump") else c for c in final_cases],
            audit_report=audit_dict_r,
            test_points=[tp.model_dump() if hasattr(tp, "model_dump") else tp for tp in test_points],
            rules=[r.model_dump() if hasattr(r, "model_dump") else r for r in rules],
        )

        return {"status": "completed", "batch_id": batch_id}

    except Exception as e:
        error_type = type(e).__name__
        error_msg = f"{error_type}: 模型流水线恢复失败"
        logger.error("Pipeline resume failed for batch %s error_type=%s", batch_id, error_type)
        await on_pipeline_failed(batch_id=batch_id, error=error_msg, stage="unknown")
        return {"status": "failed", "error": error_msg}


def _extract_open_questions_from_snapshot(snapshot) -> list:
    """从 LangGraph StateSnapshot 中提取 open_questions

    interrupt() 被调用后，snapshot.tasks 中包含 interrupts 信息。
    interrupt_handler.py 传递 questions_for_user 列表作为 interrupt value。
    """
    open_questions: list = []

    # snapshot.tasks 包含挂起任务的中断信息
    for task in snapshot.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            for intr in task.interrupts:
                val = intr.value
                if isinstance(val, dict):
                    # graph.py interrupt_node 传的格式
                    open_questions = val.get("open_questions", [])
                    if open_questions:
                        return open_questions
                elif isinstance(val, list):
                    # interrupt_handler.py 传的 questions_for_user 列表
                    return val

    # 回退：从 snapshot.values 中获取
    values = snapshot.values if hasattr(snapshot, "values") else {}
    if isinstance(values, dict):
        open_questions = values.get("open_questions", [])

    return open_questions
