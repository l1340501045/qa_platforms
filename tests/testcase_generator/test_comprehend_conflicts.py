"""质量门冲突澄清改造 — comprehend 冲突结构化 / 兜底 / 字段链路。"""
from __future__ import annotations

import pytest

from src.testcase_generator.stages.comprehend import node as cnode


def test_is_placeholder():
    for s in ["", "  ", "未列", "未知", "N/A", "n/a", "无", "null", None]:
        assert cnode._is_placeholder(s) is True
    for s in ["§5.6.1", "§9.2 表", "PRD 支付功能"]:
        assert cnode._is_placeholder(s) is False
