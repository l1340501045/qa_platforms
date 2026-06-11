"""阶段1+2 新机制的纯逻辑单测（不依赖 LLM）：
- review_router 覆盖回填回环（含上限）
- dedup 近重复聚类
- verify verdict→bucket 确定性映射
"""

from __future__ import annotations

from src.testcase_generator.pipeline.edges import MAX_RECONCILE, review_router
from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates
from src.testcase_generator.stages.verify.verifier import _VERDICT_BUCKET, _normalize_verdict


class _Audit:
    def __init__(self, uncovered):
        self.uncovered_test_point_ids = uncovered


def test_review_router_loops_to_backfill_when_uncovered():
    state = {"audit_report": _Audit(["TP-009"]), "reconcile_iterations": 0}
    assert review_router(state) == "backfill"


def test_review_router_stops_at_reconcile_cap():
    state = {"audit_report": _Audit(["TP-009"]), "reconcile_iterations": MAX_RECONCILE}
    assert review_router(state) == "verify"


def test_review_router_to_verify_when_fully_covered():
    state = {"audit_report": _Audit([]), "reconcile_iterations": 0}
    assert review_router(state) == "verify"


def test_verdict_bucket_mapping_is_deterministic():
    assert _VERDICT_BUCKET["grounded"] == "main"
    assert _VERDICT_BUCKET["conflict"] == "to_fix"
    assert _VERDICT_BUCKET["ungrounded"] == "needs_spec"
    assert _VERDICT_BUCKET["undefined"] == "needs_spec"


def test_unknown_verdict_normalized_strictly():
    # 无法识别的 verdict 从严归 ungrounded（不放进主集）
    assert _normalize_verdict("garbage") == "ungrounded"
    assert _normalize_verdict("GROUNDED") == "grounded"


def test_dedup_flags_parametric_near_duplicates():
    cases = [
        DedupCase("c1", "F-002", "切换每页显示条数为10条，验证列表数据条数正确"),
        DedupCase("c2", "F-002", "切换每页显示条数为50条，验证列表数据条数正确"),
        DedupCase("c3", "F-002", "切换每页显示条数为100条，验证列表数据条数正确"),
        DedupCase("c4", "F-003", "点击解绑按钮弹出二次确认对话框并成功解绑账户"),
    ]
    dup_map = find_duplicates(cases)
    # c2/c3 是 c1 的近重复（仅数字不同），c4 不应被并入
    assert dup_map.get("c2") == "c1"
    assert dup_map.get("c3") == "c1"
    assert "c4" not in dup_map


def test_dedup_empty_input():
    assert find_duplicates([]) == {}
