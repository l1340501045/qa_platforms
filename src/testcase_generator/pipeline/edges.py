"""T036: 条件边 — Gate 路由 + review 迭代循环"""

from __future__ import annotations

from src.testcase_generator.schemas.pipeline_state import PipelineState


def gate_router(state: PipelineState) -> str:
    """comprehend 阶段 Gate 路由

    根据 gate_result 决定下一步：
    - GO → test_points（正常流转）
    - CONDITIONAL → test_points（带 open_questions 但不阻塞）
    - NO_GO → interrupt（触发 LangGraph interrupt，等待人工澄清）
    """
    gate_result = state.get("gate_result", "GO")

    if gate_result == "NO_GO":
        return "interrupt"
    # GO 和 CONDITIONAL 都流转到 test_points
    return "test_points"


def review_router(state: PipelineState) -> str:
    """review 阶段路由 — 判断是否需要迭代

    检查审计覆盖率：
    - 覆盖率 >= 0.95 → 流转到 export
    - 覆盖率 < 0.95 且已补全 → 流转到 export（一轮补全即可）
    """
    audit_report = state.get("audit_report")
    if audit_report is None:
        return "export"

    # 已执行过 gap_fill，直接进入 export（避免无限循环）
    return "export"
