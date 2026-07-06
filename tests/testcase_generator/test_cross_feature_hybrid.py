"""CrossFeatureIndex Hybrid 检索测试：关键词盲区 / 向量补召回 / 异常降级。"""
from unittest.mock import patch

import pytest

from src.testcase_generator.stages import context_utils
from src.testcase_generator.stages.context_utils import CrossFeatureIndex


class _Sec:
    def __init__(self, heading, content, source_ref, section_kind="spec"):
        self.heading = heading
        self.content = content
        self.source_ref = source_ref
        self.section_kind = section_kind


class _Src:
    def __init__(self, title, trust_level, sections):
        self.title = title
        self.trust_level = trust_level
        self.sections = sections


class _Ctx:
    def __init__(self, sources):
        self.sources = sources


# A 与 query 词面重叠（"投放方式"）；B 语义相近但用词不同（"广告形式"），词面不重叠
_SEC_A = _Sec("投放方式切换规则", "切换投放方式后已选监测链接自动清空，需重新选择投放方式对应链接", "§6")
_SEC_B = _Sec("广告形式重置说明", "广告形式调整后追踪链接需重置", "§7")


def _ctx():
    return _Ctx([_Src("PRD", 1, [_SEC_A, _SEC_B])])


_QUERY = "切换投放方式后监测链接是否清空"


@pytest.mark.asyncio
async def test_disabled_is_keyword_only(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", False)
    idx = await CrossFeatureIndex.build(_ctx())
    res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs          # 词面重叠仍召回
    assert "§7" not in refs      # 纯关键词召不回语义相近的（这正是要修的盲区）


@pytest.mark.asyncio
async def test_hybrid_recalls_semantic_neighbor(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", True)

    async def fake_batch(self, texts):
        # 候选 A→[1,0,0]，候选 B→[0,1,0]
        return [[1.0, 0.0, 0.0] if "投放方式" in t else [0.0, 1.0, 0.0] for t in texts]

    async def fake_single(self, text):
        return [0.0, 0.95, 0.0]   # query 向量接近 B

    with patch.object(context_utils.EmbeddingClient, "__init__", lambda self: None), \
         patch.object(context_utils.EmbeddingClient, "embed_batch", fake_batch), \
         patch.object(context_utils.EmbeddingClient, "embed_single", fake_single):
        idx = await CrossFeatureIndex.build(_ctx())
        res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs and "§7" in refs   # 关键词召回A + 向量补召回B


@pytest.mark.asyncio
async def test_embed_failure_degrades_to_keyword(monkeypatch):
    monkeypatch.setattr(context_utils.settings, "hybrid_cross_retrieval_enabled", True)

    async def boom(self, *args, **kwargs):
        raise RuntimeError("embedding gateway down")

    with patch.object(context_utils.EmbeddingClient, "embed_batch", boom), \
         patch.object(context_utils.EmbeddingClient, "embed_single", boom):
        idx = await CrossFeatureIndex.build(_ctx())          # build 期失败不抛
        res = await idx.query(_QUERY, set(), top_k=5, min_score=1)
    refs = {r.source_ref for r in res}
    assert "§6" in refs                                       # 降级为纯关键词仍可用
