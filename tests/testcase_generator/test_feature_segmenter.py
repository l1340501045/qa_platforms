from unittest.mock import patch

import pytest

from src.testcase_generator.stages.parse.node import _extract_sections, _parse_triples


class _R:  # 鸭子 SearchResult（_extract_sections 只用 content_snippet + title）
    def __init__(self, content, title="DOC"):
        self.content_snippet = content
        self.title = title


_NESTED = "# 六\n\n## 6.3 功能方案\n\n### 书籍状态\n状态机A\n\n### 作家管理\n管理B\n\n## 6.1 流程图\n图\n"


def test_triples_parsed():
    t = _parse_triples(_NESTED)
    assert [h for _l, h, _b in t] == ["六", "6.3 功能方案", "书籍状态", "作家管理", "6.1 流程图"]


def test_roles_drive_boundaries():
    roles = {0: "container", 1: "container", 2: "feature_root", 3: "feature_root", 4: "background"}
    secs = _extract_sections(_R(_NESTED), "prd", roles=roles)
    headings = [s.heading for s in secs]
    assert "书籍状态" in headings and "作家管理" in headings
    assert "6.1 流程图" not in headings
    assert "6.3 功能方案" not in headings and "六" not in headings


def test_deep_children_fold_into_feature_root():
    """feature_root 下的深层子标题（未标或标 container）正文必须折叠进该功能节，不能丢。"""
    doc = "# 文档\n\n## 功能方案\n\n### 书籍搜索\n搜索规格\n\n#### 模糊匹配\n模糊逻辑\n\n#### 高级过滤\n过滤规则\n"
    # 书籍搜索=feature_root，模糊匹配/高级过滤 未标（LLM 没返回或标 container）
    roles = {0: "container", 1: "container", 2: "feature_root", 3: "container", 4: "container"}
    secs = _extract_sections(_R(doc), "prd", roles=roles)
    assert len(secs) == 1
    assert secs[0].heading == "书籍搜索"
    assert "模糊逻辑" in secs[0].content
    assert "过滤规则" in secs[0].content


def test_deep_children_unlabeled_fold():
    """LLM 漏标（roles 无该 idx）的深层子标题也必须折叠进 current。"""
    doc = "# 文档\n\n## 功能方案\n\n### 会员订阅\n订阅规格\n\n#### 自动续费\n续费逻辑\n"
    # 只标前3个，idx=3 (自动续费) 未标
    roles = {0: "container", 1: "container", 2: "feature_root"}
    secs = _extract_sections(_R(doc), "prd", roles=roles)
    assert len(secs) == 1
    assert "续费逻辑" in secs[0].content


def test_sibling_container_does_not_steal_children():
    """同级 container 后的漏标子标题不应折叠进上一个 feature_root。"""
    doc = (
        "# 文档\n\n"
        "### 书籍搜索\n搜索规格\n\n"
        "### 交互说明\n交互概述\n\n"
        "#### 弹窗规则\n弹窗逻辑\n"
    )
    # 书籍搜索=feature_root, 交互说明=container(同级), 弹窗规则=漏标
    roles = {0: "container", 1: "feature_root", 2: "container", 3: ""}
    secs = _extract_sections(_R(doc), "prd", roles=roles)
    # 弹窗逻辑不应出现在「书籍搜索」的 content 里
    if secs:
        book_sec = next((s for s in secs if s.heading == "书籍搜索"), None)
        if book_sec:
            assert "弹窗逻辑" not in book_sec.content


def test_roles_none_is_legacy():
    """roles=None 走旧路，输出结构与现状一致（feature_level=1 → 全折叠进一级标题）。"""
    secs = _extract_sections(_R(_NESTED), "prd", roles=None)
    assert len(secs) == 1
    assert secs[0].heading == "六"
    assert "状态机A" in secs[0].content
    assert "管理B" in secs[0].content


# ── segmenter 单测（mock LLM + 兜底）──


@pytest.mark.asyncio
async def test_segmenter_returns_roles():
    from unittest.mock import AsyncMock, MagicMock

    from src.testcase_generator.stages.parse import feature_segmenter as fseg

    triples = [(1, "六", ""), (2, "6.3 功能方案", ""), (3, "书籍状态", "x"), (2, "6.1 流程图", "图")]

    class _Out:
        classifications = [
            type("C", (), {"idx": 1, "role": "container"})(),
            type("C", (), {"idx": 2, "role": "feature_root"})(),
            type("C", (), {"idx": 3, "role": "background"})(),
        ]

    mock_client = MagicMock()
    mock_client.generate_structured = AsyncMock(return_value=_Out())

    with patch("src.testcase_generator.stages.parse.feature_segmenter.get_llm_client", return_value=mock_client):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles.get(2) == "feature_root"


@pytest.mark.asyncio
async def test_segmenter_fallback_on_error():
    from unittest.mock import AsyncMock, MagicMock

    from src.testcase_generator.stages.parse import feature_segmenter as fseg

    triples = [(2, "A", "x")]

    mock_client = MagicMock()
    mock_client.generate_structured = AsyncMock(side_effect=RuntimeError("llm down"))

    with patch("src.testcase_generator.stages.parse.feature_segmenter.get_llm_client", return_value=mock_client):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles == {}


@pytest.mark.asyncio
async def test_segmenter_empty_triples():
    """空 triples 直接返回 {}，不调用 LLM。"""
    from src.testcase_generator.stages.parse import feature_segmenter as fseg

    roles = await fseg.decide_feature_roles("DOC", [])
    assert roles == {}


@pytest.mark.asyncio
async def test_segmenter_no_feature_root_returns_empty():
    """LLM 返回但无 feature_root → 回退空 dict。"""
    from unittest.mock import AsyncMock, MagicMock

    from src.testcase_generator.stages.parse import feature_segmenter as fseg

    triples = [(1, "文档", ""), (2, "背景", "x")]

    class _Out:
        classifications = [
            type("C", (), {"idx": 0, "role": "container"})(),
            type("C", (), {"idx": 1, "role": "meta"})(),
        ]

    mock_client = MagicMock()
    mock_client.generate_structured = AsyncMock(return_value=_Out())

    with patch("src.testcase_generator.stages.parse.feature_segmenter.get_llm_client", return_value=mock_client):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles == {}


@pytest.mark.asyncio
async def test_segmenter_invalid_role_and_idx_filtered():
    """非法 role 和越界 idx 被过滤。"""
    from unittest.mock import AsyncMock, MagicMock

    from src.testcase_generator.stages.parse import feature_segmenter as fseg

    triples = [(2, "功能A", "x")]

    class _Out:
        classifications = [
            type("C", (), {"idx": 0, "role": "feature_root"})(),
            type("C", (), {"idx": 99, "role": "feature_root"})(),  # 越界
            type("C", (), {"idx": 0, "role": "invalid_role"})(),  # 非法 role
        ]

    mock_client = MagicMock()
    mock_client.generate_structured = AsyncMock(return_value=_Out())

    with patch("src.testcase_generator.stages.parse.feature_segmenter.get_llm_client", return_value=mock_client):
        roles = await fseg.decide_feature_roles("DOC", triples)
    assert roles == {0: "feature_root"}
    assert 99 not in roles
