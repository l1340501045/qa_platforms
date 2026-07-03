"""同实体门控（治概念混淆型假 conflict）单测。

承接 docs/spec/2026-06-30-conflict-entity-gate-design.md：用例对象 ≠ PRD 反驳条款对象
（如"监测链接" vs "投放链接"）→ 撤销 conflict、降级 ungrounded + conflict_entity_mismatch。
rubric 同实体前置指令 + 后处理降级均受 conflict_entity_gate_enabled 灰度控制，关时零回归
（rubric 段落不注入、后处理不动）。后处理仅当 LLM 明确 same_entity=False 时降级，词法
Jaccard 作佐证但不覆盖 LLM 的同实体判断（防误伤真 conflict）。
"""

from __future__ import annotations


def test_case_verification_has_entity_gate_fields():
    """CaseVerification 带实体门控和审查诊断字段，默认值向后兼容（不破坏既有构造）。"""
    from src.testcase_generator.schemas.test_case import CaseVerification

    # 显式构造（verdict=conflict 时填）
    cv = CaseVerification(
        conflict_subject_case="监测链接",
        conflict_subject_prd="投放链接",
        conflict_entity_mismatch=True,
        review_issue_type="verify_uncertain",
    )
    assert cv.conflict_subject_case == "监测链接"
    assert cv.conflict_subject_prd == "投放链接"
    assert cv.conflict_entity_mismatch is True
    assert cv.review_issue_type == "verify_uncertain"

    # 默认值（向后兼容）
    empty = CaseVerification()
    assert empty.conflict_subject_case == ""
    assert empty.conflict_subject_prd == ""
    assert empty.conflict_entity_mismatch is False
    assert empty.review_issue_type is None


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
    assert res["V0"].review_issue_type == "verify_uncertain"
    assert res["V0"].conflict_subject_case == "监测链接"
    assert res["V0"].conflict_subject_prd == "投放链接"
    # rationale 前缀标注撤销原因
    assert "同实体" in res["V0"].rationale or "实体" in res["V0"].rationale


async def test_gate_lexical_does_not_override_llm_same_entity_true(monkeypatch):
    """词法不覆盖 LLM 明确的同实体判断：LLM 判 same_entity=True，即便 subject="监测链接"/"投放链接"
    字符集 Jaccard<0.5（词法判不同实体），也【不降级】——尊重 LLM 的 same_entity=True，
    防词法把 LLM 已判同实体的真 conflict 误撤。词法仅作 rationale 佐证。"""
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

    # same_entity=True → 不降级（词法不覆盖）
    assert res["V0"].verdict == "conflict"
    assert res["V0"].bucket == "to_fix"
    assert res["V0"].conflict_entity_mismatch is False
    assert res["V0"].review_issue_type == "case_wrong"


