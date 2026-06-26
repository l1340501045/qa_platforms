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


def _report(conflicts, coverage=0.9):
    oqs = [
        OpenQuestion(question_id=f"Q-{i+1:03d}", question="q", context="c", blocking=True,
                     question_type="conflict", severity="high", conflict_id=c.conflict_id)
        for i, c in enumerate(conflicts)
    ]
    return ComprehensionReport(
        gate_result="NO_GO", understanding_coverage=coverage,
        feature_matrix=[], conflicts=conflicts, blind_spots=[], open_questions=oqs,
    )


async def test_apply_resolves_all_and_releases_nested_shape():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {
        "comprehension_report": report,
        "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "以 §5.6.1 为准"}]},
    }
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")
    assert out["open_questions"] == []
    assert out["clarification_rounds"] == 1
    assert "用户裁决" in out["comprehension_report"].conflicts[0].resolution


async def test_apply_accepts_bare_list_shape():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {"comprehension_report": report,
             "clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")


async def test_apply_partial_keeps_remaining_no_blind_spots():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001"), _conflict("C-002")])
    state = {"comprehension_report": report,
             "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}}
    out = await apply_clarification_node(state)
    assert out["gate_result"] == "NO_GO"
    assert len(out["open_questions"]) == 1


async def test_apply_round_limit_force_release():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")])
    state = {"comprehension_report": report, "clarification_rounds": 3,
             "clarification_answers": {"clarification_answers": []}}
    out = await apply_clarification_node(state)
    assert out["gate_result"] in ("GO", "CONDITIONAL")
    assert out["comprehension_report"].conflicts[0].resolution_basis == "forced_release"


async def test_apply_low_coverage_still_releases_when_no_conflict():
    from src.testcase_generator.stages.comprehend.apply_clarification import apply_clarification_node
    report = _report([_conflict("C-001")], coverage=0.1)
    state = {"comprehension_report": report,
             "clarification_answers": {"clarification_answers": [{"question_id": "Q-001", "answer": "x"}]}}
    out = await apply_clarification_node(state)
    assert out["gate_result"] == "CONDITIONAL"


def test_apply_module_does_not_import_llm():
    import inspect
    from src.testcase_generator.stages.comprehend import apply_clarification as mod
    assert "get_llm_client" not in inspect.getsource(mod)
