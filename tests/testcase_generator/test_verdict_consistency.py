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
    conflict_refs: bool = False,
    prd_evidence: str | None = None,
) -> CaseVerification:
    bucket = {
        "grounded": "main",
        "conflict": "to_fix",
        "ungrounded": "needs_spec",
        "undefined": "needs_spec",
    }[verdict]
    from src.testcase_generator.schemas.test_case import CrossSectionConflictRef

    return CaseVerification(
        verdict=verdict,
        bucket=bucket,
        rationale=rationale,
        conflict_entity_mismatch=mismatch,
        cross_section_conflict=conflict_refs,
        conflicting_refs=(
            [CrossSectionConflictRef(ref_a="§7.2", quote_a="q1", ref_b="§7.3", quote_b="q2")] if conflict_refs else []
        ),
        conflict_subject_case="用例对象" if conflict_refs else "",
        conflict_subject_prd="PRD对象" if conflict_refs else "",
        prd_evidence=prd_evidence,
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


def test_reconcile_clears_conflict_evidence_fields_when_downgraded():
    """🔴#1 降级：原 conflict（带 refs/subject/cross_section_conflict）被簇内多数降为
    ungrounded 时，conflict 衍生证据字段必须清空，避免 verdict=ungrounded 却残留
    冲突依据的自相矛盾数据。"""
    cases = [
        _case("C1", title="监测链接自动绑定预置hash01"),
        _case("C2", title="监测链接自动绑定预置hash02"),
        _case("C3", title="监测链接自动绑定预置hash03"),
    ]
    results = {
        "C1": _verification("conflict", conflict_refs=True),
        "C2": _verification("ungrounded"),
        "C3": _verification("ungrounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    # C1 由 conflict 降级为 ungrounded（簇内多数 ungrounded）
    assert reconciled["C1"].verdict == "ungrounded"
    # 衍生证据字段必须清空——不得残留 conflict 依据
    assert reconciled["C1"].cross_section_conflict is False
    assert reconciled["C1"].conflicting_refs == []
    assert reconciled["C1"].conflict_subject_case == ""
    assert reconciled["C1"].conflict_subject_prd == ""


def test_reconcile_upgrade_to_conflict_does_not_fabricate_cross_section_refs():
    """🔴#1 升级：原 grounded 被簇内多数升为 conflict 时，不得伪造 cross_section_conflict
    / conflicting_refs（无真实跨节冲突依据），cross_section_conflict 保持 False；
    verdict=conflict 仅由 rationale 的"同构一致化"追溯，避免污染 summarize 的
    cross_section_conflicts 计数。"""
    cases = [
        _case("C1", title="投放方式为付费直投时自动绑定IAP预置链接01"),
        _case("C2", title="投放方式为付费直投时自动绑定IAP预置链接02"),
        _case("C3", title="投放方式为付费直投时自动绑定IAP预置链接03"),
    ]
    results = {
        "C1": _verification("conflict", conflict_refs=True),
        "C2": _verification("conflict", conflict_refs=True),
        "C3": _verification("grounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    # C3 由 grounded 升级为 conflict（簇内多数 conflict）
    assert reconciled["C3"].verdict == "conflict"
    assert reconciled["C3"].bucket == "to_fix"
    # 不得伪造跨节冲突依据——C3 原本就没有 refs
    assert reconciled["C3"].cross_section_conflict is False
    assert reconciled["C3"].conflicting_refs == []
    assert "同构一致化" in reconciled["C3"].rationale


def test_summarize_reports_reconciled_conflict_separately():
    """🔴#1 summarize：5a 升级出的 conflict（verdict=conflict 但 cross_section_conflict=False
    且 rationale 含"同构一致化"）应单列 reconciled_conflict 计数，不混入 cross_section_conflicts，
    使 by_verdict.conflict 与 cross_section_conflicts 的差可解释、不污染 5b 观测基线。"""
    from src.testcase_generator.stages.verify.verifier import summarize

    verifications = {
        # 真实跨节 conflict（有 refs）——计入 cross_section_conflicts
        "R1": CaseVerification(
            verdict="conflict",
            bucket="to_fix",
            rationale="跨节冲突",
            cross_section_conflict=True,
            conflicting_refs=[
                __import__(
                    "src.testcase_generator.schemas.test_case",
                    fromlist=["CrossSectionConflictRef"],
                ).CrossSectionConflictRef(ref_a="§7.2", quote_a="q1", ref_b="§7.3", quote_b="q2")
            ],
        ),
        # 5a 升级出的 conflict（无 refs、rationale 含同构一致化）——不计入 cross_section_conflicts，
        # 应计入 reconciled_conflict
        "R2": CaseVerification(
            verdict="conflict",
            bucket="to_fix",
            rationale="原判（同构一致化：簇内多数 → conflict）",
            cross_section_conflict=False,
            conflicting_refs=[],
        ),
        "R3": CaseVerification(verdict="grounded", bucket="main", rationale="有支撑"),
    }

    summary = summarize(verifications)

    assert summary["by_verdict"]["conflict"] == 2  # R1 + R2 都是 conflict
    assert summary["cross_section_conflicts"] == 1  # 仅 R1 真实跨节冲突
    assert summary["reconciled_conflict"] == 1  # R2 是 5a 升级出的 conflict


def test_reconcile_mismatch_cluster_clears_conflict_evidence_when_downgraded():
    """🟡#3 边界①：mismatch 簇内带 refs 的 conflict 被 ④ mismatch 剔除降级后，
    conflict 衍生证据字段（含 prd_evidence）必须清空。mismatch 降级与多数票降级
    共用同一 else 清字段分支，本用例显式锁定 mismatch 路径下的字段清理。"""
    cases = [
        _case("C1", title="监测链接自动绑定预置hash01"),
        _case("C2", title="监测链接自动绑定预置hash02"),
        _case("C3", title="监测链接自动绑定预置hash03"),
    ]
    results = {
        # C1 是带完整 conflict 证据 + mismatch 标记的 conflict，会被 mismatch 协同剔除降级
        "C1": _verification("conflict", mismatch=True, conflict_refs=True, prd_evidence="PRD反驳原文"),
        "C2": _verification("ungrounded"),
        "C3": _verification("ungrounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    # C1 因 mismatch 剔除 conflict 候选、降为 ungrounded（簇内非 conflict 多数）
    assert reconciled["C1"].verdict == "ungrounded"
    assert reconciled["C1"].conflict_entity_mismatch is True  # mismatch 传播
    assert reconciled["C1"].cross_section_conflict is False
    assert reconciled["C1"].conflicting_refs == []
    assert reconciled["C1"].conflict_subject_case == ""
    assert reconciled["C1"].conflict_subject_prd == ""
    assert reconciled["C1"].prd_evidence == ""  # 反驳证据清空，不残留进待修正清单


def test_reconcile_preserves_real_conflict_refs_when_verdict_stays_conflict():
    """🟡#3 边界②：升级簇内原 conflict 项（带真实 refs）保持 conflict 时，
    conflicting_refs 必须保留——反向断言"保持 conflict 时 refs 不被误清"。"""
    cases = [
        _case("C1", title="投放方式为付费直投时自动绑定IAP预置链接01"),
        _case("C2", title="投放方式为付费直投时自动绑定IAP预置链接02"),
        _case("C3", title="投放方式为付费直投时自动绑定IAP预置链接03"),
    ]
    results = {
        "C1": _verification("conflict", conflict_refs=True, prd_evidence="PRD反驳原文"),
        "C2": _verification("conflict", conflict_refs=True, prd_evidence="PRD反驳原文"),
        "C3": _verification("grounded"),
    }

    reconciled = reconcile_verdicts(results, cases, sim=0.92)

    # C1/C2 原 conflict 且簇内多数仍 conflict → 保持 conflict，真实 refs 必须保留
    assert reconciled["C1"].verdict == "conflict"
    assert reconciled["C2"].verdict == "conflict"
    assert len(reconciled["C1"].conflicting_refs) == 1
    assert len(reconciled["C2"].conflicting_refs) == 1
    assert reconciled["C1"].cross_section_conflict is True
    assert reconciled["C1"].prd_evidence == "PRD反驳原文"  # 保持 conflict 时证据保留
    # C3 由 grounded 升级为 conflict，但不伪造 refs（无真实跨节依据）
    assert reconciled["C3"].verdict == "conflict"
    assert reconciled["C3"].conflicting_refs == []
    assert reconciled["C3"].cross_section_conflict is False


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
