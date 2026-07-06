"""规则锚点测试点 —— 把规则台账确定性地转成「每条规则 1 个带 rule_id 的锚点测试点」。

设计取舍（相对 plan 的 LLM 方案）：规则本身已是「原子、可验证」的陈述，故确定性 1:1 生成锚点，
不再额外打 LLM（更省、更稳、可复现，规避长输出 JSON 不稳定）。breadth（正常/边界/异常等）仍由
维度驱动路径补足；write_cases 也会把单个锚点测试点展开成多条具体用例。

锚点测试点按「章节号/标题 token 就近匹配」挂到现有 feature，以复用 write_cases 的按 feature
上下文注入（规则文本本身也进描述，且 write_cases 会注入全局/跨章节上下文兜底）。
"""

from __future__ import annotations

import re

from src.testcase_generator.schemas.parsed_context import FeatureItem
from src.testcase_generator.schemas.test_point import TestPointSchema

_NUM = re.compile(r"\d+(?:\.\d+)*")
_CJK = re.compile(r"[\u4e00-\u9fff]{2,}")

# 规则类型 → (主维度标签, 默认优先级)
_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "权限": ("access_control", "P0"),
    "功能": ("functional_correctness", "P0"),
    "校验": ("format_validation", "P1"),
    "状态": ("state_transition", "P1"),
    "边界": ("boundary_value", "P1"),
    "数据": ("data_calculation", "P1"),
    "联动": ("cross_system", "P1"),
}


def _tokenize(text: str) -> set[str]:
    """章节号（含层级前缀）+ CJK n-gram，作为就近匹配信号。"""
    toks: set[str] = set()
    for m in _NUM.findall(text or ""):
        parts = m.split(".")
        for i in range(1, len(parts) + 1):
            toks.add(".".join(parts[:i]))
    for run in _CJK.findall(text or ""):
        if len(run) <= 4:
            toks.add(run)
        else:
            toks.update(run[i : i + 2] for i in range(len(run) - 1))
    return toks


def match_feature_for_rule(module: str, features: list[FeatureItem]) -> str:
    """把规则的来源模块就近匹配到一个 feature_id。

    优先按章节号/标题 token 重叠取最高分；全无重叠则回退首个 feature（保证有上下文、不丢规则）；
    无任何 feature 时返回空串（write_cases 走 PRD 通用上下文分支）。
    """
    if not features:
        return ""
    mod_tokens = _tokenize(module)
    best_id = features[0].id
    best_score = 0
    for f in features:
        score = len(mod_tokens & _tokenize(f.name))
        if score > best_score:
            best_score = score
            best_id = f.id
    return best_id


def build_rule_anchored_test_points(
    rules: list[dict], features: list[FeatureItem], start_idx: int
) -> list[TestPointSchema]:
    """每条规则确定性产出 1 个带 rule_id 的锚点测试点。

    Args:
        rules: 规则台账（list[dict]，每条含 rule_code/module/rule/category/source_quote）。
        features: parsed_context.features，用于就近匹配。
        start_idx: 测试点编号起始（接在维度驱动测试点之后，避免撞号）。
    """
    anchors: list[TestPointSchema] = []
    for r in rules:
        rule_code = r.get("rule_code")
        if not rule_code:
            continue
        category = r.get("category", "")
        dimension, priority = _CATEGORY_MAP.get(category, ("functional_correctness", "P1"))
        module = r.get("module", "")
        feature_id = match_feature_for_rule(module, features)
        idx = start_idx + len(anchors) + 1
        derived: list[str] = []
        if module:
            derived.append(module)
        if r.get("source_quote"):
            derived.append(r["source_quote"])
        anchors.append(
            TestPointSchema(
                id=f"TP-{idx:03d}",
                feature_id=feature_id,
                dimension=dimension,
                description=r.get("rule", ""),
                priority=priority,  # type: ignore[arg-type]
                derived_from=derived,
                applicable_dimensions=[dimension],
                rule_id=rule_code,
            )
        )
    return anchors
