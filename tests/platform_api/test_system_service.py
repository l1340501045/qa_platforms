"""系统 Service 集成测试。"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.core.exceptions import ApiError
from src.platform_api.services.system_service import SystemService
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
async def seed_system_stats(db_session: AsyncSession):
    """创建系统 + 有效/软删除文档 + 批次，用于验证列表聚合统计。"""
    system_id = uuid.uuid4()
    active_doc_id = uuid.uuid4()
    deleted_doc_id = uuid.uuid4()
    batch_ids = [uuid.uuid4(), uuid.uuid4()]

    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"system_stats_{system_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents "
            "(id, system_id, title, doc_type, content, storage_path, content_hash) "
            "VALUES (:id, :sid, '有效 PRD', 'prd', 'content', '/tmp/a.md', :hash)"
        ),
        {"id": active_doc_id, "sid": system_id, "hash": uuid.uuid4().hex},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents "
            "(id, system_id, title, doc_type, content, storage_path, content_hash, deleted_at) "
            "VALUES (:id, :sid, '已删除 PRD', 'prd', 'content', '/tmp/b.md', :hash, now())"
        ),
        {"id": deleted_doc_id, "sid": system_id, "hash": uuid.uuid4().hex},
    )
    for batch_id in batch_ids:
        await db_session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) "
                "VALUES (:id, :did, :sid, 'completed')"
            ),
            {"id": batch_id, "did": active_doc_id, "sid": system_id},
        )

    await db_session.commit()
    yield {"system_id": system_id, "doc_ids": [active_doc_id, deleted_doc_id], "batch_ids": batch_ids}

    await db_session.execute(
        text("DELETE FROM testcase.test_batches WHERE id = ANY(:ids)"),
        {"ids": batch_ids},
    )
    await db_session.execute(
        text("DELETE FROM knowledge.documents WHERE id = ANY(:ids)"),
        {"ids": [active_doc_id, deleted_doc_id]},
    )
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


async def test_list_systems_returns_real_document_and_batch_counts(
    db_session: AsyncSession,
    seed_system_stats,
):
    service = SystemService(db_session)

    items, _ = await service.list_systems(offset=0, limit=100)
    item = next(i for i in items if i.id == seed_system_stats["system_id"])

    assert item.document_count == 1
    assert item.batch_count == 2


@pytest.fixture
async def seed_system_with_soft_deleted_doc(db_session: AsyncSession):
    """创建系统 + 仅软删除文档，用于验证系统删除不会被 tombstone 阻塞。"""
    system_id = uuid.uuid4()
    deleted_doc_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"system_soft_doc_{system_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents "
            "(id, system_id, title, doc_type, content, storage_path, content_hash, deleted_at) "
            "VALUES (:id, :sid, '已删除 PRD', 'prd', 'content', '/tmp/deleted.md', :hash, now())"
        ),
        {"id": deleted_doc_id, "sid": system_id, "hash": uuid.uuid4().hex},
    )
    await db_session.commit()
    yield {"system_id": system_id, "doc_id": deleted_doc_id}

    await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": deleted_doc_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


@pytest.fixture
async def seed_system_with_active_doc(db_session: AsyncSession):
    """创建系统 + 有效文档，用于验证真实业务资产仍阻止系统删除。"""
    system_id = uuid.uuid4()
    active_doc_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"system_active_doc_{system_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents "
            "(id, system_id, title, doc_type, content, storage_path, content_hash) "
            "VALUES (:id, :sid, '有效 PRD', 'prd', 'content', '/tmp/active.md', :hash)"
        ),
        {"id": active_doc_id, "sid": system_id, "hash": uuid.uuid4().hex},
    )
    await db_session.commit()
    yield {"system_id": system_id, "doc_id": active_doc_id}

    await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": active_doc_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


@pytest.fixture
async def seed_system_with_batch_on_soft_deleted_doc(db_session: AsyncSession):
    """创建系统 + 软删除文档 + 批次，用于验证批次仍阻止系统删除。"""
    system_id = uuid.uuid4()
    deleted_doc_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"system_batch_{system_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents "
            "(id, system_id, title, doc_type, content, storage_path, content_hash, deleted_at) "
            "VALUES (:id, :sid, '已删除 PRD', 'prd', 'content', '/tmp/deleted-batch.md', :hash, now())"
        ),
        {"id": deleted_doc_id, "sid": system_id, "hash": uuid.uuid4().hex},
    )
    await db_session.execute(
        text(
            "INSERT INTO testcase.test_batches (id, document_id, system_id, status) "
            "VALUES (:id, :did, :sid, 'completed')"
        ),
        {"id": batch_id, "did": deleted_doc_id, "sid": system_id},
    )
    await db_session.commit()
    yield {"system_id": system_id, "doc_id": deleted_doc_id, "batch_id": batch_id}

    await db_session.execute(text("DELETE FROM testcase.test_batches WHERE id = :id"), {"id": batch_id})
    await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": deleted_doc_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


async def test_delete_system_allows_only_soft_deleted_documents(
    db_session: AsyncSession,
    seed_system_with_soft_deleted_doc,
):
    service = SystemService(db_session)

    await service.delete_system(seed_system_with_soft_deleted_doc["system_id"])

    system_count = (
        await db_session.execute(
            text("SELECT count(*) FROM public.systems WHERE id = :id"),
            {"id": seed_system_with_soft_deleted_doc["system_id"]},
        )
    ).scalar_one()
    doc_count = (
        await db_session.execute(
            text("SELECT count(*) FROM knowledge.documents WHERE id = :id"),
            {"id": seed_system_with_soft_deleted_doc["doc_id"]},
        )
    ).scalar_one()

    assert system_count == 0
    assert doc_count == 0


async def test_delete_system_rejects_active_documents(
    db_session: AsyncSession,
    seed_system_with_active_doc,
):
    service = SystemService(db_session)

    with pytest.raises(ApiError) as exc:
        await service.delete_system(seed_system_with_active_doc["system_id"])

    assert exc.value.error_code == "E4091"
    assert "文档" in exc.value.message


async def test_delete_system_rejects_existing_batches_even_if_document_is_soft_deleted(
    db_session: AsyncSession,
    seed_system_with_batch_on_soft_deleted_doc,
):
    service = SystemService(db_session)

    with pytest.raises(ApiError) as exc:
        await service.delete_system(seed_system_with_batch_on_soft_deleted_doc["system_id"])

    assert exc.value.error_code == "E4091"
    assert "批次" in exc.value.message
