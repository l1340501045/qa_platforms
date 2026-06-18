"""实体级关系查询服务测试：定位实体 → 多跳遍历 → 归类应答"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.knowledge_base.services.entity_graph.query_service import (
    EntityContext,
    query_entity_context,
)


def _entity(name, canonical_key, entity_type="field", section_ref=None):
    e = MagicMock()
    e.id = uuid4()
    e.name = name
    e.canonical_key = canonical_key
    e.entity_type = entity_type
    e.section_ref = section_ref
    e.description = f"{name} 描述"
    return e


class TestQueryEntityContext:
    @pytest.mark.asyncio
    async def test_full_context_for_directed_package_name(self):
        """定向包名查询 → 应包含 field_defined_in/section_priority/mutually_exclusive"""
        # 构造实体
        e_field = _entity("定向包名", "field_定向包名", "field", "§5.7.1")
        e_section_local = _entity("§5.7.1 定向包名称", "§5.7.1", "section", "§5.7.1")
        e_section_global = _entity("§5.0.3 全局字数规则", "§5.0.3", "section", "§5.0.3")
        e_other = _entity("普通名称字数算法", "rule_half_width", "rule", "§5.0.3")

        # mock session: 按 name/canonical_key 匹配找到 seed
        session = AsyncMock()

        # find_by_name 返回 seed 实体
        async def mock_find(name, system_id):
            if "定向包名" in name:
                return e_field
            return None

        # traverse 返回邻居
        async def mock_traverse(seed_id, max_depth=2):
            return [
                (e_section_local.id, 1, "field_defined_in", "outgoing"),
                (e_section_global.id, 2, "section_priority", "outgoing"),
                (e_other.id, 1, "mutually_exclusive", "outgoing"),
            ]

        # get_entity_by_id 批量查实体详情
        entity_map = {
            e_field.id: e_field,
            e_section_local.id: e_section_local,
            e_section_global.id: e_section_global,
            e_other.id: e_other,
        }

        async def mock_get_entities(entity_ids):
            return [entity_map[eid] for eid in entity_ids if eid in entity_map]

        repo = AsyncMock()
        repo.find_entity_by_name = AsyncMock(side_effect=mock_find)
        repo.traverse_entities = AsyncMock(side_effect=mock_traverse)
        repo.get_entities_by_ids = AsyncMock(side_effect=mock_get_entities)

        with patch("src.knowledge_base.services.entity_graph.query_service.settings") as mock_s:
            mock_s.entity_retrieval_enabled = True
            result = await query_entity_context("定向包名", system_id=uuid4(), repo=repo)

        assert isinstance(result, EntityContext)
        assert result.seed_entity is not None
        assert result.seed_entity.canonical_key == "field_定向包名"

        # 应含各类型关系
        rel_types = {r["relation_type"] for r in result.related}
        assert "field_defined_in" in rel_types
        assert "section_priority" in rel_types
        assert "mutually_exclusive" in rel_types

    @pytest.mark.asyncio
    async def test_entity_not_found_returns_empty(self):
        """查询不存在的实体 → 空结果"""
        repo = AsyncMock()
        repo.find_entity_by_name = AsyncMock(return_value=None)

        with patch("src.knowledge_base.services.entity_graph.query_service.settings") as mock_s:
            mock_s.entity_retrieval_enabled = True
            result = await query_entity_context("不存在的概念", system_id=uuid4(), repo=repo)

        assert result.seed_entity is None
        assert result.related == []

    @pytest.mark.asyncio
    async def test_switch_off_returns_empty(self):
        """entity_retrieval_enabled=False → 空结果"""
        from unittest.mock import patch

        repo = AsyncMock()
        with patch("src.knowledge_base.services.entity_graph.query_service.settings") as mock_s:
            mock_s.entity_retrieval_enabled = False
            result = await query_entity_context("定向包名", system_id=uuid4(), repo=repo)

        assert result.seed_entity is None
        assert result.related == []
        repo.find_entity_by_name.assert_not_called()
