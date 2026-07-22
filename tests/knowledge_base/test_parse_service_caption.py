"""parse_service 图解析开关测试：关时产物与接入前一致"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.knowledge_base.services.parsers.markdown_parser import canonicalize_markdown


def _make_doc(content: str = "# Test\n\nHello", image_refs=None):
    doc = MagicMock()
    doc.id = uuid4()
    doc.system_id = uuid4()
    doc.content = content
    doc.image_refs = image_refs or []
    doc.image_captions = None
    doc.folder_path = "test_prd"
    doc.metadata_ = None
    doc.content_hash = "old_hash"
    return doc


class TestImageCaptionSwitch:
    @pytest.mark.asyncio
    async def test_switch_off_no_vision_called(self):
        """关图述时，生产正文与 hash 必须等于 canonical snapshot。"""
        raw_text = "---\ntitle: PRD\n---\n\n  # §1\n\n![img](images/a.png)\n\nText  \n"
        snapshot = canonicalize_markdown(raw_text)
        doc = _make_doc(raw_text)

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

            await service.parse_document(doc.id)

        call_kwargs = service.repo.update.call_args
        updated_content = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content", "")
        assert updated_content == snapshot.content
        assert call_kwargs.kwargs["content_hash"] == snapshot.canonical_sha256
        assert call_kwargs.kwargs["image_refs"] == list(snapshot.image_refs)
        assert call_kwargs.kwargs["metadata_"] == snapshot.frontmatter
        updated_captions = call_kwargs.kwargs.get("image_captions")
        assert updated_captions is None

    @pytest.mark.asyncio
    async def test_switch_on_triggers_caption_pipeline(self):
        """image_caption_enabled=True → 调用图解析流水线"""
        doc = _make_doc("# §1\n\n![img](images/a.png)\n\nText")

        with (
            patch("src.knowledge_base.services.parse_service.VectorizePipeline"),
            patch("src.knowledge_base.services.parse_service.DocumentRepository"),
            patch("src.knowledge_base.services.parse_service.settings") as mock_settings,
            patch("src.knowledge_base.services.parse_service.run_image_caption_pipeline") as mock_pipeline,
        ):
            mock_settings.image_caption_enabled = True
            mock_settings.entity_graph_enabled = False
            mock_settings.image_caption_concurrency = 2
            enriched_content = "enriched content with [图述]"
            mock_pipeline.return_value = (enriched_content, {"a.png": {"caption_text": "test"}})

            from src.knowledge_base.services.parse_service import ParseService

            session = AsyncMock()
            service = ParseService(session)
            service.repo.get_by_id = AsyncMock(return_value=doc)
            service.repo.find_by_content_hash = AsyncMock(return_value=None)
            service.repo.update = AsyncMock()
            service.vectorize_pipeline.vectorize_document = AsyncMock()

            await service.parse_document(doc.id)

        mock_pipeline.assert_called_once()
        call_kwargs = service.repo.update.call_args
        updated_content = call_kwargs.kwargs.get("content") or call_kwargs[1].get("content", "")
        assert "enriched content" in updated_content
        assert call_kwargs.kwargs["content_hash"] == hashlib.sha256(enriched_content.encode("utf-8")).hexdigest()
