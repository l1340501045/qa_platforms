"""T035: StateGraph 组装 — 6 阶段流水线图"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.parse.node import parse_node
from src.testcase_generator.stages.comprehend.node import comprehend_node
from src.testcase_generator.stages.test_points.node import test_points_node
from src.testcase_generator.stages.write_cases.node import write_cases_node
from src.testcase_generator.stages.review.node import review_node
from src.testcase_generator.stages.review.backfill_node import backfill_node
from src.testcase_generator.stages.verify.node import verify_node
from src.testcase_generator.stages.dedup.node import dedup_node
from src.testcase_generator.stages.export.node import export_node
from src.testcase_generator.pipeline.edges import gate_router, review_router


async def interrupt_node(state: PipelineState) -> dict:
    """Gate NO_GO 时触发中断，等待人工澄清

    使用 LangGraph 原生 interrupt()（硬约束#2）。
    人工提供 clarification_answers 后，流水线从 comprehend 恢复。

    注意：comprehend_node 只负责产出 gate_result + open_questions，
    interrupt 逻辑由本节点独占，避免两处 interrupt 并存。
    """
    open_questions = state.get("open_questions", [])
    # LangGraph 原生 interrupt — 暂停执行，等待外部 Command(resume=...) 恢复
    clarification = interrupt(
        {
            "type": "clarification_required",
            "open_questions": open_questions,
            "message": "理解覆盖度不足，需要人工澄清以下问题后继续",
        }
    )
    return {
        "clarification_answers": clarification,
        "current_stage": "comprehend",
    }


def build_pipeline() -> StateGraph:
    """构建 6 阶段流水线图

    节点：parse → comprehend → test_points → write_cases → review → export
    条件边：comprehend → (GO→test_points, CONDITIONAL→test_points, NO_GO→interrupt→comprehend)
    """
    graph = StateGraph(PipelineState)

    # 注册节点（全部使用 stages/ 下的真实实现）
    graph.add_node("parse", parse_node)
    graph.add_node("comprehend", comprehend_node)
    graph.add_node("interrupt", interrupt_node)
    graph.add_node("test_points", test_points_node)
    graph.add_node("write_cases", write_cases_node)
    graph.add_node("review", review_node)
    graph.add_node("backfill", backfill_node)
    graph.add_node("verify", verify_node)
    graph.add_node("dedup", dedup_node)
    graph.add_node("export", export_node)

    # 入口边
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "comprehend")

    # comprehend 后走 Gate 路由（硬约束#2: LangGraph 原生 interrupt）
    graph.add_conditional_edges(
        "comprehend",
        gate_router,
        {
            "test_points": "test_points",
            "interrupt": "interrupt",
        },
    )

    # interrupt 恢复后回到 comprehend 重新评估
    graph.add_edge("interrupt", "comprehend")

    # 正常流
    graph.add_edge("test_points", "write_cases")
    graph.add_edge("write_cases", "review")

    # review 后路由：零覆盖测试点 → backfill 定向回填；达标 → verify
    # review（全量 LLM 审计+补全）只跑一次；backfill 自循环重算覆盖，避免重复审计/additions 累积。
    graph.add_conditional_edges(
        "review",
        review_router,
        {
            "backfill": "backfill",
            "verify": "verify",
        },
    )

    # backfill 自循环：仍有零覆盖且未达上限 → 再回填；否则 → verify（受 MAX_RECONCILE 约束）
    graph.add_conditional_edges(
        "backfill",
        review_router,
        {
            "backfill": "backfill",
            "verify": "verify",
        },
    )

    # verify 事实核验 → dedup 全局去重 → export
    graph.add_edge("verify", "dedup")
    graph.add_edge("dedup", "export")

    # 终点
    graph.add_edge("export", END)

    return graph
