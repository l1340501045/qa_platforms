"""dedup 节点 — 全量用例近重复标记（verify 之后、export 之前）。

在全量 final_test_cases 上聚类，标记 duplicate_of（不删除），产出 dedup_summary。
safe_dedup_enabled 开时启用规则锚定护栏：绝不删某规则最后一条非重复用例。
"""

from __future__ import annotations

import logging

from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient
from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
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

    # 规则锚点回填：case.test_point_id → tp.rule_id。GeneratedTestCase 无 rule_id
    # 字段，须经测试点回查（与 backfill / review 的口径完全一致）。同一测试点可能
    # 没有 rule_id（维度增强 TP），其用例的 rule_codes 为空 → 不进入护栏检查。
    test_points: list[TestPointSchema] = state.get("test_points", [])
    tp_to_rule: dict[str, str] = {tp.id: tp.rule_id for tp in test_points if tp.rule_id}

    dedup_inputs = [
        DedupCase(
            case_id=c.id,
            feature_id=c.test_point_id or "",
            title=c.title,
            text=" ".join(c.expected_results or []),
            is_placeholder=_is_placeholder(c),
            dimension=" ".join(c.dimensions or []),
            rule_codes=[tp_to_rule[c.test_point_id]] if c.test_point_id in tp_to_rule else [],
        )
        for c in final_cases
    ]

    # 语义去重：semantic_dedup_enabled 时算各用例 embedding（title + expected_results
    # 拼接）传入 find_duplicates，抓词面抓不到的换措辞同义近重复。embedding 调用失败
    # → 降级为纯词面（warning，不阻断 dedup）。向量在 node 外部算好传入，find_duplicates
    # 仍纯同步可离线单测。
    embeddings: dict[str, list[float]] | None = None
    if settings.semantic_dedup_enabled and final_cases:
        texts = [
            (c.title or "") + " " + " ".join(c.expected_results or []) for c in final_cases
        ]
        try:
            vectors = await EmbeddingClient().embed_batch(texts)
            embeddings = {
                c.id: v for c, v in zip(final_cases, vectors, strict=False) if v
            }
        except Exception as e:
            logger.warning("dedup_node: embedding 失败，降级纯词面去重: %s", e)
            embeddings = None

    dup_map = find_duplicates(
        dedup_inputs,
        safe_dedup_enabled=settings.safe_dedup_enabled,
        embeddings=embeddings,
        semantic_threshold=settings.semantic_dedup_threshold,
        semantic_cross_tp_threshold=settings.semantic_dedup_cross_tp_threshold,
    )

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
