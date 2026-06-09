"""回归测试：RetrievalService 必须把「种子文档自身」纳入检索结果。

根因背景：retrieve_context 原先只做关联图遍历 + 可选向量召回 + 外部检索，
从不包含种子文档本身。对于新上传、无关联、未向量化的 PRD，merged_results 为空，
导致 parse→comprehend 覆盖度 0、Gate 直接 NO_GO，生成永远产不出用例。

本测试锁定修复：无论是否有关联/向量结果，种子文档（有 content 时）必须作为
最高优先级信源出现在 merged_results 中。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.knowledge_base.schemas.common import SearchResult
from src.knowledge_base.services.retrieval_service import RetrievalService


def _make_service(seed_doc, graph_results, vector_results=None):
    """构造一个 sub-service 全部被 mock 的 RetrievalService"""
    svc = RetrievalService(session=AsyncMock())
    svc.doc_repo.get_by_id = AsyncMock(return_value=seed_doc)
    svc.graph_search.traverse_graph = AsyncMock(return_value=graph_results)
    svc.vector_search.search = AsyncMock(return_value=vector_results or [])
    svc.external_adapter.health_check = AsyncMock(return_value=False)
    return svc


@pytest.mark.asyncio
async def test_seed_document_included_when_no_associations():
    """无关联、无向量：merged 仍必须包含种子文档自身内容"""
    doc_id = uuid4()
    seed_doc = SimpleNamespace(id=doc_id, title="登录PRD", content="# 登录\n手机号+验证码登录")
    svc = _make_service(seed_doc, graph_results=[])

    ctx = await svc.retrieve_context(document_id=doc_id, system_id=uuid4())

    assert ctx.total_count == 1
    assert len(ctx.merged_results) == 1
    seed = ctx.merged_results[0]
    assert seed.document_id == doc_id
    assert seed.source == "seed"
    assert "手机号" in seed.content_snippet  # 种子完整内容被带入


@pytest.mark.asyncio
async def test_seed_ranked_first_above_graph_results():
    """种子文档优先级最高，排在关联图结果之前"""
    doc_id = uuid4()
    seed_doc = SimpleNamespace(id=doc_id, title="登录PRD", content="登录需求正文")
    graph = [
        SearchResult(document_id=uuid4(), title="技术文档", content_snippet="接口说明", score=0.9, source="graph"),
    ]
    svc = _make_service(seed_doc, graph_results=graph)

    ctx = await svc.retrieve_context(document_id=doc_id, system_id=uuid4())

    assert len(ctx.merged_results) == 2
    assert ctx.merged_results[0].source == "seed"
    assert ctx.merged_results[0].document_id == doc_id


@pytest.mark.asyncio
async def test_empty_content_seed_not_injected():
    """种子文档无 content 时不注入（避免空信源污染）"""
    doc_id = uuid4()
    seed_doc = SimpleNamespace(id=doc_id, title="空文档", content="")
    svc = _make_service(seed_doc, graph_results=[])

    ctx = await svc.retrieve_context(document_id=doc_id, system_id=uuid4())

    assert ctx.total_count == 0
    assert ctx.merged_results == []
