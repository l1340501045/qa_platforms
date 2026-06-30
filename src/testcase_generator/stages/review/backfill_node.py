"""覆盖回填节点 — 对 review 算出的零覆盖测试点定向重生成用例，再回 review 复核。

弃"功能点级丢失/无回填循环"的旧缺陷：write_cases 子批失败隔离后仍可能有零覆盖测试点，
此节点只针对 uncovered_test_point_ids 重生成，闭合覆盖回环（轮数受 MAX_RECONCILE 上限约束）。
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.audit_report import AuditReport
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.review.rule_gate import (
    compute_rule_coverage,
    compute_structural_coverage,
)
from src.testcase_generator.stages.write_cases.node import generate_cases

logger = logging.getLogger(__name__)


def _max_case_counter(cases: list[GeneratedTestCase]) -> int:
    """现有用例逻辑 id（形如 TC-001）的最大序号；用作新用例的起始计数，
    确保新号段不与保留用例号段重叠（移除部分用例后 len 不再等于最大号，故不能用 len）。"""
    mx = 0
    for c in cases:
        cid = c.id or ""
        if "-" in cid:
            tail = cid.rsplit("-", 1)[-1]
            if tail.isdigit():
                mx = max(mx, int(tail))
    return mx


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
    # 假覆盖测试点仅在首轮处理（替换重做），之后清空避免回环反复；自循环只继续补零覆盖。
    weak_ids = set(getattr(audit_report, "weak_coverage_test_point_ids", []) or []) if audit_report else set()
    weak_ids -= uncovered_ids  # 零覆盖优先走追加逻辑

    if not uncovered_ids and not weak_ids:
        return {"reconcile_iterations": iters, "current_stage": "backfill"}

    # 假覆盖：先移除其现有（被判无效验证的）用例，稍后用接地生成替换
    kept_cases = [c for c in final_cases if c.test_point_id not in weak_ids] if weak_ids else final_cases
    removed = len(final_cases) - len(kept_cases)

    # 防御性兜底：显式纳入结构化未覆盖点（当前 review_node 已将其计入 uncovered_test_point_ids，
    # 此处 |= 幂等；保留以防 review 未来只统计非结构化点时不漏）。
    if settings.structural_coverage_enabled and audit_report and audit_report.uncovered_structural_keys:
        struct_uncovered_ids = {
            tp.id for tp in test_points
            if getattr(tp, "structural_key", None) in set(audit_report.uncovered_structural_keys)
        }
        uncovered_ids |= struct_uncovered_ids

    target_ids = uncovered_ids | weak_ids
    target_tps = [tp for tp in test_points if tp.id in target_ids]
    logger.info(
        "backfill 第 %d 轮：零覆盖补 %d 个 + 假覆盖替换 %d 个（移除旧用例 %d 条），接地重生成",
        iters, len(uncovered_ids), len(weak_ids), removed,
    )

    parsed_context = state["parsed_context"]
    system_id = UUID(state["system_id"])
    document_id = UUID(state["document_id"])
    # 起始号取所有现有用例（含被移除前的全集）的最大序号，避免与保留用例撞号
    start_counter = _max_case_counter(final_cases)
    new_cases, failed = await generate_cases(
        parsed_context,
        target_tps,
        system_id,
        document_id=document_id,
        start_counter=start_counter,
    )

    merged = kept_cases + new_cases

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
    # 更新 audit_report：刷新零覆盖列表，并清空假覆盖列表（替换重做仅一轮，防回环反复）
    if audit_report is not None:
        update_fields: dict = {
            "uncovered_test_point_ids": still_uncovered,
            "weak_coverage_test_point_ids": [],
            "per_test_point_covered": len(covered_tp_ids & all_tp_ids),
        }
        # 回填可能令未覆盖规则的锚点测试点重新拿到用例 → 同步刷新规则级覆盖（gate 开时）。
        rules = state.get("rules") or []
        if settings.rule_coverage_gate_enabled and rules:
            rule_fields = compute_rule_coverage(rules, test_points, covered_tp_ids)
            update_fields.update(rule_fields)
            logger.info(
                "backfill 第 %d 轮：规则覆盖刷新 %d/%d，剩余未覆盖 %d 条",
                iters, rule_fields["covered_rules"], rule_fields["total_rules"],
                len(rule_fields["uncovered_rule_codes"]),
            )
        # 同步刷新结构化覆盖
        if settings.structural_coverage_enabled:
            struct_fields = compute_structural_coverage(test_points, covered_tp_ids)
            update_fields.update(struct_fields)
            logger.info(
                "backfill 第 %d 轮：结构化覆盖刷新 %d/%d，剩余未覆盖 %d 个 key",
                iters, struct_fields["structural_covered"], struct_fields["structural_total"],
                len(struct_fields["uncovered_structural_keys"]),
            )
        out["audit_report"] = audit_report.model_copy(update=update_fields)
    return out
