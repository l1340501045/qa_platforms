"""质量门冲突澄清改造 — comprehend 冲突结构化 / 兜底 / 字段链路。"""
from __future__ import annotations

import pytest

from src.testcase_generator.schemas.comprehension_report import (
    ConflictDetail,
    ConflictSide,
    SourceConflict,
)
from src.testcase_generator.stages.comprehend import node as cnode
from src.testcase_generator.stages.comprehend.blind_spot_detector import BlindSpotDetector


def test_is_placeholder():
    for s in ["", "  ", "未列", "未知", "N/A", "n/a", "无", "null", None]:
        assert cnode._is_placeholder(s) is True
    for s in ["§5.6.1", "§9.2 表", "PRD 支付功能"]:
        assert cnode._is_placeholder(s) is False


def _detail(loc_a="§5.6.1", loc_b="§9.2 表"):
    return ConflictDetail(
        topic="角色名称字数上限",
        side_a=ConflictSide(location=loc_a, statement="必填 / ≤50字", trust_level=1),
        side_b=ConflictSide(location=loc_b, statement="必填 / 不限字数", trust_level=1),
        recommendation="side_a",
        recommendation_reason="角色名是展示字段",
    )


def test_merge_structured_conflict_maps_and_unresolved():
    out = cnode._merge_conflicts([_detail()], features=[], sources=[], detector=BlindSpotDetector())
    assert len(out) == 1
    c = out[0]
    assert c.source_a == "§5.6.1" and c.source_b == "§9.2 表"
    assert c.source_a_trust_level == 1 and c.source_b_trust_level == 1
    assert c.resolution == "unresolved"
    assert c.conflict_detail is not None and c.conflict_detail.topic == "角色名称字数上限"


def test_merge_placeholder_location_degrades_detail():
    out = cnode._merge_conflicts([_detail(loc_a="未列", loc_b="")], features=[], sources=[], detector=BlindSpotDetector())
    assert out[0].conflict_detail is None
    assert out[0].resolution == "unresolved"
