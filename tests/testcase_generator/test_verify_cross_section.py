"""verify 跨族 + 跨条款矛盾扫描 单测。"""

from __future__ import annotations

import json

import pytest

from src.testcase_generator.services.llm_client import LLMClient


def test_case_verification_has_cross_section_fields():
    from src.testcase_generator.schemas.test_case import CaseVerification, CrossSectionConflictRef

    cv = CaseVerification(
        verdict="grounded",
        bucket="main",
        cross_section_conflict=True,
        conflicting_refs=[CrossSectionConflictRef(
            ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2首表", quote_b="不限字数",
        )],
    )
    assert cv.cross_section_conflict is True
    assert cv.conflicting_refs[0].ref_b == "§9.2首表"
    # 默认值（向后兼容）
    assert CaseVerification().cross_section_conflict is False
    assert CaseVerification().conflicting_refs == []


async def test_verify_cases_attaches_and_summarizes_conflict(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import (
        PrdSection, VerifyCase, summarize, verify_cases,
    )

    class _FakeOut:
        def __init__(self):
            self.verdicts = [vmod._CaseVerdict(
                case_id="V0", verdict="grounded", rationale="r",
                cross_section_conflict=True,
                conflicting_refs=[vmod._ConflictRef(
                    ref_a="§5.6.1", quote_a="≤50字", ref_b="§9.2", quote_b="不限字数")],
            )]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return _FakeOut()

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())

    cases = [VerifyCase(case_id="V0", feature_id="F1", title="标题包名50字可存")]
    sections = {"F1": [PrdSection("§5.6.1", "≤50字", "§5.6.1"),
                       PrdSection("§9.2", "不限字数", "§9.2")]}
    res = await verify_cases(cases, sections)
    assert res["V0"].cross_section_conflict is True
    assert res["V0"].verdict == "grounded"  # 不被改写

    summ = summarize(res)
    assert summ["cross_section_conflicts"] == 1
    assert len(summ["prd_conflict_list"]) == 1


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
