"""优先级 risk 模型单测。"""
from __future__ import annotations

import pytest

from src.testcase_generator.stages.test_points.node import risk_to_priority


@pytest.mark.parametrize("likelihood,impact,expected", [
    (3, 3, "P0"), (3, 2, "P0"), (2, 3, "P0"),   # risk 9/6/6
    (2, 2, "P1"), (3, 1, "P1"), (1, 3, "P1"),   # risk 4/3/3
    (1, 2, "P2"), (2, 1, "P2"), (1, 1, "P2"),   # risk 2/2/1
])
def test_risk_to_priority(likelihood, impact, expected):
    assert risk_to_priority(likelihood, impact) == expected


def test_risk_to_priority_clamps_out_of_range():
    assert risk_to_priority(0, 9) in {"P0", "P1", "P2"}
