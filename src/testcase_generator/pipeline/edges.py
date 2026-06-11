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


# 覆盖回填回环最大轮数（防无限循环；超过仍有零覆盖则带缺口进 verify，由报表如实记录）
MAX_RECONCILE = 2


def review_router(state: PipelineState) -> str:
    """review 阶段路由 — 覆盖回填/重做回环 + verify 事实核验关卡。

    - 存在零覆盖测试点 或 假覆盖测试点，且回填轮数 < MAX_RECONCILE
      → backfill（定向接地重生成；零覆盖追加、假覆盖替换）
    - 否则 → verify（进入事实核验关卡）
    """
    audit_report = state.get("audit_report")
    iters = state.get("reconcile_iterations", 0)
    if audit_report and iters < MAX_RECONCILE:
        if getattr(audit_report, "uncovered_test_point_ids", None) or getattr(
            audit_report, "weak_coverage_test_point_ids", None
        ):
            return "backfill"
    return "verify"
