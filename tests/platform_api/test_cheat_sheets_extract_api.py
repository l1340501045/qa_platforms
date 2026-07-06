"""cheat sheet 提取触发 API 测试。"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.platform_api.core.settings import settings
from src.platform_api.main import app


@pytest.fixture
async def client():
    """HTTPX async client for testing FastAPI app。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_extract_api_returns_disabled_when_switch_off(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """cheat_sheet_extract_enabled=False 时返回 disabled 提示，不触发提取。"""
    monkeypatch.setattr(settings, "cheat_sheet_extract_enabled", False, raising=False)

    resp = await client.post(f"/api/v1/documents/{uuid4()}/cheat-sheets/extract")

    assert resp.status_code == 202
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {
        "enabled": False,
        "message": "cheat_sheet_extract_enabled disabled",
    }


@pytest.mark.asyncio
async def test_extract_api_triggers_service_when_switch_on(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """cheat_sheet_extract_enabled=True 时触发提取落库服务。"""
    document_id = uuid4()
    system_id = uuid4()
    sheet_id = uuid4()
    monkeypatch.setattr(settings, "cheat_sheet_extract_enabled", True)

    doc = MagicMock()
    doc.id = document_id
    doc.system_id = system_id
    doc_repo = MagicMock()
    doc_repo.get_by_id = AsyncMock(return_value=doc)
    service = MagicMock()
    saved_sheet = MagicMock()
    saved_sheet.id = sheet_id
    saved_sheet.version = 3
    service.extract_and_save = AsyncMock(return_value=saved_sheet)

    monkeypatch.setattr("src.platform_api.api.v1.cheat_sheets.DocumentRepository", MagicMock(return_value=doc_repo))
    monkeypatch.setattr("src.platform_api.api.v1.cheat_sheets.EntityRepository", MagicMock())
    monkeypatch.setattr("src.platform_api.api.v1.cheat_sheets.CheatSheetRepository", MagicMock())
    monkeypatch.setattr(
        "src.platform_api.api.v1.cheat_sheets.CheatSheetExtractorService",
        MagicMock(return_value=service),
    )

    resp = await client.post(f"/api/v1/documents/{document_id}/cheat-sheets/extract")

    assert resp.status_code == 202
    body = resp.json()
    assert body["data"] == {
        "enabled": True,
        "sheet_id": str(sheet_id),
        "version": 3,
    }
    service.extract_and_save.assert_awaited_once_with(document_id, system_id)
