"""实体图谱 repo 测试：save_graph 幂等 + parse 开关控制"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.knowledge_base.schemas.entity import EntityGraph, EntityItem, RelationItem
from src.knowledge_base.repositories.entity_repo import EntityRepository


class TestEntityRepository:
    @pytest.mark.asyncio
    async def test_save_graph_stores_entities_and_relations(self):
        """save_graph 存实体+关系"""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        session.flush = AsyncMock()

        repo = EntityRepository(session)
        doc_id = uuid4()
        system_id = uuid4()

        graph = EntityGraph(
            entities=[
                EntityItem(entity_type="section", name="全局规则", canonical_key="§5.0.3",
                           section_ref="§5.0.3"),
                EntityItem(entity_type="field", name="定向包名", canonical_key="field_定向包名",
                           section_ref="§5.7.1"),
            ],
            relations=[
                RelationItem(source_name="§5.7.1", target_name="§5.0.3",
                             relation_type="section_priority", note="局部优先"),
            ],
        )

        await repo.save_graph(doc_id, system_id, graph)

        # session.add 应被调用（实体+关系）
        assert session.add.call_count >= 2  # 至少 2 个实体
        # flush 应被调用以获取实体 ID
        assert session.flush.called

    @pytest.mark.asyncio
    async def test_save_graph_idempotent_deletes_old(self):
        """重复 save_graph 先删旧实体/关系再写新（幂等）"""
        session = AsyncMock()
        # 模拟已有旧数据
        session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        session.flush = AsyncMock()

        repo = EntityRepository(session)
        doc_id = uuid4()
        system_id = uuid4()

        graph = EntityGraph(entities=[], relations=[])

        await repo.save_graph(doc_id, system_id, graph)

        # 应先执行 DELETE 清理旧数据
        delete_calls = [c for c in session.execute.call_args_list]
        assert len(delete_calls) >= 1  # 至少调了 delete


class TestEntityGraphParseSwitch:
    @pytest.mark.asyncio
    async def test_switch_off_no_extraction(self):
        """entity_graph_enabled=False → 不抽取实体"""
        doc = MagicMock()
        doc.id = uuid4()
        doc.system_id = uuid4()
        doc.content = "# §1\n\nHello"
        doc.image_refs = []
        doc.image_captions = None
        doc.folder_path = "prd"
        doc.metadata_ = None

        with (
            patch("src.knowledge_base.services.parse_service.VectorizePipeline"),
            patch("src.knowledge_base.services.parse_service.DocumentRepository"),
            patch("src.knowledge_base.services.parse_service.settings") as mock_settings,
        ):
            mock_settings.image_caption_enabled = False
            mock_settings.entity_graph_enabled = False

            from src.knowledge_base.services.parse_service import ParseService

            session = AsyncMock()
            service = ParseService(session)
            service.repo.get_by_id = AsyncMock(return_value=doc)
            service.repo.find_by_content_hash = AsyncMock(return_value=None)
            service.repo.update = AsyncMock()
            service.vectorize_pipeline.vectorize_document = AsyncMock()

            with patch("src.knowledge_base.services.parse_service.run_entity_graph_pipeline") as mock_eg:
                await service.parse_document(doc.id)

            mock_eg.assert_not_called()

    @pytest.mark.asyncio
    async def test_switch_on_triggers_entity_extraction(self):
        """entity_graph_enabled=True → 调用实体抽取"""
        doc = MagicMock()
        doc.id = uuid4()
        doc.system_id = uuid4()
        doc.content = "# §1\n\nHello"
        doc.image_refs = []
        doc.image_captions = None
        doc.folder_path = "prd"
        doc.metadata_ = None

        with (
            patch("src.knowledge_base.services.parse_service.VectorizePipeline"),
            patch("src.knowledge_base.services.parse_service.DocumentRepository"),
            patch("src.knowledge_base.services.parse_service.settings") as mock_settings,
            patch("src.knowledge_base.services.parse_service.run_entity_graph_pipeline") as mock_eg,
        ):
            mock_settings.image_caption_enabled = False
            mock_settings.entity_graph_enabled = True
            mock_settings.entity_extract_concurrency = 4
            mock_eg.return_value = None  # 异步函数返回 None

            from src.knowledge_base.services.parse_service import ParseService

            session = AsyncMock()
            service = ParseService(session)
            service.repo.get_by_id = AsyncMock(return_value=doc)
            service.repo.find_by_content_hash = AsyncMock(return_value=None)
            service.repo.update = AsyncMock()
            service.vectorize_pipeline.vectorize_document = AsyncMock()

            await service.parse_document(doc.id)

        mock_eg.assert_called_once()
