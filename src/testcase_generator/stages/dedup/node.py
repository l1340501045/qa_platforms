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

    dedup_inputs = [
        DedupCase(
            case_id=c.id,
            feature_id=c.test_point_id or "",
            title=c.title,
            text=" ".join(c.expected_results or []),
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
