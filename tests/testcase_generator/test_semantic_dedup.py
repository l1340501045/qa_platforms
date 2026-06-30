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


# ── GPT Review 修复回归 ──────────────────────────────────────────────────────


def test_semantic_same_tp_not_polluted_by_trailing_empty_feature():
    # 🔴-1 回归：末条 case feature_id 为空时，不应污染同 tp 对的阈值判定。
    # 同 tp、cosine 落在 [0.86, 0.90) 的对应被折叠（用 0.86），不能因末条空被误判成跨 tp 用 0.90。
    a = _c("A", "TP1", "组长可查看全员定向包", dim="access_control")
    b = _c("B", "TP1", "投放组长能看到所有成员创建的定向包", dim="access_control")
    trailing = _c("Z", "", "无关占位用例无 test_point")  # 末条 feature_id 空（污染源）
    # cosine((1,0),(0.55,0.3)) ≈ 0.878 ∈ [0.86, 0.90)
    emb = {"A": _emb(1.0, 0.0), "B": _emb(0.55, 0.3)}
    dup = find_duplicates([a, b, trailing], embeddings=emb, semantic_threshold=0.86,
                          semantic_cross_tp_threshold=0.90)
    # 修复前：same_tp 恒 False（末条 c.feature_id 空）→ 用 0.90 → 0.878<0.90 不折叠（bug）
    # 修复后：same_tp 基于当前对 (A,B) 自身 → TP1==TP1 → 用 0.86 → 0.878≥0.86 折叠
    assert dup.get("B") == "A" or dup.get("A") == "B"


def test_semantic_trailing_empty_feature_does_not_collapse_cross_tp_pair():
    # 🔴-1 互补断言：末条空时，跨 tp、cosine∈[0.86,0.90) 的对**仍不应折叠**（跨 tp 用 0.90 严阈值）。
    # 防止修复"过度"——不能让末条空把跨 tp 对也放松到 0.86。
    a = _c("A", "TP1", "组长可查看全员定向包", dim="access_control")
    b = _c("B", "TP2", "投放组长能看到所有成员创建的定向包", dim="access_control")
    trailing = _c("Z", "", "无关占位用例无 test_point")
    # cosine((1,0),(0.55,0.3)) = 0.55/√(0.55²+0.3²) = 0.55/0.6265 ≈ 0.878 ∈ [0.86, 0.90)
    emb = {"A": _emb(1.0, 0.0), "B": _emb(0.55, 0.3)}
    dup = find_duplicates([a, b, trailing], embeddings=emb, semantic_threshold=0.86,
                          semantic_cross_tp_threshold=0.90)
    # 跨 tp 用 0.90，0.878 < 0.90 → 不折叠（即便末条空，跨 tp 严阈值不被放松）
    assert dup == {}


def test_dedup_node_degrades_to_lexical_and_lexical_still_folds(monkeypatch):
    # 🟡-3：embedding 失败时，一对**词面能折叠**的用例仍被词面 pass 折叠
    # （证明是"降级到词面"而非"去重被跳过"）
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_enabled", True)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_threshold", 0.86)
    monkeypatch.setattr(dedup_node_mod.settings, "semantic_dedup_cross_tp_threshold", 0.90)
    monkeypatch.setattr(dedup_node_mod, "EmbeddingClient", lambda: _FailingEmbeddingClient())
    state = {
        "final_test_cases": [
            _tc("TC-001", "TP-A", "切换每页显示条数为10条，验证列表数据条数正确", exp=["列表显示10条"]),
            _tc("TC-002", "TP-B", "切换每页显示条数为50条，验证列表数据条数正确", exp=["列表显示50条"]),
        ],
        "test_points": [],
    }
    result = asyncio.run(dedup_node_mod.dedup_node(state))
    by_id = {c.id: c for c in result["final_test_cases"]}
    # 词面 pass（跨 tp 同维度换皮）应折叠 TC-002 → TC-001
    assert by_id["TC-002"].duplicate_of == "TC-001"
    assert result["dedup_summary"]["duplicate_count"] == 1


# ── 🟡-2：零回归规模化对拍（数据验证，非代码推断）─────────────────────────────
# 用现有 3185 条离线数据跑 find_duplicates（不传 embeddings），断言 duplicate_count
# 稳定在 golden 值 228。任何破坏"关时逐字节一致"的改动都会让此值漂移。.audit 缺失则 skip。

import glob  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

_OFFLINE_BATCH = "278c211f-6f25-4970-a425-9db94cbc8ff7"
_OFFLINE_GOLDEN_DUP_COUNT = 228


def _load_offline_cases():
    pattern = os.path.join(".audit", _OFFLINE_BATCH, "modules", "*.cases.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    cases = []
    for fp in files:
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            cases.append(
                DedupCase(
                    case_id=d["id"],
                    feature_id=d.get("test_point_id") or "",
                    title=d.get("title") or "",
                    text=" ".join(d.get("expected_results") or []),
                    dimension=" ".join(d.get("dimensions") or []),
                )
            )
    return cases


def test_zero_regression_offline_golden():
    # 🟡-2：不传 embeddings 时，3185 条离线数据的 dup_count 稳定 = golden（228）。
    # 把"零回归"从代码推断升级为数据验证。.audit 缺失则 skip（CI 无审计数据时不阻断）。
    cases = _load_offline_cases()
    if cases is None:
        import pytest

        pytest.skip(f"离线审计数据不存在：.audit/{_OFFLINE_BATCH}/")
    dup = find_duplicates(cases)  # 不传 embeddings → 纯词面，与改造前逐字节一致
    assert len(dup) == _OFFLINE_GOLDEN_DUP_COUNT
