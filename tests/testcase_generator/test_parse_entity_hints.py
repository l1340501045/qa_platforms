"""修复1：parse_node 真实填充 entity_graph_hints（非仅 schema 测试）
修复B：retrieve_entity_graph_hints 自身单测（挡住二跳 bug）

验证：entity_retrieval_enabled 开时 parse_node 产出 entity_graph_hints 非空且
含 section_priority/mutually_exclusive/unreachable 类型关系；关时为空列表。
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.testcase_generator.stages.parse.kb_retriever import (
    _HIGH_VALUE_RELATION_TYPES,
    retrieve_entity_graph_hints,
)


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


# ─── 修复 B：retrieve_entity_graph_hints 自身单测（挡住二跳 bug）───────────────


def _entity(id_, name, canonical_key, entity_type="section"):
    e = MagicMock()
    e.id = id_
    e.name = name
    e.canonical_key = canonical_key
    e.entity_type = entity_type
    return e


def _relation(source_id, target_id, relation_type, note=None):
    r = MagicMock()
    r.source_entity_id = source_id
    r.target_entity_id = target_id
    r.relation_type = relation_type
    r.note = note
    return r


class TestRetrieveEntityGraphHints:
    """直接测 retrieve_entity_graph_hints 内部逻辑（mock repo，不整体 mock 函数）"""

    @pytest.mark.asyncio
    async def test_only_one_hop_direct_relations(self):
        """图 A--section_priority-->B, B--mutually_exclusive-->C：
        应产出恰好 2 条一跳关系，不产 A→C 错误间接关系"""
        doc_id = uuid4()
        sys_id = uuid4()
        id_a, id_b, id_c = uuid4(), uuid4(), uuid4()

        entities = [
            _entity(id_a, "§5.0.3 全局字数", "§5.0.3"),
            _entity(id_b, "§5.7.1 定向包名", "§5.7.1"),
            _entity(id_c, "普通名称算法", "rule_half_width", "rule"),
        ]
        relations = [
            _relation(id_b, id_a, "section_priority", "局部优先全局"),
            _relation(id_b, id_c, "mutually_exclusive", "定向包≠普通名称"),
        ]

        mock_repo = AsyncMock()
        mock_repo.get_entities_by_document = AsyncMock(return_value=entities)
        mock_repo.get_relations_by_document = AsyncMock(return_value=relations)

        with patch(
            "src.testcase_generator.stages.parse.kb_retriever.async_session_factory"
        ) as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "src.knowledge_base.repositories.entity_repo.EntityRepository",
                return_value=mock_repo,
            ):
                hints = await retrieve_entity_graph_hints(doc_id, sys_id)

        # 恰好 2 条一跳直接关系
        assert len(hints) == 2
        pairs = {(h["source_entity"], h["target_entity"], h["relation_type"]) for h in hints}
        assert ("§5.7.1", "§5.0.3", "section_priority") in pairs
        assert ("§5.7.1", "rule_half_width", "mutually_exclusive") in pairs
        # 关键：不应有 A→C 间接关系
        assert not any(
            h["source_entity"] == "§5.0.3" and h["target_entity"] == "rule_half_width"
            for h in hints
        )

    @pytest.mark.asyncio
    async def test_non_high_value_relations_filtered(self):
        """非 section_priority/mutually_exclusive/unreachable 的关系被过滤"""
        doc_id, sys_id = uuid4(), uuid4()
        id_a, id_b = uuid4(), uuid4()

        entities = [_entity(id_a, "A", "a"), _entity(id_b, "B", "b")]
        relations = [
            _relation(id_a, id_b, "belongs_to"),  # not high value
            _relation(id_a, id_b, "field_defined_in"),  # not high value
        ]

        mock_repo = AsyncMock()
        mock_repo.get_entities_by_document = AsyncMock(return_value=entities)
        mock_repo.get_relations_by_document = AsyncMock(return_value=relations)

        with patch(
            "src.testcase_generator.stages.parse.kb_retriever.async_session_factory"
        ) as mock_sf:
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "src.knowledge_base.repositories.entity_repo.EntityRepository",
                return_value=mock_repo,
            ):
                hints = await retrieve_entity_graph_hints(doc_id, sys_id)

        assert hints == []

    @pytest.mark.asyncio
    async def test_empty_entities_returns_empty(self):
        """空实体 → 空 hints"""
        mock_repo = AsyncMock()
        mock_repo.get_entities_by_document = AsyncMock(return_value=[])

        with patch(
            "src.testcase_generator.stages.parse.kb_retriever.async_session_factory"
        ) as mock_sf:
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "src.knowledge_base.repositories.entity_repo.EntityRepository",
                return_value=mock_repo,
            ):
                hints = await retrieve_entity_graph_hints(uuid4(), uuid4())

        assert hints == []
