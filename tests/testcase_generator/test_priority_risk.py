"""优先级 risk 模型单测。"""
from __future__ import annotations

import pytest

from src.testcase_generator.stages.test_points.node import GeneratedTestPoint, risk_to_priority


@pytest.mark.parametrize("likelihood,impact,expected", [
    (3, 3, "P0"), (3, 2, "P0"), (2, 3, "P0"),   # risk 9/6/6
    (2, 2, "P1"), (3, 1, "P1"), (1, 3, "P1"),   # risk 4/3/3
    (1, 2, "P2"), (2, 1, "P2"), (1, 1, "P2"),   # risk 2/2/1
])
def test_risk_to_priority(likelihood, impact, expected):
    assert risk_to_priority(likelihood, impact) == expected


@pytest.mark.parametrize("likelihood,impact,expected", [
    (0, 9, "P1"),   # clamp(0)=1, clamp(9)=3 → risk=3
    (5, 5, "P0"),   # clamp(5)=3, clamp(5)=3 → risk=9
    (-1, 2, "P2"),  # clamp(-1)=1 → risk=2
])
def test_risk_to_priority_clamps_out_of_range(likelihood, impact, expected):
    assert risk_to_priority(likelihood, impact) == expected


def test_generated_test_point_accepts_out_of_range():
    """LLM 越界值不应触发 ValidationError，由 _clamp 兜底。"""
    gtp = GeneratedTestPoint(
        feature_id="F-001",
        dimension="boundary_value",
        description="测试越界",
        likelihood=5,
        impact=0,
    )
    assert gtp.likelihood == 5
    assert gtp.impact == 0
    assert risk_to_priority(gtp.likelihood, gtp.impact) == "P1"  # clamp(5)=3, clamp(0)=1 → 3
