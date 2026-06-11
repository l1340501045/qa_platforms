"""覆盖回填节点 — 对 review 算出的零覆盖测试点定向重生成用例，再回 review 复核。

弃"功能点级丢失/无回填循环"的旧缺陷：write_cases 子批失败隔离后仍可能有零覆盖测试点，
此节点只针对 uncovered_test_point_ids 重生成，闭合覆盖回环（轮数受 MAX_RECONCILE 上限约束）。
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.testcase_generator.schemas.audit_report import AuditReport
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.write_cases.node import generate_cases

logger = logging.getLogger(__name__)


async def backfill_node(state: PipelineState) -> dict:
    """对零覆盖测试点定向重生成，自己重算覆盖率并更新 audit_report。

    设计：review（全量 LLM 审计 + 补全）只跑一次；backfill 自循环（不回 review），
    避免每轮回环重跑昂贵审计、且把上一轮 [审计补全] 用例当普通用例重审、additions 跨轮累积。
    覆盖率重算是纯集合运算（无 LLM），路由据更新后的 uncovered_test_point_ids 决定继续或放行。
    """
    iters = state.get("reconcile_iterations", 0) + 1
    audit_report: AuditReport | None = state.get("audit_report")
    test_points: list[TestPointSchema] = state.get("test_points", [])
    final_cases: list[GeneratedTestCase] = state.get("final_test_cases") or state.get("test_cases", [])

    uncovered_ids = set(audit_report.uncovered_test_point_ids) if audit_report else set()
    if not uncovered_ids:
        return {"reconcile_iterations": iters, "current_stage": "backfill"}

    uncovered_tps = [tp for tp in test_points if tp.id in uncovered_ids]
    logger.info("backfill 第 %d 轮：对 %d 个零覆盖测试点定向重生成", iters, len(uncovered_tps))

    parsed_context = state["parsed_context"]
    system_id = UUID(state["system_id"])
    new_cases, failed = await generate_cases(
        parsed_context, uncovered_tps, system_id, start_counter=len(final_cases)
    )

    merged = final_cases + new_cases

    # 重算覆盖（纯集合运算，不触发 LLM）：剩余仍零覆盖的测试点
    covered_tp_ids = {c.test_point_id for c in merged if c.test_point_id}
    all_tp_ids = {tp.id for tp in test_points}
    still_uncovered = sorted(all_tp_ids - covered_tp_ids)
    logger.info(
        "backfill 第 %d 轮：新增 %d 条（失败子批 %d），剩余零覆盖 %d 个",
        iters, len(new_cases), len(failed), len(still_uncovered),
    )

    out: dict = {
        "final_test_cases": merged,
        "reconcile_iterations": iters,
        "current_stage": "backfill",
    }
    # 更新 audit_report.uncovered_test_point_ids，供 review_router 判断是否继续回填
    if audit_report is not None:
        out["audit_report"] = audit_report.model_copy(
            update={
                "uncovered_test_point_ids": still_uncovered,
                "per_test_point_covered": len(covered_tp_ids & all_tp_ids),
            }
        )
    return out
