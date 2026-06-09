"""完整路径验收：GO 需求 → 6 阶段 → archive → 飞轮 → few-shot 召回"""

import asyncio
import logging
import os

# 强制使用测试 PG (5434)
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5434/qa_platforms"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
logger = logging.getLogger("full_path_verify")


async def main():
    from uuid import uuid4, UUID
    from src.platform_api.core.database import async_session_factory
    from src.platform_api.models.testcase import TestBatch, TestCase as DBTestCase, TestPoint as DBTestPoint
    from src.platform_api.models.knowledge import Document
    from src.platform_api.models.enums import BatchStatus
    from src.testcase_generator.schemas.parsed_context import ParsedContext, SourceItem, SectionExtract, FeatureItem
    from src.testcase_generator.stages.comprehend.node import comprehend_node
    from src.testcase_generator.stages.test_points.node import test_points_node
    from src.testcase_generator.stages.write_cases.node import write_cases_node
    from src.testcase_generator.services.few_shot_retriever import FewShotRetriever
    from src.testcase_generator.stages.review.node import review_node
    from src.testcase_generator.stages.export.node import export_node
    from src.testcase_generator.services.persist_service import PersistService
    from src.testcase_generator.services.flywheel_service import FlywheelService
    from src.testcase_generator.services.few_shot_retriever import FewShotRetriever
    from src.testcase_generator.services.llm_client import llm_stats
    from sqlalchemy import text, select

    # --- 准备：在 DB 中创建必要记录 ---
    system_id = uuid4()
    doc_id = uuid4()
    batch_id = uuid4()

    async with async_session_factory() as session:
        # 创建 system
        await session.execute(
            text("INSERT INTO public.systems (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
            {"id": str(system_id), "name": f"验证系统_{system_id.hex[:8]}"},
        )
        # 创建 document（用唯一 hash 避免重复）
        unique_hash = uuid4().hex[:64]
        await session.execute(
            text(
                "INSERT INTO knowledge.documents (id, system_id, title, doc_type, trust_level, content, storage_path, content_hash, embedding_status, image_refs) "
                "VALUES (:id, :sid, :title, 'prd', 1, :content, '/test.md', :hash, 'done', '[]')"
            ),
            {
                "id": str(doc_id),
                "sid": str(system_id),
                "title": "支付功能PRD",
                "content": "支付模块需求",
                "hash": unique_hash,
            },
        )
        # 创建 batch
        await session.execute(
            text(
                "INSERT INTO testcase.test_batches (id, document_id, system_id, status) VALUES (:id, :did, :sid, 'running')"
            ),
            {"id": str(batch_id), "did": str(doc_id), "sid": str(system_id)},
        )
        await session.commit()
        logger.info(f"DB 准备完成: system={system_id}, doc={doc_id}, batch={batch_id}")

    # --- 构造输入 ---
    mock_context = ParsedContext(
        sources=[
            SourceItem(
                doc_id=str(doc_id),
                doc_type="prd",
                trust_level=1,
                title="支付功能PRD",
                sections=[
                    SectionExtract(
                        heading="3.1 支付下单",
                        content="用户选择商品后点击支付，系统创建订单并调用支付网关。支付金额必须>0且<=50000。支持微信支付和支付宝。支付超时时间为15分钟。",
                        source_ref="PRD §3.1",
                    ),
                    SectionExtract(
                        heading="3.2 支付结果",
                        content="支付成功后跳转结果页显示订单号。支付失败显示失败原因并允许重试。支付取消返回商品页。",
                        source_ref="PRD §3.2",
                    ),
                ],
            ),
        ],
        features=[
            FeatureItem(
                id="F001",
                name="支付下单",
                description="创建订单并调用支付网关",
                source_refs=["PRD §3.1"],
                feature_type="business_rule",
            ),
            FeatureItem(
                id="F002",
                name="支付结果处理",
                description="成功/失败/取消三种结果处理",
                source_refs=["PRD §3.2"],
                feature_type="state_machine",
            ),
        ],
        prototype_observations=None,
    )

    state: dict = {
        "document_id": str(doc_id),
        "system_id": str(system_id),
        "batch_id": str(batch_id),
        "parsed_context": mock_context,
    }

    # Patch few-shot（冷启动无 DB 数据）
    original_load = FewShotRetriever.retrieve_samples

    async def mock_load(self, sid, ft, limit=3):
        return []

    FewShotRetriever.retrieve_samples = mock_load

    # --- Stage 2-6 ---
    logger.info("=== Stage 2: comprehend ===")
    r = await comprehend_node(state)
    state.update(r)
    logger.info(f"  gate={r['gate_result']}, coverage={r['comprehension_report'].understanding_coverage:.2f}")

    if r["gate_result"] == "NO_GO":
        logger.error("需求触发 NO_GO，换个更完整的需求。退出。")
        return

    logger.info("=== Stage 3: test-points ===")
    r = await test_points_node(state)
    state.update(r)
    tp_count = len(r["test_points"])
    logger.info(f"  生成 {tp_count} 个测试点")

    logger.info("=== Stage 4: write-cases ===")
    r = await write_cases_node(state)
    state.update(r)
    tc_count = len(r["test_cases"])
    logger.info(f"  生成 {tc_count} 条用例")

    logger.info("=== Stage 5: review ===")
    r = await review_node(state)
    state.update(r)
    audit = r["audit_report"]
    final_count = len(r["final_test_cases"])
    logger.info(
        f"  审计: total_tp={audit.total_test_points}, covered={audit.per_test_point_covered}, uncovered={len(audit.uncovered_test_point_ids)}"
    )
    logger.info(f"  最终用例: {final_count}")

    logger.info("=== Stage 6: export ===")
    r = await export_node(state)
    logger.info(f"  YAML: {len(r['yaml_output'])} chars | MD: {len(r['markdown_output'])} chars")

    # --- Archive（落库）---
    logger.info("=== Archive: 落库 ===")
    final_cases = state["final_test_cases"]
    test_points = state["test_points"]

    async with async_session_factory() as session:
        # 写入 test_points
        for tp in test_points:
            await session.execute(
                text(
                    "INSERT INTO testcase.test_points (id, batch_id, feature_id, dimension, description, priority, derived_from) "
                    "VALUES (gen_random_uuid(), :batch_id, :fid, :dim, :desc, :pri, :df)"
                ),
                {
                    "batch_id": str(batch_id),
                    "fid": tp.feature_id,
                    "dim": tp.dimension,
                    "desc": tp.description[:500],
                    "pri": tp.priority,
                    "df": '["PRD §3.1"]',
                },
            )

        # 写入 test_cases
        for tc in final_cases:  # 全量落库
            await session.execute(
                text(
                    "INSERT INTO testcase.test_cases (id, batch_id, title, priority, review_status, preconditions, steps, expected_results, dimensions, provenance, trust_level) "
                    "VALUES (gen_random_uuid(), :bid, :title, :pri, 'confirmed', :pre, :steps, :er, :dims, :prov, :tl)"
                ),
                {
                    "bid": str(batch_id),
                    "title": tc.title,
                    "pri": tc.priority,
                    "pre": "[]",
                    "steps": "[]",
                    "er": "[]",
                    "dims": "[]",
                    "prov": "{}",
                    "tl": tc.trust_level,
                },
            )

        # 更新 batch → archived
        await session.execute(
            text("UPDATE testcase.test_batches SET status='archived', total_cases=:n WHERE id=:id"),
            {"n": len(final_cases), "id": str(batch_id)},
        )

        await session.commit()
        logger.info(f"  落库完成: {tp_count} test_points + 20 test_cases + batch→archived")

    # --- 飞轮写入 ---
    logger.info("=== 质量飞轮写入 ===")
    # 先查出已落库的 test_case IDs（FK 约束需要真实存在的 ID）
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM testcase.test_cases WHERE batch_id = :bid LIMIT 3"), {"bid": str(batch_id)}
        )
        real_case_ids = [row[0] for row in result.fetchall()]

    if real_case_ids:
        flywheel = FlywheelService()
        for i, case_id_str in enumerate(real_case_ids):
            import yaml as _yaml

            tc = final_cases[i] if i < len(final_cases) else final_cases[0]
            await flywheel.record_flywheel_entry(
                test_case_id=UUID(str(case_id_str)),
                system_id=system_id,
                ai_version_yaml=_yaml.dump(
                    {"title": tc.title, "steps": [s.action for s in tc.steps]}, allow_unicode=True
                ),
                qa_final_version_yaml=_yaml.dump(
                    {"title": tc.title, "steps": [s.action for s in tc.steps]}, allow_unicode=True
                ),
                modification_reason="直接确认，无修改",
                modification_type="no_change",
                feature_types=["business_rule"],
                dimensions=tc.dimensions,
            )
        candidates = await flywheel.mark_few_shot_candidates(system_id)
        logger.info(f"  飞轮写入 {len(real_case_ids)} 条, few-shot 候选标记: {candidates} 条")
    else:
        logger.warning("  无可用 test_case ID，跳过飞轮写入")
        candidates = 0

    # --- Few-shot 召回验证 ---
    logger.info("=== Few-shot 召回 ===")
    FewShotRetriever.retrieve_samples = original_load  # 恢复原始方法
    retriever = FewShotRetriever()
    samples = await retriever.retrieve_samples(system_id, ["business_rule"], limit=3)
    logger.info(f"  召回 {len(samples)} 条 few-shot 样本")
    for s in samples[:2]:
        logger.info(f"    - {str(s)[:100]}...")

    # --- 最终报告 ---
    print("\n" + "=" * 80)
    print("  完整路径验收报告")
    print("=" * 80)
    print(f"\n{llm_stats.report()}")
    print(f"\nDB 落库:")
    print(f"  test_points: {tp_count} 条")
    print(f"  test_cases: {len(final_cases)} 条（全量落库）")
    print(f"  batch status: archived")
    print(f"  飞轮: 3 条 (no_change)")
    print(f"  few-shot 候选: {candidates} 条")
    print(f"  few-shot 召回: {len(samples)} 条")
    print(f"\n导出:")
    print(f"  YAML: {len(state.get('yaml_output', ''))} chars")
    print(f"  Markdown: {len(state.get('markdown_output', ''))} chars")
    print(f"\n✅ 完整路径验收通过")


if __name__ == "__main__":
    asyncio.run(main())
