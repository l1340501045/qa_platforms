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


# ── Task 4：dedup_node 算向量传入 + 降级 ──────────────────────────────────────

import asyncio  # noqa: E402

from src.testcase_generator.schemas.test_case import GeneratedTestCase, Provenance  # noqa: E402
from src.testcase_generator.stages.dedup import node as dedup_node_mod  # noqa: E402


def _tc(case_id: str, tp_id: str, title: str, *, exp: list[str] | None = None) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=case_id,
        test_point_id=tp_id,
        title=title,
        expected_results=exp or [],
        priority="P1",
        provenance=Provenance(source_section="§x", verbatim_excerpt="x", trust_level=3),
        trust_level=3,
    )


class _FakeEmbeddingClient:
    """返回与 case_id 绑定的固定向量，cosine 可控。"""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    async def embed_batch(self, texts):
        # dedup_node 按 final_cases 顺序传 texts（title + expected_results 拼接）；
        # 测试里按调用顺序与 case 顺序对齐返回固定向量。
        return [self._vectors[k] for k in self._vectors][: len(texts)]


class _FailingEmbeddingClient:
    async def embed_batch(self, texts):
        raise RuntimeError("embedding gateway down")


def _semantic_state():
    # 两条跨 test_point、词面远、语义近的同义用例（mock 向量高度相似）
    return {
        "final_test_cases": [
            _tc("TC-001", "TP-A", "组长可查看全员定向包", exp=["显示所有成员定向包"]),
            _tc("TC-002", "TP-B", "投放组长能看到所有成员创建的定向包", exp=["列出全部成员定向包"]),
        ],
        "test_points": [],
    }


def test_dedup_node_semantic_on_folds_synonyms(monkeypatch):
    # semantic_dedup_enabled=True：mock 向量高度相似 → 语义折叠生效
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_enabled", True)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_threshold", 0.86)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_cross_tp_threshold", 0.90)
    monkeypatch.setattr(
        dedup_node_mod, "EmbeddingClient",
        lambda: _FakeEmbeddingClient({"TC-001": _emb(1.0, 0.0), "TC-002": _emb(0.985, 0.02)}),
    )
    result = asyncio.run(dedup_node_mod.dedup_node(_semantic_state()))
    cases = result["final_test_cases"]
    # TC-001（先出现）为 canonical，TC-002 标为其重复
    by_id = {c.id: c for c in cases}
    assert by_id["TC-002"].duplicate_of == "TC-001"
    assert result["dedup_summary"]["duplicate_count"] == 1


def test_dedup_node_degrades_to_lexical_on_embedding_failure(monkeypatch):
    # embedding 调用抛异常 → 降级纯词面，不抛、summary 仍产出
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_enabled", True)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_threshold", 0.86)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_cross_tp_threshold", 0.90)
    monkeypatch.setattr(dedup_node_mod, "EmbeddingClient", lambda: _FailingEmbeddingClient())
    result = asyncio.run(dedup_node_mod.dedup_node(_semantic_state()))
    # 词面差异大，降级后不折叠
    cases = result["final_test_cases"]
    by_id = {c.id: c for c in cases}
    assert by_id["TC-001"].duplicate_of is None
    assert by_id["TC-002"].duplicate_of is None
    assert result["dedup_summary"]["duplicate_count"] == 0


def test_dedup_node_semantic_off_no_embedding_call(monkeypatch):
    # semantic_dedup_enabled=False：不调 EmbeddingClient，行为与现状一致
    called = {"n": 0}

    class _Spy:
        async def embed_batch(self, texts):
            called["n"] += 1
            return []

    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_enabled", False)
    monkeypatch.setattr(dedup_node_mod, "EmbeddingClient", lambda: _Spy())
    result = asyncio.run(dedup_node_mod.dedup_node(_semantic_state()))
    assert called["n"] == 0  # 关时不触网
    assert result["dedup_summary"]["total"] == 2
