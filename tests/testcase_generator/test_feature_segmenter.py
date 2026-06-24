import pytest
from unittest.mock import patch

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
    t = _parse_triples(_NESTED)
    roles = {0: "container", 1: "container", 2: "feature_root", 3: "feature_root", 4: "background"}
    secs = _extract_sections(_R(_NESTED), "prd", roles=roles)
    headings = [s.heading for s in secs]
    assert "书籍状态" in headings and "作家管理" in headings
    assert "6.1 流程图" not in headings
    assert "6.3 功能方案" not in headings and "六" not in headings


def test_roles_none_is_legacy():
    secs = _extract_sections(_R(_NESTED), "prd", roles=None)
    assert len(secs) >= 1


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
