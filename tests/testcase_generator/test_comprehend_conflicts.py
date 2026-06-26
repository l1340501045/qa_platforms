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


def test_build_questions_conflict_carries_detail_and_type():
    conflicts = [SourceConflict(
        conflict_id="C-001", description="角色名称字数上限：'≤50字' vs '不限字数'",
        source_a="§5.6.1", source_a_trust_level=1, source_b="§9.2 表", source_b_trust_level=1,
        resolution="unresolved", resolution_basis="x", conflict_detail=_detail(),
    )]
    qs = cnode._build_open_questions(blind_spots=[], conflicts=conflicts, features=[], max_questions=10)
    q = qs[0]
    assert q.question_type == "conflict" and q.severity == "high"
    assert q.conflict_detail is not None
    assert "§5.6.1" in q.context and "Level 1" in q.context
    assert "未列" not in q.context and "Level 3" not in q.context


def test_build_questions_placeholder_source_safe_context():
    conflicts = [SourceConflict(
        conflict_id="C-001", description="某冲突", source_a="未列", source_a_trust_level=3,
        source_b="未列", source_b_trust_level=3, resolution="unresolved", resolution_basis="x",
        conflict_detail=None,
    )]
    qs = cnode._build_open_questions(blind_spots=[], conflicts=conflicts, features=[], max_questions=10)
    assert qs[0].question_type == "conflict"
    assert "未列" not in qs[0].context and "Level 3" not in qs[0].context


def test_to_frontend_dict_aligns_fields():
    from src.testcase_generator.schemas.comprehension_report import OpenQuestion
    q = OpenQuestion(
        question_id="Q-001", question="q", context="c", blocking=True,
        question_type="conflict", severity="high", conflict_detail=_detail(),
    )
    d = cnode._open_question_to_payload(q)
    assert d["id"] == "Q-001" and d["question_id"] == "Q-001"
    assert d["priority"] == "high"
    assert d["question_type"] == "conflict"
    assert d["conflict_detail"]["topic"] == "角色名称字数上限"
