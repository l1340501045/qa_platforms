"""同实体门控（治概念混淆型假 conflict）单测。

承接 docs/spec/2026-06-30-conflict-entity-gate-design.md：用例对象 ≠ PRD 反驳条款对象
（如"监测链接" vs "投放链接"）→ 撤销 conflict、降级 ungrounded + conflict_entity_mismatch。
门控主力在 rubric（让 LLM 判 conflict 前过"同实体"关），后处理用 same_entity + 词法
兜底（字符集 Jaccard）防 LLM 仍误判。灰度 conflict_entity_gate_enabled，关时零回归。
"""

from __future__ import annotations


def test_case_verification_has_entity_gate_fields():
    """CaseVerification 带 3 个新字段，默认值向后兼容（不破坏既有构造）。"""
    from src.testcase_generator.schemas.test_case import CaseVerification

    # 显式构造（verdict=conflict 时填）
    cv = CaseVerification(
        conflict_subject_case="监测链接",
        conflict_subject_prd="投放链接",
        conflict_entity_mismatch=True,
    )
    assert cv.conflict_subject_case == "监测链接"
    assert cv.conflict_subject_prd == "投放链接"
    assert cv.conflict_entity_mismatch is True

    # 默认值（向后兼容）
    empty = CaseVerification()
    assert empty.conflict_subject_case == ""
    assert empty.conflict_subject_prd == ""
    assert empty.conflict_entity_mismatch is False
