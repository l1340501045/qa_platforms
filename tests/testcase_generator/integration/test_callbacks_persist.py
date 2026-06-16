"""T048/T049 补强：真调 on_pipeline_complete + PersistService.archive_batch

守住那两个修过的落库 bug：
- on_pipeline_complete: test_point_id FK 映射（逻辑 ID → 真实 PK）
- archive_batch: 知识沉淀 + req_to_case 关联（source≠target，不触发 CHECK）
"""

import os
import pytest
from uuid import uuid4, UUID

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms")

from sqlalchemy import text
from src.platform_api.core.database import get_session_factory


# ─── Test: on_pipeline_complete 真调 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_pipeline_complete_real_fk_mapping():
    """真调 on_pipeline_complete：验证 test_point_id FK 映射正确

    覆盖的 bug：callback 里 test_point_id 逻辑 ID → 真实 PK 映射。
    如果映射坏了，test_cases.test_point_id 会为 NULL。
    """
    from src.testcase_generator.tasks.callbacks import on_pipeline_complete

    system_id = uuid4()
    doc_id = uuid4()
    batch_id = uuid4()

    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
            {"id": str(system_id), "name": f"cb_test_{system_id.hex[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge.documents (id, system_id, title, doc_type, trust_level, content, storage_path, content_hash, embedding_status, image_refs) "
                "VALUES (:id, :sid, 'CB测试需求', 'prd', 1, '内容', '/cb.md', :hash, 'done', '[]')"
            ),
            {"id": str(doc_id), "sid": str(system_id), "hash": uuid4().hex[:64]},
        )
        await session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) VALUES (:id, :did, :sid, 'running')"
            ),
            {"id": str(batch_id), "did": str(doc_id), "sid": str(system_id)},
        )
        await session.commit()

    # 构造测试点和用例数据（模拟流水线输出）
    test_points = [
        {
            "id": "TP-001",
            "feature_id": "F001",
            "dimension": "functional_correctness",
            "description": "测试点1",
            "priority": "P0",
            "derived_from": ["PRD §1"],
        },
        {
            "id": "TP-002",
            "feature_id": "F001",
            "dimension": "boundary_value",
            "description": "测试点2",
            "priority": "P0",
            "derived_from": ["PRD §1"],
        },
        {
            "id": "TP-003",
            "feature_id": "F002",
            "dimension": "error_handling",
            "description": "测试点3",
            "priority": "P1",
            "derived_from": ["PRD §2"],
        },
    ]

    final_cases = [
        {
            "test_point_id": "TP-001",
            "title": "用例A",
            "preconditions": [],
            "steps": [],
            "expected_results": [],
            "priority": "P0",
            "dimensions": ["functional_correctness"],
            "provenance": {},
            "trust_level": 1,
        },
        {
            "test_point_id": "TP-002",
            "title": "用例B",
            "preconditions": [],
            "steps": [],
            "expected_results": [],
            "priority": "P0",
            "dimensions": ["boundary_value"],
            "provenance": {},
            "trust_level": 1,
        },
        {
            "test_point_id": "TP-003",
            "title": "用例C",
            "preconditions": [],
            "steps": [],
            "expected_results": [],
            "priority": "P1",
            "dimensions": ["error_handling"],
            "provenance": {},
            "trust_level": 2,
        },
    ]

    audit_report = {"coverage": 1.0, "gaps": []}

    # 真调 on_pipeline_complete
    await on_pipeline_complete(
        batch_id=str(batch_id),
        final_cases=final_cases,
        audit_report=audit_report,
        test_points=test_points,
    )

    # 验证 DB
    async with session_factory() as session:
        # test_points 条数
        result = await session.execute(
            text("SELECT count(*) FROM testcase.test_points WHERE batch_id = :bid"), {"bid": str(batch_id)}
        )
        tp_count = result.scalar()
        assert tp_count == 3, f"test_points 应为 3, got {tp_count}"

        # test_cases 条数
        result = await session.execute(
            text("SELECT count(*) FROM testcase.test_cases WHERE batch_id = :bid"), {"bid": str(batch_id)}
        )
        tc_count = result.scalar()
        assert tc_count == 3, f"test_cases 应为 3, got {tc_count}"

        # 关键断言：每条 test_case.test_point_id 非空且指向真实 PK
        result = await session.execute(
            text("SELECT tc.title, tc.test_point_id FROM testcase.test_cases tc WHERE tc.batch_id = :bid"),
            {"bid": str(batch_id)},
        )
        for row in result.fetchall():
            title, tp_id = row
            assert tp_id is not None, f"用例 '{title}' 的 test_point_id 为 NULL（FK 映射坏了）"

        # 验证 FK 指向真实存在的 test_points
        result = await session.execute(
            text(
                "SELECT tc.title FROM testcase.test_cases tc "
                "LEFT JOIN testcase.test_points tp ON tc.test_point_id = tp.id "
                "WHERE tc.batch_id = :bid AND tp.id IS NULL"
            ),
            {"bid": str(batch_id)},
        )
        orphans = result.fetchall()
        assert len(orphans) == 0, f"FK 指向不存在的 test_point: {orphans}"

        # 验证 batch 状态更新为 pending_review
        result = await session.execute(
            text("SELECT status FROM testcase.test_batches WHERE id = :id"), {"id": str(batch_id)}
        )
        status = result.scalar()
        assert status == "pending_review", f"batch status 应为 pending_review, got {status}"