async def test_gate_same_entity_false_downgrades_even_if_lexical_same(monkeypatch):
    """LLM 明确 same_entity=False → 降级，即便词法判同实体（subject 高重叠）也尊重 LLM。
    词法仅作 rationale 佐证，不改变降级决定。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="原判：冲突",
            # subject 高重叠（词法判同实体），但 LLM 明确判不同实体
            conflict_subject_case="标题包名称字数",
            conflict_subject_prd="标题包名称长度",
            same_entity=False,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "ungrounded"
    assert res["V0"].bucket == "needs_spec"
    assert res["V0"].conflict_entity_mismatch is True
    assert res["V0"].review_issue_type == "verify_uncertain"


async def test_gate_real_conflict_with_lexical_divergence_not_downgraded(monkeypatch):
    """不误伤（GPT-3 边界）：同实体但措辞分歧大的真 conflict——LLM 正确判 same_entity=True，
    subject="标题字数上限"/"字数" 字符集 Jaccard≈0.33<0.5（词法判不同实体），但 same_entity=True
    → 不降级。这正是"词法会误伤"的边界，新逻辑（词法不覆盖）守住不误撤。"""
    from src.testcase_generator.stages.verify import verifier as vmod

    verdicts = [
        vmod._CaseVerdict(
            case_id="V0",
            verdict="conflict",
            rationale="标题字数上限 50 vs 30",
            conflict_subject_case="标题字数上限",
            conflict_subject_prd="字数",
            same_entity=True,
        )
    ]
    res = await _run_verify(monkeypatch, verdicts, gate_on=True)

    assert res["V0"].verdict == "conflict"
    assert res["V0"].bucket == "to_fix"
    assert res["V0"].conflict_entity_mismatch is False


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


async def test_gate_off_does_not_inject_rubric_instruction(monkeypatch):
    """GPT-1 验证盲区补强：关门控时 CONFLICT_ENTITY_GATE_INSTRUCTION 不注入 system_prompt
    （rubric 层真·零回归），开时才注入。守"关时逐字节现状"在 LLM 提示层也成立。"""
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection,
        VerifyCase,
        verify_cases,
    )

    seen_prompts: list[str] = []

    class _FakeClient:
        async def generate_structured(self, *, system_prompt, **kw):
            seen_prompts.append(system_prompt)
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(case_id="V0", verdict="grounded", rationale="r"),
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    cases = [VerifyCase(case_id="V0", feature_id="F1", title="t")]
    sections = {"F1": [PrdSection("§5.8.3", "投放链接单选", "§5.8.3")]}

    # 关：同实体前置指令不注入
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    await verify_cases(cases, sections)
    assert "同实体前置" not in seen_prompts[-1]

    # 开：同实体前置指令注入
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", True)
    await verify_cases(cases, sections)
    assert "同实体前置" in seen_prompts[-1]


# ─── Chunk 4: 已知 §7.2 fixture 端到端（开关因果链）──────────────────────────


async def test_section72_fixture_end_to_end(monkeypatch):
    """真实 §7.2 场景端到端：监测链接用例被 verify 拿投放链接反驳（不同实体），
    与真 conflict（标题包字数）、grounded 用例混跑——门控开 → §7.2 型降级、真 conflict 与
    grounded 不动；门控关 → 全部逐字节保持 conflict（开关因果链）。"""
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection,
        VerifyCase,
        verify_cases,
    )

    # §7.2 监测链接用例（自动绑定预置 hash），PRD §5.8.3 给的是投放链接单选——不同实体
    # 真 conflict：标题包名称字数 50 vs 30（同实体）
    # grounded：正常有支撑
    cases = [
        VerifyCase(case_id="S72", feature_id="F7.2", title="监测链接自动绑定预置hash"),
        VerifyCase(case_id="REAL", feature_id="F5.6", title="标题包名称字数50可存"),
        VerifyCase(case_id="GRD", feature_id="F5.8", title="投放链接单选正常"),
    ]
    sections = {
        "F7.2": [PrdSection("§7.1.1", "监测链接自动绑定预置 hash", "§7.1.1")],
        "F5.6": [PrdSection("§5.6.1", "标题包名称 ≤ 50 字", "§5.6.1")],
        "F5.8": [PrdSection("§5.8.3", "投放链接单选", "§5.8.3")],
    }
    verdicts = [
        vmod._CaseVerdict(
            case_id="S72",
            verdict="conflict",
            rationale="原判：与投放链接单选冲突",
            conflict_subject_case="监测链接",
            conflict_subject_prd="投放链接",
            same_entity=False,
        ),
        vmod._CaseVerdict(
            case_id="REAL",
            verdict="conflict",
            rationale="标题包名称字数 50 vs 30",
            conflict_subject_case="标题包名称字数",
            conflict_subject_prd="标题包名称字数",
            same_entity=True,
        ),
        vmod._CaseVerdict(case_id="GRD", verdict="grounded", rationale="有支撑"),
    ]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(verdicts=verdicts)

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())

    # ── 门控开：§7.2 型降级，真 conflict 与 grounded 不动 ──────────────────
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", True)
    res_on = await verify_cases(cases, sections)
    assert res_on["S72"].verdict == "ungrounded"
    assert res_on["S72"].bucket == "needs_spec"
    assert res_on["S72"].conflict_entity_mismatch is True
    assert res_on["REAL"].verdict == "conflict"  # 真 conflict 不误撤
    assert res_on["REAL"].bucket == "to_fix"
    assert res_on["REAL"].conflict_entity_mismatch is False
    assert res_on["GRD"].verdict == "grounded"
    assert res_on["GRD"].bucket == "main"

    # ── 门控关：§7.2 型 conflict 逐字节保持（零回归）────────────────────
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    res_off = await verify_cases(cases, sections)
    assert res_off["S72"].verdict == "conflict"
    assert res_off["S72"].bucket == "to_fix"
    assert res_off["S72"].conflict_entity_mismatch is False
    assert res_off["REAL"].verdict == "conflict"
    assert res_off["GRD"].verdict == "grounded"
