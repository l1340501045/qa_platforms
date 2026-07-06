"""reverify_batch.py — 对指定 batch 仅重跑 verify→dedup→落库（验证脚手架，不进主流程）

用途：让已完成 batch 的 cross_section_conflict 数据透出，仅用于数据修复/验证。
不改主流程 retry 语义，不重新生成测试用例；仅重跑 verify→dedup→落库。

用法：
    uv run python scripts/reverify_batch.py <batch_id>

⚠️  注意：
- 运行会**删除**该 batch 的旧 test_cases/test_points/rules 再重新落库。
  (on_pipeline_complete 是纯 INSERT，不清旧会重复插入 3185→6370 条)。
  删除操作在 verify+dedup **成功之后**才执行，防止 LLM 失败时旧数据意外丢失。
- 需要 .env 配置 DATABASE_URL（Postgres）和 LLM_BASE_URL/KEY。
- 脚本直接调用节点函数，不经 Celery，方便本地验证。

only-for-verification: 不接入 API/正常 retry 流程。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def _clear_old_records(batch_id_str: str) -> tuple[int, int, int]:
    """删该 batch 旧 test_cases/test_points/rules（防 on_pipeline_complete 重复插入）。"""
    import uuid

    from sqlalchemy import delete, func, select

    from src.platform_api.models.testcase import Rule, TestCase, TestPoint
    from src.testcase_generator.db import async_session_factory

    batch_uuid = uuid.UUID(batch_id_str)
    async with async_session_factory() as session:
        # 统计旧数量（供打印）
        def _count(model, col):
            return select(func.count()).select_from(model).where(col == batch_uuid)

        tc_n = (await session.execute(_count(TestCase, TestCase.batch_id))).scalar_one()
        tp_n = (await session.execute(_count(TestPoint, TestPoint.batch_id))).scalar_one()
        r_n = (await session.execute(_count(Rule, Rule.batch_id))).scalar_one()

        await session.execute(delete(TestCase).where(TestCase.batch_id == batch_uuid))
        await session.execute(delete(TestPoint).where(TestPoint.batch_id == batch_uuid))
        await session.execute(delete(Rule).where(Rule.batch_id == batch_uuid))
        await session.commit()

    return tc_n, tp_n, r_n


async def main(batch_id: str) -> None:
    from src.testcase_generator.pipeline.persistence import open_async_checkpointer
    from src.testcase_generator.pipeline.runner import compile_pipeline
    from src.testcase_generator.schemas.parsed_context import ParsedContext
    from src.testcase_generator.stages.dedup.node import dedup_node
    from src.testcase_generator.stages.verify.node import verify_node
    from src.testcase_generator.tasks.callbacks import on_pipeline_complete

    run_config = {"configurable": {"thread_id": batch_id}}

    # ── 1. 从 checkpoint 加载完整 PipelineState ────────────────────────────────
    print(f"[1/5] 加载 batch {batch_id} 的 checkpoint …")
    async with open_async_checkpointer() as checkpointer:
        app = compile_pipeline(checkpointer=checkpointer)
        snapshot = await app.aget_state(run_config)

    if not snapshot.values:
        print(f"ERROR: checkpoint 不存在（batch={batch_id}），请确认 batch_id 正确且 Postgres 可达。")
        sys.exit(1)

    state: dict = dict(snapshot.values)
    final_cases_orig = state.get("final_test_cases") or []
    test_points = state.get("test_points") or []
    rules = state.get("rules") or []
    print(
        f"  已加载：final_test_cases={len(final_cases_orig)}, "
        f"test_points={len(test_points)}, rules={len(rules)}"
    )

    if not final_cases_orig:
        print("ERROR: checkpoint 内 final_test_cases 为空，无法重跑 verify。")
        sys.exit(1)

    # 类型守卫：_PIPELINE_SERDE 白名单外顶层类型会静默降级为 dict；
    # 在清旧数据之前 fail-fast，避免删了旧数据但 verify 中途 AttributeError 造成不可恢复空窗。
    if not isinstance(state.get("parsed_context"), ParsedContext):
        print(
            f"ERROR: checkpoint parsed_context 降级为 {type(state.get('parsed_context')).__name__}，"
            "疑似白名单未覆盖/类路径变更，中止以免误删旧数据。"
        )
        sys.exit(1)

    # ── 2. 重跑 verify_node（调 LLM，约几刀）────────────────────────────────
    print("[2/5] 重跑 verify_node（调 LLM 核验）…")
    verify_result = await verify_node(state)
    state.update(verify_result)
    verify_summary = state.get("verify_summary", {})
    print(
        f"  verify 完成：total={verify_summary.get('total', '?')}, "
        f"cross_section_conflicts={verify_summary.get('cross_section_conflicts', 0)}"
    )

    # ── 3. 重跑 dedup_node ────────────────────────────────────────────────────
    print("[3/5] 重跑 dedup_node …")
    dedup_result = await dedup_node(state)
    state.update(dedup_result)
    dedup_summary = state.get("dedup_summary", {})
    print(
        f"  dedup 完成：total={dedup_summary.get('total', '?')}, "
        f"duplicates={dedup_summary.get('duplicate_count', 0)}"
    )

    # ── 4. 清旧数据（verify+dedup 均成功后才删，防数据空窗）──────────────────
    print("[4/5] 清除旧 test_cases/test_points/rules …")
    tc_n, tp_n, r_n = await _clear_old_records(batch_id)
    print(f"  已删：test_cases={tc_n}, test_points={tp_n}, rules={r_n}")

    # ── 5. 落库 ───────────────────────────────────────────────────────────────
    print("[5/5] 落库（on_pipeline_complete）…")
    final_cases_new = state.get("final_test_cases") or []
    audit_report = state.get("audit_report")
    audit_dict: dict = {}
    if audit_report is not None:
        audit_dict = audit_report.model_dump() if hasattr(audit_report, "model_dump") else audit_report

    await on_pipeline_complete(
        batch_id=batch_id,
        final_cases=[c.model_dump() if hasattr(c, "model_dump") else c for c in final_cases_new],
        audit_report=audit_dict,
        test_points=[tp.model_dump() if hasattr(tp, "model_dump") else tp for tp in test_points],
        rules=[r.model_dump() if hasattr(r, "model_dump") else r for r in rules],
    )

    # ── 摘要 ─────────────────────────────────────────────────────────────────
    conflict_cases = sum(
        1
        for c in final_cases_new
        if hasattr(c, "verification")
        and c.verification is not None
        and getattr(c.verification, "cross_section_conflict", False)
    )
    print(
        f"\n✓ 完成 batch={batch_id}\n"
        f"  落库用例数: {len(final_cases_new)}\n"
        f"  cross_section_conflict=True 的用例: {conflict_cases}\n"
        f"  (日志中 cross_section_conflicts 计数: {verify_summary.get('cross_section_conflicts', 0)})\n"
        f"\n请用 audit_export.py 复核：\n"
        f"  uv run python scripts/audit_export.py {batch_id}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run python scripts/reverify_batch.py <batch_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
