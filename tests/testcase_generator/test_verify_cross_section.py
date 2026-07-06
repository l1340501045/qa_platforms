"""verify 跨族 + 跨条款矛盾扫描 单测。"""

from __future__ import annotations

import json

from src.testcase_generator.services.llm_client import LLMClient


def test_case_verification_has_cross_section_fields():
    from src.testcase_generator.schemas.test_case import CaseVerification, CrossSectionConflictRef

    cv = CaseVerification(
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=[
            CrossSectionConflictRef(
                ref_a="§5.6.1",
                quote_a="≤50字",
                ref_b="§9.2首表",
                quote_b="不限字数",
            )
        ],
    )
    assert cv.cross_section_conflict is True
    assert cv.conflicting_refs[0].ref_b == "§9.2首表"
    # 默认值（向后兼容）
    assert CaseVerification().cross_section_conflict is False
    assert CaseVerification().conflicting_refs == []


async def test_verify_cases_attaches_and_summarizes_conflict(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection,
        VerifyCase,
        summarize,
        verify_cases,
    )

    class _FakeOut:
        def __init__(self):
            self.verdicts = [
                vmod._CaseVerdict(
                    case_id="V0",
                    verdict="grounded",
                    rationale="r",
                    cross_section_conflict=True,
                    conflicting_refs=[
                        vmod._ConflictRef(ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")
                    ],
                )
            ]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return _FakeOut()

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())

    cases = [VerifyCase(case_id="V0", feature_id="F1", title="标题包名50字可存")]
    sections = {"F1": [PrdSection("§5.6.1", "≤50字", "§5.6.1"), PrdSection("§9.2", "不限字数", "§9.2")]}
    res = await verify_cases(cases, sections)
    assert res["V0"].cross_section_conflict is True
    assert res["V0"].verdict == "grounded"  # 不被改写

    summ = summarize(res)
    assert summ["cross_section_conflicts"] == 1
    assert len(summ["prd_conflict_list"]) == 1


async def test_known_prd_conflicts_recalled_end_to_end(monkeypatch):
    """审查已知的 3 对 PRD 矛盾：开关开 → 指令注入 → verify_cases 召回 cross_section_conflict。"""
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection,
        VerifyCase,
        summarize,
        verify_cases,
    )

    known = [
        ("F1", "标题包名称恰好50字可保存", "§5.6.1", "标题包名称 ≤ 50 字", "§9.2", "标题包包名 不限字数"),
        ("F2", "包名含emoji被自动剔除", "§5.0.3", "emoji 自动剔除并提示", "§5.6.1", "emoji 保存时弹错"),
        ("F3", "同投手定向包重名禁止保存", "§5.0.5", "重名禁止保存", "§5.7.1", "同投手不重名 mock 仅弱校验"),
    ]
    cases, sections = [], {}
    for i, (fid, title, ra, qa, rb, qb) in enumerate(known):
        cases.append(VerifyCase(case_id=f"V{i}", feature_id=fid, title=title))
        sections[fid] = [PrdSection(ra, qa, ra), PrdSection(rb, qb, rb)]

    class _FakeClient:
        async def generate_structured(self, *, system_prompt, user_content, output_schema, **kw):
            inject = "跨条款矛盾扫描" in system_prompt
            payload = json.loads(user_content)
            verdicts = []
            for tc in payload["test_cases"]:
                secs = payload["prd_sections"]
                verdicts.append(
                    vmod._CaseVerdict(
                        case_id=tc["case_id"],
                        verdict="grounded",
                        cross_section_conflict=inject,
                        conflicting_refs=[
                            vmod._ConflictRef(
                                ref_a=secs[0]["source_ref"],
                                quote_a=secs[0]["content"],
                                ref_b=secs[1]["source_ref"],
                                quote_b=secs[1]["content"],
                            )
                        ]
                        if inject
                        else [],
                    )
                )
            return vmod._VerifyLLMOutput(verdicts=verdicts)

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", True)

    res = await verify_cases(cases, sections)
    assert sum(1 for v in res.values() if v.cross_section_conflict) == 3
    assert len(summarize(res)["prd_conflict_list"]) == 3

    # 对照：开关关 → 指令不注入 → 召回 0（验证因果链）
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    res0 = await verify_cases(cases, sections)
    assert sum(1 for v in res0.values() if v.cross_section_conflict) == 0


def test_summarize_dedups_same_conflict_pair_and_counts():
    """同一对矛盾被 2 个 case 命中 → 合并为 1 条、case_count=2；对称 ref 顺序正确去重。"""
    from src.testcase_generator.schemas.test_case import CaseVerification, CrossSectionConflictRef
    from src.testcase_generator.stages.verify.verifier import summarize

    pair = [CrossSectionConflictRef(ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")]
    pair_rev = [CrossSectionConflictRef(ref_a="§9.2", quote_a="不限字数", ref_b="§5.6.1", quote_b="≤50字")]
    cv = lambda refs: CaseVerification(  # noqa: E731
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=refs,
    )
    res = {"V0": cv(pair), "V1": cv(pair_rev)}
    summ = summarize(res)
    assert summ["cross_section_conflicts"] == 2
    assert len(summ["prd_conflict_list"]) == 1
    assert summ["prd_conflict_list"][0]["case_count"] == 2


def test_conflict_true_but_no_refs_treated_as_false():
    """LLM 标 conflict=True 但漏给 refs → 回挂时不采信（defensive）。"""
    from src.testcase_generator.schemas.test_case import CaseVerification
    from src.testcase_generator.stages.verify.verifier import summarize

    res = {
        "V0": CaseVerification(verdict="grounded", bucket="main", cross_section_conflict=True, conflicting_refs=[]),
    }
    summ = summarize(res)
    # cross_section_conflict=True 但 conflicting_refs=[] 的 case 仍被 summarize 计入
    # （防御在回挂层：verifier 回挂时已把无 refs 的标为 False，这里测 summarize 对已入库数据的兼容）
    assert summ["cross_section_conflicts"] == 1
    assert summ["prd_conflict_list"] == []


async def test_generate_structured_passes_explicit_model(monkeypatch):
    """传入 model 时，_call 必须收到该 model（而非 primary）。"""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    client = LLMClient.__new__(LLMClient)  # 跳过 __init__ 避免连真网关
    client.primary_model = "claude-primary"
    client._json_mode = False

    seen = {}

    async def fake_call(model, system_prompt, user_content, output_schema, temperature, images=None):
        seen["model"] = model
        return _Out(ok=True)

    monkeypatch.setattr(client, "_call", fake_call)

    await client.generate_structured("sys", "usr", _Out, model="deepseek-x")
    assert seen["model"] == "deepseek-x"

    await client.generate_structured("sys", "usr", _Out)  # 不传 → 回退 primary
    assert seen["model"] == "claude-primary"
