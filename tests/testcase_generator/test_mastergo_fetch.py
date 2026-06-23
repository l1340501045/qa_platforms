"""落点⑦ — mastergo_fetch 单测：链接解析（layer/page/goto）+ DSL→摘要 + 异步兜底"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.testcase_generator.stages.parse.mastergo_fetch import (
    dsl_to_spec_digest,
    enrich_sections_with_mastergo,
    extract_goto_links,
    extract_mastergo_links,
)

# ── 链接解析：layer_id 格式 ──


def test_extract_links_with_layer_id():
    c = "见原型 https://mastergo.com/file/171777687959897?page_id=68%3A91864&layer_id=90%3A420043 完"
    refs = extract_mastergo_links(c)
    assert len(refs) == 1
    assert refs[0].file_id == "171777687959897"
    assert refs[0].layer_id == "90:420043"
    assert refs[0].is_page_only is False


# ── 链接解析：page_id 格式（真实 PRD 链接） ──


def test_extract_links_page_only():
    c = "管理端见原型 https://mastergo.com/file/171777687959897?fileOpenFrom=project&page_id=68%3A91864 完"
    refs = extract_mastergo_links(c)
    assert len(refs) == 1
    assert refs[0].file_id == "171777687959897"
    assert refs[0].layer_id == "68:91864"
    assert refs[0].is_page_only is True


def test_extract_links_multiple_pages():
    c = (
        "页面A https://mastergo.com/file/123?page_id=48%3A74637 "
        "页面B https://mastergo.com/file/123?page_id=68%3A91864 完"
    )
    refs = extract_mastergo_links(c)
    assert len(refs) == 2
    assert {r.layer_id for r in refs} == {"48:74637", "68:91864"}


def test_extract_links_dedup():
    c = (
        "链接1 https://mastergo.com/file/123?page_id=48%3A74637 "
        "链接2 https://mastergo.com/file/123?page_id=48%3A74637 重复"
    )
    refs = extract_mastergo_links(c)
    assert len(refs) == 1


def test_extract_links_prefers_layer_over_page():
    c = "https://mastergo.com/file/123?page_id=68%3A91864&layer_id=90%3A420043"
    refs = extract_mastergo_links(c)
    assert len(refs) == 1
    assert refs[0].layer_id == "90:420043"
    assert refs[0].is_page_only is False


def test_extract_none():
    assert extract_mastergo_links("没有任何原型链接的普通文本") == []


def test_extract_no_id_params():
    c = "https://mastergo.com/file/123?fileOpenFrom=project"
    assert extract_mastergo_links(c) == []


# ── /goto/ 短链解析 ──


def test_extract_goto_links():
    c = "详见 https://mastergo.com/goto/abc123?from=share 和正文"
    urls = extract_goto_links(c)
    assert len(urls) == 1
    assert "goto/abc123" in urls[0]


def test_extract_goto_links_none():
    assert extract_goto_links("没有 goto 链接") == []


# ── DSL → 摘要 ──


def test_digest_from_dsl():
    dsl = {"nodes": [{"type": "FRAME", "name": "审核列表", "children": [
        {"type": "TEXT", "name": "x", "text": [{"text": "审核状态"}]},
        {"type": "TEXT", "name": "y", "text": [{"text": "待提审"}, {"text": "/审核通过"}]},
    ]}]}
    d = dsl_to_spec_digest(dsl)
    assert "审核状态" in d and "待提审" in d


def test_digest_empty_nodes():
    assert dsl_to_spec_digest({"nodes": []}) == ""


def test_digest_nested_frames():
    dsl = {"nodes": [{"type": "FRAME", "name": "根", "children": [
        {"type": "FRAME", "name": "表单区", "children": [
            {"type": "TEXT", "name": "t1", "text": [{"text": "用户名"}]},
            {"type": "TEXT", "name": "t2", "text": [{"text": "密码"}]},
        ]},
    ]}]}
    d = dsl_to_spec_digest(dsl)
    assert "表单区" in d and "用户名" in d and "密码" in d


# ── 异步兜底：fetch 失败不抛 ──


class FakeSection:
    def __init__(self, content: str):
        self.content = content


class FakeSource:
    def __init__(self, sections: list):
        self.sections = sections


@pytest.mark.asyncio
async def test_enrich_fetch_failure_no_raise():
    """单链接失败不抛异常、section 内容不变。"""
    sec = FakeSection("原型 https://mastergo.com/file/999?layer_id=1%3A2 完")
    sources = [FakeSource([sec])]
    original_content = sec.content

    with patch(
        "src.testcase_generator.stages.parse.mastergo_fetch.fetch_dsl",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError("401", request=None, response=None),
    ):
        result = await enrich_sections_with_mastergo(sources, "bad_token")

    assert result == 0
    assert sec.content == original_content


@pytest.mark.asyncio
async def test_enrich_page_only_empty_nodes():
    """page_id 链接 DSL 返回空 nodes → 不富化、不报错。"""
    sec = FakeSection("原型 https://mastergo.com/file/123?page_id=68%3A91864 完")
    sources = [FakeSource([sec])]
    original_content = sec.content

    with patch(
        "src.testcase_generator.stages.parse.mastergo_fetch.fetch_dsl",
        new_callable=AsyncMock,
        return_value={"styles": {}, "nodes": [], "components": []},
    ):
        result = await enrich_sections_with_mastergo(sources, "valid_token")

    assert result == 0
    assert sec.content == original_content


@pytest.mark.asyncio
async def test_enrich_layer_id_success():
    """layer_id 链接 DSL 返回有内容 → 富化成功。"""
    sec = FakeSection("原型 https://mastergo.com/file/123?layer_id=90%3A420043 完")
    sources = [FakeSource([sec])]

    fake_dsl = {"nodes": [{"type": "FRAME", "name": "列表页", "children": [
        {"type": "TEXT", "name": "t", "text": [{"text": "状态"}]},
    ]}]}
    with patch(
        "src.testcase_generator.stages.parse.mastergo_fetch.fetch_dsl",
        new_callable=AsyncMock,
        return_value=fake_dsl,
    ):
        result = await enrich_sections_with_mastergo(sources, "valid_token")

    assert result == 1
    assert "【原型规格（来自 MasterGo 设计稿）】" in sec.content
    assert "状态" in sec.content


@pytest.mark.asyncio
async def test_enrich_cache_dedup():
    """同一 (file_id, layer_id) 跨 section 只拉一次 DSL。"""
    url = "https://mastergo.com/file/123?layer_id=90%3A420043"
    sec1 = FakeSection(f"A {url} 完")
    sec2 = FakeSection(f"B {url} 完")
    sources = [FakeSource([sec1, sec2])]

    fake_dsl = {"nodes": [{"type": "FRAME", "name": "X", "children": [
        {"type": "TEXT", "name": "t", "text": [{"text": "内容"}]},
    ]}]}
    mock_fetch = AsyncMock(return_value=fake_dsl)
    with patch("src.testcase_generator.stages.parse.mastergo_fetch.fetch_dsl", mock_fetch):
        result = await enrich_sections_with_mastergo(sources, "token")

    assert result == 2
    assert mock_fetch.call_count == 1  # 缓存命中，只调一次


@pytest.mark.asyncio
async def test_enrich_no_token():
    """无 token → 直接返回 0，不做任何请求。"""
    sec = FakeSection("原型 https://mastergo.com/file/123?layer_id=1%3A2 完")
    sources = [FakeSource([sec])]
    result = await enrich_sections_with_mastergo(sources, "")
    assert result == 0
