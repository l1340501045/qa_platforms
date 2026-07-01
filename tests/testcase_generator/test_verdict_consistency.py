"""verdict 同构一致化与 conflict 复判测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.testcase_generator.schemas.test_case import CaseVerification
from src.testcase_generator.stages.verify.verifier import VerifyCase, reconcile_verdicts


def _case(case_id: str, *, feature_id: str = "F1", title: str | None = None) -> VerifyCase:
    return VerifyCase(case_id=case_id, feature_id=feature_id, title=title or "标题包名称字数边界校验")


def _verification(
    verdict: str,
    *,
    mismatch: bool = False,
    rationale: str = "原判理由",
) -> CaseVerification:
    bucket = {
        "grounded": "main",
        "conflict": "to_fix",
        "ungrounded": "needs_spec",
        "undefined": "needs_spec",
    }[verdict]
    return CaseVerification(
        verdict=verdict,
        bucket=bucket,
        rationale=rationale,
        conflict_entity_mismatch=mismatch,
    )


def test_reconcile_verdicts_unifies_highly_similar_cases_by_majority():
    cases = [
        _case("C1", title="标题包名称字数边界校验01"),
        _case("C2", title="标题包名称字数边界校验02"),
        _case("C3", title="标题包名称字数边界校验03"),
    ]
    results = {
        "C1": _verification("grounded"),
        "C2": _verification("grounded"),
        "C3": _verification("conflict"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    assert {item.verdict for item in reconciled.values()} == {"grounded"}
    assert {item.bucket for item in reconciled.values()} == {"main"}
    assert "同构一致化" in reconciled["C3"].rationale


def test_reconcile_verdicts_breaks_ties_by_stricter_verdict():
    cases = [
        _case("C1", title="标题包名称字数边界校验"),
        _case("C2", title="标题包名称字数边界验证"),
    ]
    results = {
        "C1": _verification("conflict"),
        "C2": _verification("grounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.85)

    assert reconciled["C1"].verdict == "conflict"
    assert reconciled["C2"].verdict == "conflict"
    assert reconciled["C2"].bucket == "to_fix"


def test_reconcile_verdicts_propagates_entity_mismatch_and_excludes_conflict():
    cases = [
        _case("C1", title="监测链接自动绑定预置hash01"),
        _case("C2", title="监测链接自动绑定预置hash02"),
        _case("C3", title="监测链接自动绑定预置hash03"),
    ]
    results = {
        "C1": _verification("conflict", mismatch=True),
        "C2": _verification("conflict"),
        "C3": _verification("ungrounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    assert {item.verdict for item in reconciled.values()} == {"ungrounded"}
    assert {item.bucket for item in reconciled.values()} == {"needs_spec"}
    assert all(item.conflict_entity_mismatch for item in reconciled.values())


def test_reconcile_verdicts_does_not_merge_different_features_or_dissimilar_titles():
    cases = [
        _case("C1", feature_id="F1", title="标题包名称字数边界校验"),
        _case("C2", feature_id="F2", title="标题包名称字数边界验证"),
        _case("C3", feature_id="F1", title="投放链接单选正常保存"),
    ]
    results = {
        "C1": _verification("grounded"),
        "C2": _verification("conflict"),
        "C3": _verification("undefined"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.85)

    assert reconciled["C1"].verdict == "grounded"
    assert reconciled["C2"].verdict == "conflict"
    assert reconciled["C3"].verdict == "undefined"


def test_reconcile_verdicts_skips_empty_feature_id():
    cases = [
        _case("C1", feature_id="", title="点击取消关闭弹窗"),
        _case("C2", feature_id="", title="点击取消关闭弹窗"),
    ]
    results = {
        "C1": _verification("grounded"),
        "C2": _verification("conflict"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    assert reconciled["C1"].verdict == "grounded"
    assert reconciled["C2"].verdict == "conflict"


def test_offline_eval_uses_module_as_feature_fallback():
    from scripts.reconcile_offline_eval import _to_case

    record = {
        "id": "C1",
        "test_point_id": "tp-should-not-be-feature",
        "title": "失败数量等于0时不展示查看原因",
        "verification": {"verdict": "grounded", "bucket": "main"},
    }

    converted = _to_case(Path("99__prd_任务中心.cases.jsonl"), record)

    assert converted is not None
    case, _ = converted
    assert case.feature_id == "99__prd_任务中心"


async def test_verify_cases_applies_reconcile_when_enabled(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    cases = [
        _case("C1", title="标题包名称字数边界校验01"),
        _case("C2", title="标题包名称字数边界校验02"),
        _case("C3", title="标题包名称字数边界校验03"),
    ]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(case_id="C1", verdict="grounded", rationale="有支撑"),
                    vmod._CaseVerdict(case_id="C2", verdict="grounded", rationale="有支撑"),
                    vmod._CaseVerdict(case_id="C3", verdict="conflict", rationale="误判冲突"),
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", True, raising=False)
    monkeypatch.setattr(vmod.settings, "reconcile_sim", 0.92, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(cases, {"F1": [PrdSection("§5.6", "标题包名称规则", "§5.6")]})

    assert {item.verdict for item in results.values()} == {"grounded"}
    assert results["C3"].bucket == "main"


async def test_verify_cases_keeps_original_verdicts_when_reconcile_disabled(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    cases = [
        _case("C1", title="标题包名称字数边界校验01"),
        _case("C2", title="标题包名称字数边界校验02"),
    ]

    class _FakeClient:
        async def generate_structured(self, **kw):
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(case_id="C1", verdict="grounded", rationale="有支撑"),
                    vmod._CaseVerdict(case_id="C2", verdict="conflict", rationale="原判冲突"),
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False, raising=False)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    results = await verify_cases(cases, {"F1": [PrdSection("§5.6", "标题包名称规则", "§5.6")]})

    assert results["C1"].verdict == "grounded"
    assert results["C2"].verdict == "conflict"
    assert results["C2"].bucket == "to_fix"


async def test_conflict_revote_overrides_initial_conflict_by_majority(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    calls: list[list[str]] = []

    class _FakeClient:
        async def generate_structured(self, *, user_content, **kw):
            payload = json.loads(user_content)
            calls.append([case["case_id"] for case in payload["test_cases"]])
            if len(calls) == 1:
                return vmod._VerifyLLMOutput(
                    verdicts=[
                        vmod._CaseVerdict(case_id="C1", verdict="conflict", rationale="首轮冲突"),
                        vmod._CaseVerdict(case_id="C2", verdict="grounded", rationale="有支撑"),
                    ]
                )
            return vmod._VerifyLLMOutput(
                verdicts=[vmod._CaseVerdict(case_id="C1", verdict="grounded", rationale="复判有支撑")]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "conflict_revote_enabled", True)
    monkeypatch.setattr(vmod.settings, "revote_n", 3)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False)

    cases = [_case("C1"), _case("C2")]
    results = await verify_cases(cases, {"F1": [PrdSection("§5.6", "标题包规则", "§5.6")]})

    assert results["C1"].verdict == "grounded"
    assert results["C1"].bucket == "main"
    assert results["C2"].verdict == "grounded"
    assert calls == [["C1", "C2"], ["C1"], ["C1"]]


async def test_conflict_revote_skips_non_conflict_cases(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    calls = 0

    class _FakeClient:
        async def generate_structured(self, **kw):
            nonlocal calls
            calls += 1
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(case_id="C1", verdict="grounded", rationale="有支撑"),
                    vmod._CaseVerdict(case_id="C2", verdict="ungrounded", rationale="无支撑"),
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "conflict_revote_enabled", True)
    monkeypatch.setattr(vmod.settings, "revote_n", 3)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False)

    cases = [_case("C1"), _case("C2")]
    await verify_cases(cases, {"F1": [PrdSection("§5.6", "标题包规则", "§5.6")]})

    assert calls == 1


async def test_conflict_revote_result_still_passes_entity_gate(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    calls = 0

    class _FakeClient:
        async def generate_structured(self, **kw):
            nonlocal calls
            calls += 1
            same_entity = calls == 1
            return vmod._VerifyLLMOutput(
                verdicts=[
                    vmod._CaseVerdict(
                        case_id="C1",
                        verdict="conflict",
                        rationale="复判仍为冲突",
                        conflict_subject_case="监测链接",
                        conflict_subject_prd="投放链接",
                        same_entity=same_entity,
                    )
                ]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "conflict_revote_enabled", True)
    monkeypatch.setattr(vmod.settings, "revote_n", 3)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", True)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", False)

    cases = [_case("C1")]
    results = await verify_cases(cases, {"F1": [PrdSection("§7.1", "监测链接规则", "§7.1")]})

    assert results["C1"].verdict == "ungrounded"
    assert results["C1"].bucket == "needs_spec"
    assert results["C1"].conflict_entity_mismatch is True


async def test_revote_then_reconcile_when_both_switches_enabled(monkeypatch):
    from src.testcase_generator.stages.verify import verifier as vmod
    from src.testcase_generator.stages.verify.verifier import PrdSection, verify_cases

    calls = 0

    class _FakeClient:
        async def generate_structured(self, **kw):
            nonlocal calls
            calls += 1
            if calls == 1:
                return vmod._VerifyLLMOutput(
                    verdicts=[
                        vmod._CaseVerdict(case_id="C1", verdict="conflict", rationale="首轮冲突"),
                        vmod._CaseVerdict(case_id="C2", verdict="grounded", rationale="有支撑"),
                        vmod._CaseVerdict(case_id="C3", verdict="grounded", rationale="有支撑"),
                    ]
                )
            return vmod._VerifyLLMOutput(
                verdicts=[vmod._CaseVerdict(case_id="C1", verdict="grounded", rationale="复判有支撑")]
            )

    monkeypatch.setattr(vmod, "get_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(vmod.settings, "conflict_revote_enabled", True)
    monkeypatch.setattr(vmod.settings, "revote_n", 3)
    monkeypatch.setattr(vmod.settings, "verdict_reconcile_enabled", True)
    monkeypatch.setattr(vmod.settings, "reconcile_sim", 0.92)
    monkeypatch.setattr(vmod.settings, "conflict_entity_gate_enabled", False)
    monkeypatch.setattr(vmod.settings, "verify_cross_section_conflict_enabled", False)

    cases = [
        _case("C1", title="标题包名称字数边界校验01"),
        _case("C2", title="标题包名称字数边界校验02"),
        _case("C3", title="标题包名称字数边界校验03"),
    ]
    results = await verify_cases(cases, {"F1": [PrdSection("§5.6", "标题包规则", "§5.6")]})

    assert {item.verdict for item in results.values()} == {"grounded"}
    assert calls == 3
