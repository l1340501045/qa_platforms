"""覆盖回填节点 — 对 review 算出的零覆盖测试点定向重生成用例，再回 review 复核。

弃"功能点级丢失/无回填循环"的旧缺陷：write_cases 子批失败隔离后仍可能有零覆盖测试点，
此节点只针对 uncovered_test_point_ids 重生成，闭合覆盖回环（轮数受 MAX_RECONCILE 上限约束）。
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.write_cases.node import generate_cases

logger = logging.getLogger(__name__)


async def backfill_node(state: PipelineState) -> dict:
    """对零覆盖测试点定向重生成，合并进用例集后交回 review 复核覆盖率。"""
    iters = state.get("reconcile_iterations", 0) + 1
    audit_report = state.get("audit_report")
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
    logger.info("backfill 第 %d 轮：新增 %d 条用例（失败子批 %d）", iters, len(new_cases), len(failed))

    merged = final_cases + new_cases
    return {
        # 同步回 test_cases，使 review 基于全量重算覆盖率
        "test_cases": merged,
        "final_test_cases": merged,
        "reconcile_iterations": iters,
        "current_stage": "backfill",
    }
