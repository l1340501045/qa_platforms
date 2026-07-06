"""Task 0.0 — seed 原文加载器测试（C1 单一数据源守卫）。

核心断言：`load_seed_markdown` 返回 seed 文档的【原始 markdown】——含 `#` 标题前缀、
含 meta 段，与 `parse_node` 剥离/折叠后的 `parsed_context.sources` 截然不同。
这是「节点与离线探针卡同一套规则集」的根基（评审 C1）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.testcase_generator.stages.rule_extract import source_loader


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _patch_repo(monkeypatch, doc):
    monkeypatch.setattr(source_loader, "async_session_factory", lambda: _FakeSession())
    fake_repo = MagicMock()
    fake_repo.get_by_id = AsyncMock(return_value=doc)
    monkeypatch.setattr(source_loader, "DocumentRepository", lambda session: fake_repo)
    return fake_repo


@pytest.mark.asyncio
async def test_returns_raw_markdown_with_headings_and_meta(monkeypatch):
    raw_md = (
        "# 一、文档元信息\n作者：x\n## 1.2 变更日志\n| 时间 | 版本 |\n"
        "# 五、功能详述\n## 5.1 账户授权\n投手只能看本人触发的授权记录。授权后立即生效。\n"
    )
    doc = MagicMock()
    doc.content = raw_md
    _patch_repo(monkeypatch, doc)

    out = await source_loader.load_seed_markdown(str(uuid4()))

    # 完整原文：含 # 前缀（splitter 的标题正则依赖它）
    assert out == raw_md
    assert out.startswith("# ")
    # 含 meta 段（parse 会丢弃，这里必须保留——证明数据源不同于 parsed_context）
    assert "文档元信息" in out and "变更日志" in out


@pytest.mark.asyncio
async def test_raises_when_document_missing(monkeypatch):
    _patch_repo(monkeypatch, None)
    with pytest.raises(ValueError):
        await source_loader.load_seed_markdown(str(uuid4()))
