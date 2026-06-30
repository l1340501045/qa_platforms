"""语义去重升级（hybrid embedding + 词法）测试。

Task 1：零回归基线 —— 不传 embeddings 时 find_duplicates 行为逐字节不变。
Task 2 起：语义候选（固定向量）+ 护栏全复用。
"""

from __future__ import annotations

from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates


def _c(
    case_id: str,
    tp_id: str,
    title: str,
    *,
    rule_codes: list[str] | None = None,
    text: str = "",
    dim: str = "",
    is_placeholder: bool = False,
) -> DedupCase:
    return DedupCase(
        case_id=case_id,
        feature_id=tp_id,
        title=title,
        text=text,
        dimension=dim,
        is_placeholder=is_placeholder,
        rule_codes=list(rule_codes or []),
    )


# ── Task 1：零回归基线（不传 embeddings，行为与改造前一致）──────────────────────


def test_baseline_lexical_folds_cross_tp_same_dim():
    # 跨 test_point、同维度的换皮近重复（词面 pass 折叠）
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确", dim="functional")
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确", dim="functional")
    dup = find_duplicates([a, b])
    assert dup.get("b1") == "a1"


def test_baseline_boundary_protection_keeps_different_boundary_values():
    # 数字集不同 + 含边界关键词 → _protected 拦下，不折叠
    a = _c("a1", "TP-1", "最多1000行", text="上限1000")
    b = _c("b1", "TP-1", "最多999行", text="上限999")
    dup = find_duplicates([a, b])
    assert dup == {}


def test_baseline_structural_placeholder_fold():
    # 同测试点：占位用例并入首个断言用例（结构化折叠）
    assertion = _c("a1", "TP-1", "验证标题输入校验", is_placeholder=False)
    placeholder = _c("p1", "TP-1", "需求待确认：标题输入校验", is_placeholder=True)
    dup = find_duplicates([assertion, placeholder])
    assert dup.get("p1") == "a1"


def test_baseline_safe_dedup_protects_last_canonical_of_a_rule():
    # safe_dedup 开：a1/b1 高相似但分别是 R-001/R-002 各自唯一覆盖 → 不折叠
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确", rule_codes=["R-001"])
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确", rule_codes=["R-002"])
    dup = find_duplicates([a, b], safe_dedup_enabled=True)
    assert "b1" not in dup


def test_baseline_safe_dedup_off_folds():
    # safe_dedup 关：退回旧行为，折叠
    a = _c("a1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确", rule_codes=["R-001"])
    b = _c("b1", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确", rule_codes=["R-002"])
    dup = find_duplicates([a, b], safe_dedup_enabled=False)
    assert dup.get("b1") == "a1"


# ── Task 2：语义候选（固定向量，cosine 可控）───────────────────────────────────


def _emb(*vals: float) -> list[float]:
    return list(vals)


def test_semantic_folds_cross_testpoint_synonyms():
    # 跨 test_point 的换措辞同义（灌水大头）——语义候选须"全局"，不能只在组内
    a = _c("A", "TP1", "组长可查看全员定向包", dim="access_control")
    b = _c("B", "TP2", "投放组长能看到所有成员创建的定向包", dim="access_control")
    emb = {"A": _emb(1.0, 0.0), "B": _emb(0.985, 0.02)}  # cosine≈0.999
    dup = find_duplicates(
        [a, b],
        embeddings=emb,
        semantic_threshold=0.86,
        semantic_cross_tp_threshold=0.90,
    )
    assert dup.get("B") == "A" or dup.get("A") == "B"


def test_semantic_respects_boundary_protection():
    # 向量完全相同（cosine=1），但数字集不同 + 边界关键词 → _protected 仍拦下，不折叠
    a = _c("A", "TP1", "最多1000行", text="上限1000")
    b = _c("B", "TP1", "最多999行", text="上限999")
    emb = {"A": _emb(1.0, 0.0), "B": _emb(1.0, 0.0)}  # cosine=1
    dup = find_duplicates([a, b], embeddings=emb, semantic_threshold=0.86)
    assert dup == {}  # _protected 生效，不折叠


def test_semantic_respects_safe_dedup_last_canonical():
    # 语义高度相似，但 b1 是 R-002 唯一覆盖 → safe_dedup 护栏拦下，不折叠
    a = _c("A", "TP1", "切换每页显示条数为10条，验证列表数据条数正确", rule_codes=["R-001"])
    b = _c("B", "TP2", "切换每页显示条数为50条，验证列表数据条数正确", rule_codes=["R-002"])
    emb = {"A": _emb(1.0, 0.0), "B": _emb(0.99, 0.01)}  # cosine≈0.9999
    dup = find_duplicates(
        [a, b],
        embeddings=emb,
        semantic_threshold=0.86,
        safe_dedup_enabled=True,
    )
    assert "B" not in dup  # 护栏保护 R-002 最后一条


def test_semantic_no_embeddings_no_change():
    # 不传 embeddings → 语义 pass 整段跳过，与基线一致（零回归）
    a = _c("A", "TP1", "组长可查看全员定向包", dim="access_control")
    b = _c("B", "TP2", "投放组长能看到所有成员创建的定向包", dim="access_control")
    dup = find_duplicates([a, b])  # 词面差异大，词面 pass 折叠不了
    assert dup == {}


def test_semantic_missing_vector_skipped():
    # 某条 case 缺向量（embeddings 无该 case_id）→ 该条不参与语义候选，不报错
    a = _c("A", "TP1", "组长可查看全员定向包")
    b = _c("B", "TP2", "投放组长能看到所有成员创建的定向包")
    emb = {"A": _emb(1.0, 0.0)}  # B 缺向量
    dup = find_duplicates([a, b], embeddings=emb, semantic_threshold=0.86)
    assert dup == {}  # B 无向量，无法配对