@pytest.mark.asyncio
async def test_on_pipeline_complete_persists_rules_and_resolves_rule_id():
    """Chunk 1 验收：规则台账落库 + test_points.rule_id 由规则码解析为 rules.id(uuid)。"""
    from src.testcase_generator.tasks.callbacks import on_pipeline_complete

    system_id = uuid4()
    doc_id = uuid4()
    batch_id = uuid4()

    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
            {"id": str(system_id), "name": f"rule_test_{system_id.hex[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge.documents (id, system_id, title, doc_type, trust_level, content, storage_path, content_hash, embedding_status, image_refs) "
                "VALUES (:id, :sid, '规则台账测试', 'prd', 1, '内容', '/r.md', :hash, 'done', '[]')"
            ),
            {"id": str(doc_id), "sid": str(system_id), "hash": uuid4().hex[:64]},
        )
        await session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) VALUES (:id, :did, :sid, 'running')"
            ),
            {"id": str(batch_id), "did": str(doc_id), "sid": str(system_id)},
        )
        await session.commit()

    rules = [
        {"rule_code": "R-001", "module": "5.1 授权", "rule": "高级别包含低级别", "source_quote": "q", "category": "权限"},
        {"rule_code": "R-002", "module": "5.1 授权", "rule": "变更实时生效", "source_quote": "q", "category": "状态"},
    ]
    test_points = [
        {"id": "TP-001", "feature_id": "F001", "dimension": "permission", "description": "tp1",
         "priority": "P0", "derived_from": ["PRD §1"], "rule_id": "R-001"},
        {"id": "TP-002", "feature_id": "F001", "dimension": "functional_correctness", "description": "tp2",
         "priority": "P1", "derived_from": ["PRD §1"]},  # 无 rule_id（维度增强测试点）
    ]
    final_cases = [
        {"test_point_id": "TP-001", "title": "用例A", "preconditions": [], "steps": [],
         "expected_results": [], "priority": "P0", "dimensions": ["permission"], "provenance": {}, "trust_level": 1},
    ]

    await on_pipeline_complete(
        batch_id=str(batch_id),
        final_cases=final_cases,
        audit_report={"coverage": 1.0},
        test_points=test_points,
        rules=rules,
    )

    async with session_factory() as session:
        # 规则台账落库
        result = await session.execute(
            text("SELECT rule_code, id FROM testcase.rules WHERE batch_id = :bid ORDER BY rule_code"),
            {"bid": str(batch_id)},
        )
        rule_rows = result.fetchall()
        assert len(rule_rows) == 2, f"规则台账应落 2 条, got {len(rule_rows)}"
        code_to_id = {r[0]: r[1] for r in rule_rows}

        # TP-001 的 rule_id 解析为 R-001 的真实 uuid；TP-002 为 NULL
        result = await session.execute(
            text("SELECT description, rule_id FROM testcase.test_points WHERE batch_id = :bid"),
            {"bid": str(batch_id)},
        )
        tp_rule = {row[0]: row[1] for row in result.fetchall()}
        assert str(tp_rule["tp1"]) == str(code_to_id["R-001"]), "TP-001.rule_id 未解析为 R-001 的 uuid"
        assert tp_rule["tp2"] is None, "维度增强测试点 rule_id 应为 NULL"


