"""Gate NO_GO 澄清恢复 — 基于首次 report 消解冲突，不重跑 LLM（断死循环，方案 A）。"""
from __future__ import annotations

import logging

from src.testcase_generator.schemas.comprehension_report import ComprehensionReport
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.comprehend.gate import (
    GO_THRESHOLD,
    MAX_CLARIFICATION_ROUNDS,
    MAX_OPEN_QUESTIONS,
)
from src.testcase_generator.stages.comprehend.node import (
    _build_open_questions,
    _open_question_to_payload,
)

logger = logging.getLogger(__name__)


async def apply_clarification_node(state: PipelineState) -> dict:
    """按用户裁决消解首次 report 的对应冲突，重判 gate。全程不调 LLM。"""
    report: ComprehensionReport = state["comprehension_report"]
    rounds = state.get("clarification_rounds", 0) + 1

    # B1：clarification_answers 双层嵌套 → 入口归一化
    raw = state.get("clarification_answers") or []
    answers = raw.get("clarification_answers", []) if isinstance(raw, dict) else raw

    qid_to_cid = {q.question_id: q.conflict_id for q in report.open_questions if q.conflict_id}
    conflicts_by_id = {c.conflict_id: c for c in report.conflicts}

    for ans in answers:
        if not isinstance(ans, dict):
            continue
        cid = qid_to_cid.get(ans.get("question_id"))
        if not cid:
            continue
        conflict = conflicts_by_id.get(cid)
        if conflict is not None:
            conflict.resolution = f"用户裁决：{ans.get('answer', '')}"
            conflict.resolution_basis = "user_clarification"

    remaining = [c for c in report.conflicts if c.resolution == "unresolved"]

    if remaining and rounds < MAX_CLARIFICATION_ROUNDS:
        gate_result = "NO_GO"
        open_questions = _build_open_questions(
            blind_spots=[], conflicts=remaining, features=[], max_questions=MAX_OPEN_QUESTIONS
        )
    else:
        if remaining:
            for c in remaining:
                c.resolution = "超澄清轮数上限，强制放行"
                c.resolution_basis = "forced_release"
        gate_result = "GO" if report.understanding_coverage >= GO_THRESHOLD else "CONDITIONAL"
        open_questions = []

    report.gate_result = gate_result
    report.open_questions = open_questions

    logger.info(
        "apply_clarification: round=%d, remaining=%d, gate=%s", rounds, len(remaining), gate_result
    )

    return {
        "comprehension_report": report,
        "gate_result": gate_result,
        "open_questions": [_open_question_to_payload(q) for q in open_questions],
        "clarification_rounds": rounds,
        "current_stage": "comprehend",
    }
