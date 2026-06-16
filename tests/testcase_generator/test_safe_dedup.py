"""Task 3.1 — 规则锚定安全去重护栏测试。

护栏：当折叠会让某条规则失去其「最后一条非重复用例」时，绝不折叠（保证规则覆盖
不被去重弄丢）。开关 safe_dedup_enabled=False 时退回旧行为（无护栏，原样折叠）。
"""

from __future__ import annotations

from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates


def _c(case_id: str, tp_id: str, title: str, *, rule_codes: list[str] | None = None,
       text: str = "", dim: str = "") -> DedupCase:
    return DedupCase(
        case_id=case_id, feature_id=tp_id, title=title, text=text, dimension=dim,
        rule_codes=list(rule_codes or []),
    )


def test_safe_dedup_off_falls_back_to_legacy_behavior():
    # 即使两条用例分别是「各自规则的唯一覆盖」，关闭 safe_dedup 时仍按旧逻辑折叠
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确", rule_codes=["R-001"])
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确", rule_codes=["R-002"])
    dup = find_duplicates([a, b], safe_dedup_enabled=False)
    assert dup.get("b1") == "a1"  # 旧行为：折叠（不保护）


def test_safe_dedup_on_protects_last_canonical_of_a_rule():
    # 关键场景：a1/b1 高相似但分别是 R-001 / R-002 各自唯一覆盖 → 不能折叠
    # 否则 R-002 在 b1 被并入后将零覆盖（其唯一锚点用例消失）
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确", rule_codes=["R-001"])
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确", rule_codes=["R-002"])
    dup = find_duplicates([a, b], safe_dedup_enabled=True)
    assert "b1" not in dup  # 护栏拦下：保留 b1 作为 R-002 的最后非重复用例


def test_safe_dedup_on_allows_fold_when_canonical_remains_for_each_rule():
    # 三条用例都覆盖同一规则 R-001：折叠 b/c 到 a 之后 R-001 仍有 a 作为 canonical
    a = _c("a1", "TP-1", "切换每页显示条数为10条", rule_codes=["R-001"])
    b = _c("b1", "TP-1", "切换每页显示条数为50条", rule_codes=["R-001"])
    c = _c("c1", "TP-1", "切换每页显示条数为100条", rule_codes=["R-001"])
    dup = find_duplicates([a, b, c], safe_dedup_enabled=True)
    # 至少 b 或 c 被折叠（折叠 1 条后 R-001 仍有 ≥2 条 canonical，第二次折叠也安全）
    assert "a1" not in dup  # canonical 一定保留
    assert ("b1" in dup) or ("c1" in dup)


def test_safe_dedup_handles_case_without_rule_codes():
    # 维度增强用例（rule_codes 为空）不进入护栏检查，按旧行为折叠
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确")
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确")
    dup = find_duplicates([a, b], safe_dedup_enabled=True)
    assert dup.get("b1") == "a1"  # 无 rule 锚 → 不护栏


def test_safe_dedup_protects_when_dup_covers_multi_rules():
    # b1 同时是 R-002 的唯一覆盖（也是 R-003 的唯一覆盖）→ 即便只有一条规则告急也要护栏
    a = _c("a1", "TP-1", "切换每页显示条数为10条", rule_codes=["R-001"])
    b = _c("b1", "TP-2", "切换每页显示条数为50条", rule_codes=["R-002", "R-003"])
    dup = find_duplicates([a, b], safe_dedup_enabled=True)
    assert "b1" not in dup
