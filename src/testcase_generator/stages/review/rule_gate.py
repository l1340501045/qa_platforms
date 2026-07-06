"""规则级覆盖判定（结构性闸）——review 与 backfill 共用。

规则「被覆盖」= 其锚点测试点（携 rule_id）至少 1 条用例。确定性、无额外 LLM。
返回的 dict 字段名与 AuditReport 对齐，便于 AuditReport(**fields) / model_copy(update=fields)。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.testcase_generator.schemas.test_point import TestPointSchema

# gate 关或无规则时的默认值（与历史行为一致）
DEFAULT_RULE_COVERAGE = {
    "total_rules": 0,
    "covered_rules": 0,
    "rule_coverage": 1.0,
    "uncovered_rule_codes": [],
}


# structural 覆盖 gate 关或无结构化点时的默认值
DEFAULT_STRUCTURAL_COVERAGE = {
    "structural_total": 0,
    "structural_covered": 0,
    "structural_coverage": 1.0,
    "uncovered_structural_keys": [],
}


def compute_structural_coverage(
    test_points: list[TestPointSchema],
    covered_tp_ids: Iterable[str],
) -> dict:
    """按 structural_key 计算结构化覆盖。"""
    covered_set = set(covered_tp_ids)
    struct = [tp for tp in test_points if getattr(tp, "structural_type", None)]
    total = len(struct)
    covered_keys = {tp.structural_key for tp in struct if tp.id in covered_set}
    uncovered = sorted(
        {tp.structural_key for tp in struct if tp.id not in covered_set}
        - {None}
    )
    return {
        "structural_total": total,
        "structural_covered": len(covered_keys - {None}),
        "structural_coverage": (len(covered_keys - {None}) / total) if total else 1.0,
        "uncovered_structural_keys": uncovered,
    }


def compute_rule_coverage(
    rules: list[dict],
    test_points: list[TestPointSchema],
    covered_tp_ids: Iterable[str],
) -> dict:
    """按锚点链路计算规则覆盖。

    Args:
        rules: 规则台账（含 rule_code）。
        test_points: 全部测试点（锚点带 rule_id）。
        covered_tp_ids: 有 >=1 用例的测试点 ID 集合。
    """
    covered_set = set(covered_tp_ids)
    all_rule_codes = {r.get("rule_code") for r in rules if r.get("rule_code")}
    rule_to_tp_ids: dict[str, list[str]] = defaultdict(list)
    for tp in test_points:
        if tp.rule_id:
            rule_to_tp_ids[tp.rule_id].append(tp.id)
    covered_codes = {
        code
        for code, tp_ids in rule_to_tp_ids.items()
        if any(t in covered_set for t in tp_ids)
    }
    total = len(all_rule_codes)
    covered = len(all_rule_codes & covered_codes)
    return {
        "total_rules": total,
        "covered_rules": covered,
        "rule_coverage": covered / total if total else 1.0,
        "uncovered_rule_codes": sorted(all_rule_codes - covered_codes),
    }
