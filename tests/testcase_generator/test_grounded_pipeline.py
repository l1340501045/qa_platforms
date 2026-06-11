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


def test_dedup_folds_placeholder_when_assertion_exists():
    # 同一测试点：有确定断言时，"需求待确认"占位用例应被折叠为断言的重复
    cases = [
        DedupCase("a1", "TP-1", "管理员可查看全量标题数据", text="可看到全部投手数据"),
        DedupCase("p1", "TP-1", "【需求待确认】管理员全量写操作权限范围",
                  text="PRD 未定义该行为，待 PM 澄清后再补确定断言", is_placeholder=True),
    ]
    dup_map = find_duplicates(cases)
    assert dup_map.get("p1") == "a1"
    assert "a1" not in dup_map


def test_dedup_keeps_single_placeholder_when_all_placeholder():
    # 全是占位 → 仅留其一
    cases = [
        DedupCase("p1", "TP-2", "【需求待确认】Token 过期返回 401", is_placeholder=True),
        DedupCase("p2", "TP-2", "【需求待确认】Token 过期提示重新登录", is_placeholder=True),
    ]
    dup_map = find_duplicates(cases)
    assert dup_map.get("p2") == "p1"


def test_dedup_protects_boundary_values():
    # 边界语义 + 数字不同 → 不同边界值的有效用例，绝不可误并
    cases = [
        DedupCase("b1", "TP-3", "导入恰好1000行数据时校验通过", text="提示导入成功"),
        DedupCase("b2", "TP-3", "导入恰好999行数据时校验通过", text="提示导入成功"),
        DedupCase("b3", "TP-3", "导入超出1001行数据时被拦截", text="提示超出上限"),
    ]
    dup_map = find_duplicates(cases)
    assert "b1" not in dup_map and "b2" not in dup_map and "b3" not in dup_map
