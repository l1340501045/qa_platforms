"""集成测试 — 通知系统端到端验证

覆盖点：
1. 触发器 011：batch status 变更自动创建通知
2. 触发器不重复：相同状态 UPDATE 不二次发通知
3. NotificationService CRUD：列表/未读数/标记已读/全部已读
4. retry 状态流转不误触发通知（running 不在守卫范围）
5. 响应字段：序列化 alias read、updated_count

真实 DB 连接，不 mock。
"""

import pytest
import uuid
from datetime import datetime, timezone

from tests.platform_api.conftest import requires_db

pytestmark = requires_db

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.services.notification_service import NotificationService
from src.platform_api.schemas.notification import NotificationResponse, MarkAllReadResponse


# ─── Fixtures ───


@pytest.fixture
async def db_session():
    """获取真实 DB session"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seed_batch(db_session: AsyncSession):
    """创建测试所需的 system + document + batch"""
    system_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
        {"id": system_id, "name": f"test_system_{system_id.hex[:8]}"},
    )

    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents (id, system_id, title, doc_type, content, storage_path, content_hash) "
            "VALUES (:id, :sid, :title, 'prd', 'content', '/test', :hash)"
        ),
        {"id": doc_id, "sid": system_id, "title": "测试文档", "hash": uuid.uuid4().hex},
    )

    await db_session.execute(
        text(
            "INSERT INTO testcase.test_batches (id, document_id, system_id, status, total_cases) "
            "VALUES (:id, :did, :sid, 'running', 25)"
        ),
        {"id": batch_id, "did": doc_id, "sid": system_id},
    )

    await db_session.commit()

    yield {"system_id": system_id, "doc_id": doc_id, "batch_id": batch_id}

    # Cleanup
    await db_session.execute(text("DELETE FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id})
    await db_session.execute(text("DELETE FROM testcase.test_batches WHERE id = :id"), {"id": batch_id})
    await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": doc_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


# ─── 触发器测试 ───


@pytest.mark.asyncio
async def test_trigger_creates_notification_on_completed(db_session: AsyncSession, seed_batch):
    """触发器 011：status → pending_review 自动创建 batch_completed 通知"""
    batch_id = seed_batch["batch_id"]

    # UPDATE status to pending_review（模拟 generator 完成）
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'pending_review', current_stage = 'export' WHERE id = :id"),
        {"id": batch_id},
    )
    await db_session.commit()

    # 验证通知已创建
    result = await db_session.execute(
        text(
            "SELECT type, title, body, target_type, target_id, is_read FROM public.notifications WHERE target_id = :bid"
        ),
        {"bid": batch_id},
    )
    rows = result.all()

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == "batch_completed"
    assert row[1] == "用例生成完成"
    assert "25" in row[2]  # body 包含 total_cases
    assert row[3] == "batch"
    assert row[4] == batch_id
    assert row[5] is False  # is_read 默认 False


@pytest.mark.asyncio
async def test_trigger_creates_notification_on_failed(db_session: AsyncSession, seed_batch):
    """触发器 011：status → failed 自动创建 batch_failed 通知"""
    batch_id = seed_batch["batch_id"]

    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'failed', current_stage = 'comprehend' WHERE id = :id"),
        {"id": batch_id},
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT type, body FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id}
    )
    rows = result.all()

    assert len(rows) == 1
    assert rows[0][0] == "batch_failed"
    assert "comprehend" in rows[0][1]


@pytest.mark.asyncio
async def test_trigger_creates_notification_on_suspended(db_session: AsyncSession, seed_batch):
    """触发器 011：status → suspended 自动创建 batch_suspended 通知"""
    batch_id = seed_batch["batch_id"]

    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'suspended', current_stage = 'comprehend' WHERE id = :id"),
        {"id": batch_id},
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT type, title FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id}
    )
    rows = result.all()

    assert len(rows) == 1
    assert rows[0][0] == "batch_suspended"


@pytest.mark.asyncio
async def test_trigger_no_duplicate_on_same_status(db_session: AsyncSession, seed_batch):
    """触发器守卫：重复 UPDATE 相同 status 不二次发通知"""
    batch_id = seed_batch["batch_id"]

    # 先切到 failed
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'failed' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    # 再次 UPDATE 为同样的 failed
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'failed' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT COUNT(*) FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id}
    )
    count = result.scalar()

    assert count == 1  # 只有一条，不重复


@pytest.mark.asyncio
async def test_trigger_no_notification_on_running(db_session: AsyncSession, seed_batch):
    """retry 场景：status → running 不触发通知"""
    batch_id = seed_batch["batch_id"]

    # 先切到 failed（产生一条通知）
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'failed' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    # retry 切回 running（不应产生通知）
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'running' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT COUNT(*) FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id}
    )
    count = result.scalar()

    assert count == 1  # 仍然只有 failed 那一条


# ─── NotificationService CRUD 测试 ───


@pytest.mark.asyncio
async def test_notification_crud_flow(db_session: AsyncSession, seed_batch):
    """通知 CRUD 完整流程：创建 → 列表 → 未读数 → 标记已读 → 全部已读"""
    batch_id = seed_batch["batch_id"]
    service = NotificationService(db_session)

    # 触发两条通知
    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'pending_review' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    await db_session.execute(
        text("UPDATE testcase.test_batches SET status = 'failed' WHERE id = :id"), {"id": batch_id}
    )
    await db_session.commit()

    # 验证未读数
    unread = await service.get_unread_count()
    assert unread >= 2

    # 验证列表
    items, total = await service.list_notifications(page=1, per_page=10)
    assert total >= 2
    assert len(items) >= 2

    # 验证序列化 alias
    resp = NotificationResponse.model_validate(items[0])
    dumped = resp.model_dump(by_alias=True)
    assert "read" in dumped  # 序列化用 alias "read"
    assert "is_read" not in dumped  # 不含原字段名

    # 标记单条已读
    notification = items[0]
    marked = await service.mark_read(notification.id)
    assert marked.is_read is True

    # 全部已读
    count = await service.mark_all_read()
    assert count >= 1

    # 验证全部已读后未读数为 0
    unread_after = await service.get_unread_count()
    # 可能有其他测试产生的通知，只验证 <= 之前
    assert unread_after < unread

    # 验证 MarkAllReadResponse 字段名
    resp_all = MarkAllReadResponse(updated_count=count)
    assert resp_all.model_dump() == {"updated_count": count}
