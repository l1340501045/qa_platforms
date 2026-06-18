"""集成测试 — 用例树端到端验证

覆盖点：
1. 多文档分组正确
2. 多模块（source_section）分组正确
3. source_section 缺失归"未分类"
4. review_status=deleted 用例不出现
5. priority 筛选有效

真实 DB 连接，不 mock。
"""

import pytest
import uuid

from tests.platform_api.conftest import requires_db

pytestmark = requires_db

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session_factory
from src.platform_api.services.case_tree_service import CaseTreeService


@pytest.fixture
async def db_session():
    """获取真实 DB session"""
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seed_tree_data(db_session: AsyncSession):
    """创建用例树测试数据：2 文档 × 多模块"""
    system_id = uuid.uuid4()
    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()
    batch1_id = uuid.uuid4()
    batch2_id = uuid.uuid4()

    # system
    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"tree_test_{system_id.hex[:8]}"},
    )

    # 2 documents
    for doc_id, title in [(doc1_id, "文档A-首页"), (doc2_id, "文档B-播放器")]:
        await db_session.execute(
            text(
                "INSERT INTO knowledge.documents (id, system_id, title, doc_type, content, storage_path, content_hash) "
                "VALUES (:id, :sid, :title, 'prd', 'c', '/t', :hash)"
            ),
            {"id": doc_id, "sid": system_id, "title": title, "hash": uuid.uuid4().hex},
        )

    # 2 batches (completed)
    for bid, did in [(batch1_id, doc1_id), (batch2_id, doc2_id)]:
        await db_session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) "
                "VALUES (:id, :did, :sid, 'completed')"
            ),
            {"id": bid, "did": did, "sid": system_id},
        )

    # 用例数据：doc1 有 2 个模块, doc2 有 1 个模块 + 1 个无 source_section
    cases = [
        # doc1 - 模块"推荐列表"
        (
            uuid.uuid4(),
            batch1_id,
            "推荐列表-正常加载",
            "P0",
            "confirmed",
            '{"derived_from":"t","source_section":"推荐列表","trust_level":1}',
        ),
        (
            uuid.uuid4(),
            batch1_id,
            "推荐列表-空状态",
            "P1",
            "pending",
            '{"derived_from":"t","source_section":"推荐列表","trust_level":2}',
        ),
        # doc1 - 模块"搜索栏"
        (
            uuid.uuid4(),
            batch1_id,
            "搜索栏-关键词搜索",
            "P0",
            "confirmed",
            '{"derived_from":"t","source_section":"搜索栏","trust_level":1}',
        ),
        # doc1 - deleted（不应出现）
        (
            uuid.uuid4(),
            batch1_id,
            "已删除用例",
            "P0",
            "deleted",
            '{"derived_from":"t","source_section":"推荐列表","trust_level":1}',
        ),
        # doc2 - 模块"播放控制"
        (
            uuid.uuid4(),
            batch2_id,
            "播放-开始播放",
            "P0",
            "confirmed",
            '{"derived_from":"t","source_section":"播放控制","trust_level":1}',
        ),
        # doc2 - 缺 source_section → 归"未分类"
        (uuid.uuid4(), batch2_id, "其他功能测试", "P2", "pending", '{"derived_from":"t","trust_level":3}'),
    ]

    for cid, bid, title, priority, rs, prov in cases:
        await db_session.execute(
            text(
                "INSERT INTO testcase.test_cases "
                "(id, batch_id, title, preconditions, steps, expected_results, priority, dimensions, provenance, trust_level, review_status) "
                "VALUES (:id, :bid, :title, CAST(:preconds AS jsonb), CAST(:steps AS jsonb), "
                "CAST(:expected AS jsonb), :pri, CAST(:dims AS jsonb), CAST(:prov AS jsonb), 1, :rs)"
            ),
            {
                "id": cid,
                "bid": bid,
                "title": title,
                "pri": priority,
                "rs": rs,
                "prov": prov,
                "preconds": "[]",
                "steps": '[{"step_number":1,"action":"test"}]',
                "expected": '["ok"]',
                "dims": '["functional"]',
            },
        )

    await db_session.commit()

    yield {
        "system_id": system_id,
        "doc1_id": doc1_id,
        "doc2_id": doc2_id,
        "batch1_id": batch1_id,
        "batch2_id": batch2_id,
    }

    # Cleanup
    for bid in [batch1_id, batch2_id]:
        await db_session.execute(text("DELETE FROM testcase.test_cases WHERE batch_id = :bid"), {"bid": bid})
        await db_session.execute(text("DELETE FROM public.notifications WHERE target_id = :bid"), {"bid": bid})
        await db_session.execute(text("DELETE FROM testcase.test_batches WHERE id = :id"), {"id": bid})
    for did in [doc1_id, doc2_id]:
        await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": did})
    await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_case_tree_multi_document_grouping(db_session: AsyncSession, seed_tree_data):
    """用例树：多文档正确分组"""
    service = CaseTreeService(db_session)
    tree = await service.get_case_tree(system_id=seed_tree_data["system_id"])

    assert len(tree) == 2  # 2 个文档节点
    doc_titles = [node["document_title"] for node in tree]
    assert "文档A-首页" in doc_titles
    assert "文档B-播放器" in doc_titles