# ─── Test: PersistService.archive_batch 真调 ──────────────────────────────────


@pytest.mark.asyncio
async def test_archive_batch_real_linkage():
    """真调 PersistService.archive_batch：验证知识沉淀 + req_to_case 关联

    覆盖的 bug：archive_batch 不再自关联（source_doc_id ≠ target_doc_id）。
    """
    from src.testcase_generator.services.persist_service import PersistService

    system_id = uuid4()
    doc_id = uuid4()
    batch_id = uuid4()
    tc_ids = [uuid4() for _ in range(3)]

    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO public.systems (id, name) VALUES (:id, :name)"),
            {"id": str(system_id), "name": f"arch_test_{system_id.hex[:8]}"},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge.documents (id, system_id, title, doc_type, trust_level, content, storage_path, content_hash, embedding_status, image_refs) "
                "VALUES (:id, :sid, '归档测试需求', 'prd', 1, '需求内容', '/arch.md', :hash, 'done', '[]')"
            ),
            {"id": str(doc_id), "sid": str(system_id), "hash": uuid4().hex[:64]},
        )
        await session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) VALUES (:id, :did, :sid, 'pending_review')"
            ),
            {"id": str(batch_id), "did": str(doc_id), "sid": str(system_id)},
        )

        # 插入已确认的用例（archive 前提）
        for tc_id in tc_ids:
            await session.execute(
                text(
                    "INSERT INTO testcase.test_cases (id, batch_id, title, priority, review_status, "
                    "preconditions, steps, expected_results, dimensions, provenance, trust_level) "
                    "VALUES (:id, :bid, :title, 'P0', 'confirmed', '[]', '[]', '[]', '[]', '{}', 1)"
                ),
                {"id": str(tc_id), "bid": str(batch_id), "title": f"确认用例 {tc_id.hex[:6]}"},
            )

        await session.commit()

    # 真调 archive_batch
    persist = PersistService()
    await persist.archive_batch(batch_id)

    # 验证 DB
    async with session_factory() as session:
        # 1. batch 状态 → archived
        result = await session.execute(
            text("SELECT status FROM testcase.test_batches WHERE id = :id"), {"id": str(batch_id)}
        )
        assert result.scalar() == "archived"

        # 2. knowledge.documents 有沉淀行（doc_type=test_case）
        result = await session.execute(
            text("SELECT id, doc_type FROM knowledge.documents WHERE system_id = :sid AND doc_type = 'test_case'"),
            {"sid": str(system_id)},
        )
        settle_row = result.fetchone()
        assert settle_row is not None, "archive_batch 未创建知识沉淀文档"
        settle_doc_id = settle_row[0]
        assert settle_row[1] == "test_case"

        # 3. document_associations 有 req_to_case 关联
        result = await session.execute(
            text(
                "SELECT source_doc_id, target_doc_id, relation_type FROM knowledge.document_associations "
                "WHERE source_doc_id = :src AND target_doc_id = :tgt"
            ),
            {"src": str(doc_id), "tgt": str(settle_doc_id)},
        )
        assoc = result.fetchone()
        assert assoc is not None, "archive_batch 未建立 req_to_case 关联"
        assert assoc[2] == "req_to_case"

        # 关键断言：source ≠ target（不触发 CHECK）
        assert str(assoc[0]) != str(assoc[1]), f"自关联 bug 复发！source={assoc[0]} == target={assoc[1]}"
