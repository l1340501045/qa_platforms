"""T021: Gate 质量门 — GO / CONDITIONAL / NO_GO"""

from __future__ import annotations

from typing import Literal

import yaml
from pathlib import Path

from src.testcase_generator.schemas.comprehension_report import ComprehensionReport

# 从配置读取阈值（硬约束#4：不硬编码）
_config_path = Path(__file__).parent.parent.parent / "config" / "trust_order.yaml"
with open(_config_path) as _f:
    _gate_config = yaml.safe_load(_f)["gate_config"]

GO_THRESHOLD: float = _gate_config["go_threshold"]  # 0.8
NO_GO_THRESHOLD: float = _gate_config["no_go_threshold"]  # 0.6
MAX_OPEN_QUESTIONS: int = _gate_config.get("max_open_questions", 10)


def evaluate_gate(
    comprehension_report: ComprehensionReport,
) -> Literal["GO", "CONDITIONAL", "NO_GO"]:
    """评估 Gate 结果

    判定规则：
    - GO: coverage >= go_threshold 且无同级未解决冲突
    - NO_GO: coverage < no_go_threshold 或存在同级冲突（unresolved）
    - CONDITIONAL: 其余情况（60% <= coverage < 80%，无同级冲突）

    Args:
        comprehension_report: 理解阶段产出的报告

    Returns:
        "GO" | "CONDITIONAL" | "NO_GO"
    """
    coverage = comprehension_report.understanding_coverage

    # 同级冲突 = resolution 为 "unresolved" 的冲突
    has_same_level_conflicts = any(c.resolution == "unresolved" for c in comprehension_report.conflicts)

    if has_same_level_conflicts:
        return "NO_GO"  # 同级冲突必须人工裁决

    if coverage >= GO_THRESHOLD:
        return "GO"

    if coverage < NO_GO_THRESHOLD:
        return "NO_GO"

    return "CONDITIONAL"
