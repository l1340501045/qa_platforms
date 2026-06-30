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


# ─── _same_entity 词法兜底（纯函数）────────────────────────────────────────


def test_same_entity_jaccard_not_common_token():
    """核心护栏：禁止退化为"有无公共 token"——"监测链接"∩"投放链接"={链,接} 非空，
    但字符集 Jaccard=2/6≈0.33<0.5 → 须判不同实体（False）。"""
    from src.testcase_generator.stages.verify.verifier import _same_entity

    # 监测链接 vs 投放链接：交集 {链,接}，并集 {监,测,链,接,投,放} =6 → 0.33 < 0.5
    assert _same_entity("监测链接", "投放链接") is False
    # 共享"链接"二字但限定词差异大 → 仍不同实体（防公共 token 退化）
    assert _same_entity("下载链接", "上传链接") is False


def test_same_entity_identical_or_high_overlap():
    """真 conflict（同实体）：subject 完全相同 → Jaccard=1.0 → True（不撤）。"""
    from src.testcase_generator.stages.verify.verifier import _same_entity

    assert _same_entity("标题包名称字数", "标题包名称字数") is True
    # 高重叠（仅差一两字）→ Jaccard>=0.5 → 同实体
    assert _same_entity("标题包名称字数", "标题包名称长度") is True


def test_same_entity_empty_is_conservative_true():
    """任一为空串 → 返回 True（无法判定、保守不撤，防误伤真 conflict）。"""
    from src.testcase_generator.stages.verify.verifier import _same_entity

    assert _same_entity("", "投放链接") is True
    assert _same_entity("监测链接", "") is True
    assert _same_entity("", "") is True


def test_same_entity_normalization():
    """归一化去标点/空格/数字、小写后取字符集——'监测链接' vs '监测 链接！' 仍同实体。"""
    from src.testcase_generator.stages.verify.verifier import _same_entity

    assert _same_entity("监测链接", "监测 链接！") is True
    # 大小写/标点不影响
    assert _same_entity("TrackingURL", "tracking url") is True


# ─── 后处理门控（verify_cases 端到端，mock LLM）─────────────────────────────


async def _run_verify(monkeypatch, verdicts, gate_on):
    """构造 mock LLM 产出给定 verdicts，跑 verify_cases，返回 {case_id: CaseVerification}。"""
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection,
        VerifyCase,
        verify_cases,
    )

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(verdicts=verdicts)

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", gate_on)

    cases = [VerifyCase(case_id=v.case_id, feature_id="F1", title="t") for v in verdicts]
    sections = {"F1": [PrdSection("§5.8.3", "投放链接单选", "§5.8.3")]}
    return await verify_cases(cases, sections)


async def test_gate_downgrades_cross_entity_conflict(monkeypatch):
    """§7.2 型：LLM 明确 same_entity=False → 门控开 → verdict conflict 降级 ungrounded、
    bucket=needs_spec、conflict_entity_mismatch=True。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="原判：监测链接与投放链接冲突",
            conflict_subject_case="监测链接",
            conflict_subject_prd="投放链接",
            same_entity=False,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "ungrounded"
    assert res["V0"].bucket == "needs_spec"
    assert res["V0"].conflict_entity_mismatch is True
    assert res["V0"].conflict_subject_case == "监测链接"
    assert res["V0"].conflict_subject_prd == "投放链接"
    # rationale 前缀标注撤销原因
    assert "同实体" in res["V0"].rationale or "实体" in res["V0"].rationale


async def test_gate_lexical_fallback_overrides_llm_same_entity_true(monkeypatch):
    """词法兜底：LLM 误填 same_entity=True，但 subject="监测链接"/"投放链接"
    字符集 Jaccard<0.5 → 仍降级（防 LLM 错判同实体）。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="原判：冲突",
            conflict_subject_case="监测链接",
            conflict_subject_prd="投放链接",
            same_entity=True,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "ungrounded"
    assert res["V0"].bucket == "needs_spec"
    assert res["V0"].conflict_entity_mismatch is True


async def test_gate_does_not_downgrade_real_conflict(monkeypatch):
    """不误伤：真 conflict（同实体 subject 完全相同、same_entity=True）→ 不降级，
    verdict 仍 conflict、bucket 仍 to_fix、conflict_entity_mismatch=False。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="标题包名称字数 50 vs 30 冲突",
            conflict_subject_case="标题包名称字数",
            conflict_subject_prd="标题包名称字数",
            same_entity=True,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "conflict"
    assert res["V0"].bucket == "to_fix"
    assert res["V0"].conflict_entity_mismatch is False


async def test_gate_off_is_byte_identical(monkeypatch):
    """关门控（conflict_entity_gate_enabled=False）→ conflict 逐字节不动、不降级、不标 mismatch。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    # 即便 LLM 明确 same_entity=False，关门控时也不动
    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="原判",
            conflict_subject_case="监测链接",
            conflict_subject_prd="投放链接",
            same_entity=False,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=False)

    assert res["V0"].verdict == "conflict"
    assert res["V0"].bucket == "to_fix"
    assert res["V0"].conflict_entity_mismatch is False


async def test_gate_not_triggered_for_non_conflict_verdict(monkeypatch):
    """非 conflict verdict（grounded/ungrounded/undefined）→ 门控不介入，subject 仍透传落库。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="grounded",
            rationale="有支撑",
            conflict_subject_case="监测链接",
            conflict_subject_prd="投放链接",
            same_entity=False,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "grounded"
    assert res["V0"].bucket == "main"
    assert res["V0"].conflict_entity_mismatch is False
    # subject 仍透传（落库观测）
    assert res["V0"].conflict_subject_case == "监测链接"
