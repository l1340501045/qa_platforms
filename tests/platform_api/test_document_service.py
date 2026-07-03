"""文档 Service 集成测试。"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.core.exceptions import ApiError
from src.platform_api.services.document_service import DocumentService
from tests.platform_api.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def db_session():
    """获取真实 DB session。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seed_system(db_session: AsyncSession):
    system_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"doc_service_{system_id.hex[:8]}"},
    )
    await db_session.commit()

    yield system_id

    await db_session.execute(text("DELETE FROM knowledge.documents WHERE system_id = :sid"), {"sid": system_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


async def test_batch_upload_persists_selected_doc_type(
    db_session: AsyncSession,
    seed_system,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DocumentService(db_session)
    content_hash = uuid.uuid4().hex

    async def fake_process_uploads(*, files, system_id):
        return SimpleNamespace(
            documents=[
                {
                    "title": "需求文档",
                    "content": "# PRD",
                    "content_hash": content_hash,
                    "storage_path": f"systems/{system_id}/documents/需求文档.md",
                    "folder_path": None,
                    "metadata": {"original_filename": "需求文档.md"},
                }
            ],
            skipped=[],
            failed=[],
            images=[],
            total_files=len(files),
        )

    monkeypatch.setattr(service.upload_service, "process_uploads", fake_process_uploads)
    monkeypatch.setattr(service, "_trigger_kb_parsing", lambda documents: None)

    result = await service.batch_upload(system_id=seed_system, files=[object()], doc_type="prd")

    assert result["uploaded"][0]["doc_type"] == "prd"

    row = (
        await db_session.execute(
            text("SELECT doc_type FROM knowledge.documents WHERE content_hash = :hash"),
            {"hash": content_hash},
        )
    ).one()
    assert row[0] == "prd"


async def test_batch_upload_rejects_unknown_doc_type_before_processing(
    db_session: AsyncSession,
    seed_system,
    monkeypatch: pytest.MonkeyPatch,
):
    service = DocumentService(db_session)

    async def should_not_process_uploads(*, files, system_id):
        raise AssertionError("非法 doc_type 时不应继续处理上传文件")

    monkeypatch.setattr(service.upload_service, "process_uploads", should_not_process_uploads)

    with pytest.raises(ApiError) as exc:
        await service.batch_upload(system_id=seed_system, files=[object()], doc_type="unknown_type")

    assert exc.value.error_code == "E4001"
    assert "文档类型" in exc.value.message
