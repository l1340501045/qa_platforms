"""澄清消解冲突（方案 A）— conflict_id 关联 / apply_clarification。"""
from __future__ import annotations

from src.testcase_generator.schemas.comprehension_report import (
    ComprehensionReport,
    OpenQuestion,
    SourceConflict,
)
from src.testcase_generator.stages.comprehend import node as cnode


def _conflict(cid="C-001", res="unresolved"):
    return SourceConflict(
        conflict_id=cid, description="角色名字数：'≤50' vs '不限'",
        source_a="§5.6.1", source_a_trust_level=1, source_b="§9.2 表", source_b_trust_level=1,
        resolution=res, resolution_basis="x",
    )


def test_build_open_questions_carries_conflict_id():
    qs = cnode._build_open_questions(
        blind_spots=[], conflicts=[_conflict()], features=[], max_questions=10
    )
    assert qs[0].question_type == "conflict"
    assert qs[0].conflict_id == "C-001"
