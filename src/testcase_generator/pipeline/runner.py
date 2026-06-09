"""T038: 端到端运行入口 — 编译图 + RedisSaver + 执行"""

from __future__ import annotations

from typing import Any

from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from src.testcase_generator.pipeline.graph import build_pipeline
from src.testcase_generator.schemas.pipeline_state import PipelineState


def compile_pipeline(checkpointer: Optional[BaseCheckpointSaver] = None) -> CompiledStateGraph:
    """编译流水线图

    checkpointer 必须由调用方在「自身事件循环内」打开后传入
    （见 persistence.open_async_checkpointer），避免跨事件循环复用连接。
    """
    graph = build_pipeline()
    return graph.compile(checkpointer=checkpointer)


async def run_pipeline(
    document_id: str,
    system_id: str,
    batch_id: str,
    generation_config: dict | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """端到端运行流水线

    Args:
        document_id: 种子文档 ID
        system_id: 系统 ID
        batch_id: 批次 ID
        generation_config: 生成配置（可选）
        thread_id: LangGraph thread ID（断点续跑时传入已有 ID）

    Returns:
        最终 PipelineState 字典，含 yaml_output / markdown_output
        如果被 interrupt 挂起，返回的是挂起时的 state（需检查 snapshot.next）
    """
    app = compile_pipeline()

    initial_state: PipelineState = {
        "document_id": document_id,
        "system_id": system_id,
        "batch_id": batch_id,
        "generation_config": generation_config or {},
    }

    config = {"configurable": {"thread_id": thread_id or batch_id}}

    # 异步流式执行
    final_state: dict[str, Any] = {}
    async for event in app.astream(initial_state, config=config):
        # LangGraph astream 输出格式: {"node_name": {state_updates}}
        for _node_name, node_output in event.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)

    return final_state


async def resume_pipeline(
    thread_id: str,
    clarification_answers: list[dict],
) -> dict[str, Any]:
    """从 interrupt 恢复流水线执行

    在 Gate NO_GO 后，人工提供澄清答案，通过 LangGraph Command(resume=...) 恢复执行。
    interrupt_node 中的 interrupt() 返回值即为 Command.resume 传入的数据。

    Args:
        thread_id: 原始 thread_id（与 batch_id 相同或自定义）
        clarification_answers: 人工澄清答案列表

    Returns:
        恢复后的最终 PipelineState
    """
    app = compile_pipeline()
    config = {"configurable": {"thread_id": thread_id}}

    # 使用 LangGraph Command(resume=...) 恢复中断
    # interrupt_node 中 interrupt() 的返回值 = Command.resume 的值
    resume_cmd = Command(resume={"clarification_answers": clarification_answers})

    final_state: dict[str, Any] = {}
    async for event in app.astream(resume_cmd, config=config):
        for _node_name, node_output in event.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)

    return final_state
