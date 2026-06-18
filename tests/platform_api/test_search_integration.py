"""集成测试 — 搜索端到端验证

覆盖点：
1. 触发器 010：INSERT test_cases 后 steps_text 自动填充
2. 新插入的用例能被搜索命中（不只是 009 回填的存量）
3. word_similarity 阈值 > 0.3 正常工作（短关键词搜长文本，精度与召回平衡）
4. 返回字段完整：document_id / batch_id / created_at / system_name / score
5. review_status=deleted 用例不出现在结果中

真实 DB 连接，不 mock。
"""

import pytest
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.services.case_search_service import CaseSearchService


@pytest.fixture
async def db_session():
    """获取真实 DB session"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seed_searchable_cases(db_session: AsyncSession):
    """创建可搜索的测试用例数据"""
    system_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    case_ids = [uuid.uuid4() for _ in range(4)]

    # 创建 system + document + batch
    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"搜索测试系统_{system_id.hex[:8]}"},
    )

    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents (id, system_id, title, doc_type, content, storage_path, content_hash) "
            "VALUES (:id, :sid, :title, 'prd', 'content', '/test', :hash)"
        ),
        {"id": doc_id, "sid": system_id, "title": "搜索测试文档", "hash": uuid.uuid4().hex},
    )

    await db_session.execute(
        text(
            "INSERT INTO testcase.test_batches (id, document_id, system_id, status, total_cases) "
            "VALUES (:id, :did, :sid, 'completed', 4)"
        ),
        {"id": batch_id, "did": doc_id, "sid": system_id},
    )

    # 插入用例（NOT setting steps_text — 由触发器自动计算）
    cases = [
        (
            case_ids[0],
            "登录验证-正确密码登录成功",
            '[{"step_number":1,"action":"输入用户名admin"},{"step_number":2,"action":"点击登录按钮"}]',
            "P0",
            "confirmed",
        ),
        (
            case_ids[1],
            "登录验证-密码错误提示",
            '[{"step_number":1,"action":"输入错误密码"},{"step_number":2,"action":"点击登录按钮"}]',
            "P0",
            "pending",
        ),
        (
            case_ids[2],
            "首页推荐列表加载",
            '[{"step_number":1,"action":"打开首页"},{"step_number":2,"action":"下拉刷新推荐列表"}]',
            "P1",
            "confirmed",
        ),
        (case_ids[3], "已删除用例不应出现", '[{"step_number":1,"action":"登录验证删除测试"}]', "P0", "deleted"),
    ]

    for cid, title, steps, priority, review_status in cases:
        await db_session.execute(
            text(
                "INSERT INTO testcase.test_cases "
                "(id, batch_id, title, preconditions, steps, expected_results, priority, dimensions, provenance, trust_level, review_status) "
                "VALUES (:id, :bid, :title, CAST(:preconds AS jsonb), CAST(:steps AS jsonb), CAST(:expected AS jsonb), :priority, "
                "CAST(:dims AS jsonb), CAST(:prov AS jsonb), 1, :rs)"
            ),
            {
                "id": cid,
                "bid": batch_id,
                "title": title,
                "steps": steps,
                "priority": priority,
                "rs": review_status,
                "preconds": "[]",
                "expected": '["success"]',
                "dims": '["functional"]',
                "prov": '{"derived_from":"test","source_section":"登录模块","trust_level":1}',
            },
        )

    await db_session.commit()

    yield {
        "system_id": system_id,
        "doc_id": doc_id,
        "batch_id": batch_id,
        "case_ids": case_ids,
    }

    # Cleanup
    await db_session.execute(text("DELETE FROM testcase.test_cases WHERE batch_id = :bid"), {"bid": batch_id})
    await db_session.execute(text("DELETE FROM testcase.test_batches WHERE id = :id"), {"id": batch_id})
    await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": doc_id})
    await db_session.execute(text("DELETE FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_trigger_fills_steps_text_on_insert(db_session: AsyncSession, seed_searchable_cases):
    """触发器 010：INSERT 后 steps_text 自动有值"""
    batch_id = seed_searchable_cases["batch_id"]

    result = await db_session.execute(
        text("SELECT title, steps_text FROM testcase.test_cases WHERE batch_id = :bid AND review_status != 'deleted'"),
        {"bid": batch_id},
    )
    rows = result.all()

    assert len(rows) == 3
    for title, steps_text in rows:
        assert steps_text is not None, f"steps_text is NULL for {title}"
        assert title in steps_text, f"steps_text should contain title"
        assert len(steps_text) > len(title), f"steps_text should include actions beyond title"


@pytest.mark.asyncio
async def test_search_finds_newly_inserted_cases(db_session: AsyncSession, seed_searchable_cases):
    """新插入用例（走触发器）能被搜索命中"""
    service = CaseSearchService(db_session)

    items, total = await service.search_cases(query="登录验证", page=1, per_page=10)

    assert total >= 2  # 至少匹配"登录验证-正确密码"和"登录验证-密码错误"
    titles = [item["title"] for item in items]
    assert any("登录验证" in t for t in titles)


@pytest.mark.asyncio
async def test_search_excludes_deleted_cases(db_session: AsyncSession, seed_searchable_cases):
    """review_status=deleted 的用例不出现在搜索结果"""
    service = CaseSearchService(db_session)

    items, total = await service.search_cases(query="登录验证删除测试", page=1, per_page=10)

    titles = [item["title"] for item in items]
    assert "已删除用例不应出现" not in titles


@pytest.mark.asyncio
async def test_search_result_contains_required_fields(db_session: AsyncSession, seed_searchable_cases):
    """搜索结果包含契约要求的所有字段"""
    service = CaseSearchService(db_session)

    items, total = await service.search_cases(query="登录验证", page=1, per_page=10)

    assert len(items) > 0
    item = items[0]

    # 契约 §3.8 要求的字段
    required_fields = [
        "id",
        "title",
        "priority",
        "trust_level",
        "review_status",
        "system_id",
        "system_name",
        "document_id",
        "document_title",
        "batch_id",
        "score",
        "created_at",
    ]
    for field in required_fields:
        assert field in item, f"Missing required field: {field}"

    # trust_level 是整数 1-5
    assert isinstance(item["trust_level"], int)
    assert 1 <= item["trust_level"] <= 5

    # score 是浮点数
    assert isinstance(item["score"], float)
    assert 0 < item["score"] <= 1


@pytest.mark.asyncio
async def test_search_filters_by_system_id(db_session: AsyncSession, seed_searchable_cases):
    """搜索支持 system_id 筛选"""
    service = CaseSearchService(db_session)
    system_id = seed_searchable_cases["system_id"]

    items, total = await service.search_cases(query="登录验证", system_id=system_id, page=1, per_page=10)

    assert total >= 2
    for item in items:
        assert item["system_id"] == system_id


@pytest.mark.asyncio
async def test_search_filters_by_priority(db_session: AsyncSession, seed_searchable_cases):
    """搜索支持 priority 筛选"""
    service = CaseSearchService(db_session)

    items, total = await service.search_cases(query="首页推荐", priority="P1", page=1, per_page=10)

    for item in items:
        assert item["priority"] == "P1"
