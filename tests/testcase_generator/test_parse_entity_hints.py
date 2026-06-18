"""parse 阶段实体图谱提示挂接测试"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.knowledge_base.services.entity_graph.query_service import EntityContext
from src.testcase_generator.schemas.parsed_context import ParsedContext


class TestParseEntityHints:
    def test_parsed_context_has_entity_graph_hints_default_empty(self):
        """ParsedContext 默认 entity_graph_hints 为空列表"""
        ctx = ParsedContext(sources=[], features=[])
        assert ctx.entity_graph_hints == []

    def test_parsed_context_accepts_hints(self):
        """ParsedContext 能接收 entity_graph_hints"""
        hints = [
            {"relation_type": "section_priority", "source": "§5.7.1", "target": "§5.0.3", "note": "局部优先"},
            {"relation_type": "mutually_exclusive", "source": "监测链接", "target": "投放链接", "note": "不同概念"},
        ]
        ctx = ParsedContext(sources=[], features=[], entity_graph_hints=hints)
        assert len(ctx.entity_graph_hints) == 2
        assert ctx.entity_graph_hints[0]["relation_type"] == "section_priority"
