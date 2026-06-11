"""dedup 节点 — 全量用例近重复标记（verify 之后、export 之前）。

在全量 final_test_cases 上聚类，标记 duplicate_of（不删除），产出 dedup_summary。
"""

from __future__ import annotations

import logging

from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates

logger = logging.getLogger(__name__)


async def dedup_node(state: PipelineState) -> dict:
    """对最终用例集做全局近重复标记。"""
    final_cases: list[GeneratedTestCase] = state.get("final_test_cases") or state.get("test_cases", [])

    # 兜底：保证逻辑 id 全局唯一（任何上游撞号都会让自引用 duplicate_of 落库时违反外键）。
    # 逻辑 id 不入库为列，仅用于 dedup/落库内部映射，重排无副作用。
    seen: set[str] = set()
    collided = False
    for c in final_cases:
        if not c.id or c.id in seen:
            collided = True
            break
        seen.add(c.id)
    if collided:
        for i, c in enumerate(final_cases, start=1):
            c.id = f"TC-{i:04d}"
        logger.warning("dedup_node: 检测到用例 id 撞号/缺失，已统一重排为全局唯一 id（%d 条）", len(final_cases))

    def _is_placeholder(c: GeneratedTestCase) -> bool:
        if "需求待确认" in (c.title or ""):
            return True
        exp = " ".join(c.expected_results or [])
        return "PRD" in exp and "未定义" in exp and "待" in exp and "澄清" in exp

    dedup_inputs = [
        DedupCase(
            case_id=c.id,
            feature_id=c.test_point_id or "",
            title=c.title,
            text=" ".join(c.expected_results or []),
            is_placeholder=_is_placeholder(c),
        )
        for c in final_cases
    ]
    dup_map = find_duplicates(dedup_inputs)

    for c in final_cases:
        c.duplicate_of = dup_map.get(c.id)

    # 统计：去重簇数、重复条数
    canonical_ids = set(dup_map.values())
    summary = {
        "total": len(final_cases),
        "duplicate_count": len(dup_map),
        "cluster_count": len(canonical_ids),
        "unique_after_dedup": len(final_cases) - len(dup_map),
    }
    logger.info("dedup_node: %s", summary)

    return {
        "final_test_cases": final_cases,
        "dedup_summary": summary,
        "current_stage": "dedup",
    }