@pytest.mark.asyncio
async def test_case_tree_module_grouping(db_session: AsyncSession, seed_tree_data):
    """用例树：source_section 正确分为模块"""
    service = CaseTreeService(db_session)
    tree = await service.get_case_tree(system_id=seed_tree_data["system_id"])

    # 找 doc1
    doc1 = next(n for n in tree if n["document_title"] == "文档A-首页")
    module_names = [m["module_name"] for m in doc1["modules"]]

    assert "推荐列表" in module_names
    assert "搜索栏" in module_names

    # 推荐列表模块应有 2 条（deleted 的不计入）
    rec_module = next(m for m in doc1["modules"] if m["module_name"] == "推荐列表")
    assert rec_module["case_count"] == 2


@pytest.mark.asyncio
async def test_case_tree_missing_source_section_fallback(db_session: AsyncSession, seed_tree_data):
    """用例树：source_section 缺失归"未分类" """
    service = CaseTreeService(db_session)
    tree = await service.get_case_tree(system_id=seed_tree_data["system_id"])

    # 找 doc2
    doc2 = next(n for n in tree if n["document_title"] == "文档B-播放器")
    module_names = [m["module_name"] for m in doc2["modules"]]

    assert "播放控制" in module_names
    assert "未分类" in module_names

    # 未分类模块应有 1 条
    uncat = next(m for m in doc2["modules"] if m["module_name"] == "未分类")
    assert uncat["case_count"] == 1


@pytest.mark.asyncio
async def test_case_tree_excludes_deleted(db_session: AsyncSession, seed_tree_data):
    """用例树：review_status=deleted 的用例不出现"""
    service = CaseTreeService(db_session)
    tree = await service.get_case_tree(system_id=seed_tree_data["system_id"])

    # 收集所有 case title
    all_titles = []
    for doc in tree:
        for module in doc["modules"]:
            for case in module["cases"]:
                all_titles.append(case["title"])

    assert "已删除用例" not in all_titles


@pytest.mark.asyncio
async def test_case_tree_priority_filter(db_session: AsyncSession, seed_tree_data):
    """用例树：priority 筛选有效"""
    service = CaseTreeService(db_session)
    tree = await service.get_case_tree(system_id=seed_tree_data["system_id"], priority="P0")

    # 所有 case 的 priority 应为 P0
    for doc in tree:
        for module in doc["modules"]:
            for case in module["cases"]:
                assert case["priority"] == "P0"


@pytest.mark.asyncio
async def test_case_tree_includes_pending_review_batches(db_session: AsyncSession):
    """回归防护：pending_review 批次的用例必须出现在默认用例树中

    AI 生成流水线终态是 pending_review（待人工 review），
    用例此时已生成完毕，用例库必须展示。
    """
    system_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    case_id = uuid.uuid4()

    # 创建 system + document + pending_review 批次 + 用例
    await db_session.execute(
        text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
        {"id": system_id, "name": f"pending_review_test_{system_id.hex[:8]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge.documents (id, system_id, title, doc_type, content, storage_path, content_hash) "
            "VALUES (:id, :sid, :title, 'prd', 'c', '/t', :hash)"
        ),
        {"id": doc_id, "sid": system_id, "title": "待审阅文档", "hash": uuid.uuid4().hex},
    )
    await db_session.execute(
        text(
            "INSERT INTO testcase.test_batches (id, document_id, system_id, status, total_cases) "
            "VALUES (:id, :did, :sid, 'pending_review', 1)"
        ),
        {"id": batch_id, "did": doc_id, "sid": system_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO testcase.test_cases "
            "(id, batch_id, title, preconditions, steps, expected_results, priority, dimensions, provenance, trust_level, review_status) "
            'VALUES (:id, :bid, :title, \'[]\'::jsonb, \'[{"step_number":1,"action":"test"}]\'::jsonb, '
            "'[\"ok\"]'::jsonb, 'P0', '[\"functional\"]'::jsonb, "
            '\'{"derived_from":"t","source_section":"登录模块","trust_level":1}\'::jsonb, 1, \'pending\')'
        ),
        {"id": case_id, "bid": batch_id, "title": "pending_review批次用例"},
    )
    await db_session.commit()

    try:
        # 核心断言：默认查询（不传 batch_id）应返回 pending_review 批次的用例
        service = CaseTreeService(db_session)
        tree = await service.get_case_tree(system_id=system_id)

        assert len(tree) == 1, f"应有 1 个文档节点，实际 {len(tree)}"
        assert tree[0]["document_title"] == "待审阅文档"

        all_cases = []
        for doc in tree:
            for module in doc["modules"]:
                all_cases.extend(module["cases"])

        assert len(all_cases) == 1
        assert all_cases[0]["title"] == "pending_review批次用例"
    finally:
        # Cleanup
        await db_session.execute(text("DELETE FROM testcase.test_cases WHERE batch_id = :bid"), {"bid": batch_id})
        await db_session.execute(text("DELETE FROM public.notifications WHERE target_id = :bid"), {"bid": batch_id})
        await db_session.execute(text("DELETE FROM testcase.test_batches WHERE id = :id"), {"id": batch_id})
        await db_session.execute(text("DELETE FROM knowledge.documents WHERE id = :id"), {"id": doc_id})
        await db_session.execute(text("DELETE FROM public.systems WHERE id = :id"), {"id": system_id})
        await db_session.commit()
