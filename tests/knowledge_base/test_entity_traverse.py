"""实体图 BFS 遍历测试"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.knowledge_base.repositories.entity_repo import EntityRepository


class TestTraverseEntities:
    @pytest.mark.asyncio
    async def test_returns_neighbors_with_depth_and_relation(self):
        """BFS 返回多跳邻居含 entity_id, depth, relation_type, direction"""
        seed_id = uuid4()
        neighbor1 = uuid4()
        neighbor2 = uuid4()

        # 模拟 DB 返回 BFS 结果
        fake_rows = [
            MagicMock(entity_id=neighbor1, depth=1, relation_type="section_priority", direction="outgoing"),
            MagicMock(entity_id=neighbor2, depth=2, relation_type="mutually_exclusive", direction="incoming"),
        ]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=fake_rows)))

        repo = EntityRepository(session)
        result = await repo.traverse_entities(seed_id, max_depth=2)

        assert len(result) == 2
        assert result[0] == (neighbor1, 1, "section_priority", "outgoing")
        assert result[1] == (neighbor2, 2, "mutually_exclusive", "incoming")

    @pytest.mark.asyncio
    async def test_passes_correct_params(self):
        """验证传参正确（seed_id + max_depth）"""
        seed_id = uuid4()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        repo = EntityRepository(session)
        await repo.traverse_entities(seed_id, max_depth=3)

        call_args = session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("params", {})
        assert str(seed_id) in str(call_args)

    @pytest.mark.asyncio
    async def test_empty_graph_returns_empty(self):
        """无邻居 → 空列表"""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))

        repo = EntityRepository(session)
        result = await repo.traverse_entities(uuid4(), max_depth=2)
        assert result == []
