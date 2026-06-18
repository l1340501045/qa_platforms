"""修复1：parse_node 真实填充 entity_graph_hints（非仅 schema 测试）

验证：entity_retrieval_enabled 开时 parse_node 产出 entity_graph_hints 非空且
含 section_priority/mutually_exclusive/unreachable 类型关系；关时为空列表。
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_state(doc_id=None, sys_id=None):
    return {
        "document_id": str(doc_id or uuid4()),
        "system_id": str(sys_id or uuid4()),
        "generation_config": {},
    }


def _fake_retrieval_context(doc_id=None, sys_id=None):
    """模拟 kb_retriever 返回的 RetrievalContext"""
    from src.knowledge_base.schemas.common import RetrievalContext, SearchResult

    did = doc_id or uuid4()
    sid = sys_id or uuid4()
    seed = SearchResult(
        document_id=did,
        title="漫剧批创初版功能PRD",
        content_snippet="# §5.0 全局\n\n全局规则\n\n## §5.7 定向包\n\n定向包说明",
        relation_type=None,
        depth=0,
        score=1.0,
    )
    return RetrievalContext(
        seed_document_id=did,
        system_id=sid,
        graph_results=[seed],
        vector_results=[],
        merged_results=[seed],
    )


class TestEntityGraphHintsFilling:
    """修复1：parse_node 真实调 retrieve_entity_graph_hints 填充 hints"""

    @pytest.mark.asyncio
    async def test_switch_on_fills_hints_with_high_value_relations(self):
        """entity_retrieval_enabled=True → hints 包含 section_priority 等关系"""
        fake_hints = [
            {
                "relation_type": "section_priority",
                "source_entity": "§5.7.1",
                "target_entity": "§5.0.3",
                "note": "局部优先全局",
            },
            {
                "relation_type": "mutually_exclusive",
                "source_entity": "监测链接",
                "target_entity": "投放链接",
                "note": "不同概念",
            },
        ]

        with (
            patch("src.testcase_generator.stages.parse.node.retrieve_knowledge_context") as mock_kb,
            patch("src.testcase_generator.stages.parse.node.retrieve_entity_graph_hints") as mock_hints,
            patch("src.testcase_generator.stages.parse.node.settings") as mock_settings,
            patch("src.testcase_generator.stages.parse.node.classify_sections", new_callable=AsyncMock),
        ):
            mock_kb.return_value = _fake_retrieval_context()
            mock_settings.entity_retrieval_enabled = True
            mock_hints.return_value = fake_hints

            from src.testcase_generator.stages.parse.node import parse_node

            result = await parse_node(_make_state())

        parsed_context = result["parsed_context"]
        assert len(parsed_context.entity_graph_hints) == 2
        rel_types = {h["relation_type"] for h in parsed_context.entity_graph_hints}
        assert "section_priority" in rel_types
        assert "mutually_exclusive" in rel_types
        mock_hints.assert_called_once()

    @pytest.mark.asyncio
    async def test_switch_off_leaves_hints_empty(self):
        """entity_retrieval_enabled=False → hints 为空列表，不调 retrieve"""
        with (
            patch("src.testcase_generator.stages.parse.node.retrieve_knowledge_context") as mock_kb,
            patch("src.testcase_generator.stages.parse.node.retrieve_entity_graph_hints") as mock_hints,
            patch("src.testcase_generator.stages.parse.node.settings") as mock_settings,
            patch("src.testcase_generator.stages.parse.node.classify_sections", new_callable=AsyncMock),
        ):
            mock_kb.return_value = _fake_retrieval_context()
            mock_settings.entity_retrieval_enabled = False

            from src.testcase_generator.stages.parse.node import parse_node

            result = await parse_node(_make_state())

        parsed_context = result["parsed_context"]
        assert parsed_context.entity_graph_hints == []
        mock_hints.assert_not_called()
