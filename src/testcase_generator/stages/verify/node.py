"""verify 节点 — grounding 事实核验关卡（review 之后、export 之前）

读取 final_test_cases + parsed_context，对每条用例对照 PRD 章节原文核验，
把 CaseVerification 回挂到用例，并产出分桶汇总。处置策略：isolate（剥离非主集）。
"""

from __future__ import annotations

import logging
from collections import defaultdict

from src.testcase_generator.schemas.parsed_context import ParsedContext
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.verify.verifier import (
    PrdSection,
    VerifyCase,
    summarize,
    verify_cases,
)

logger = logging.getLogger(__name__)


def _build_feature_sections(parsed_context: ParsedContext, feature_ids: set[str]) -> dict[str, list[PrdSection]]:
    """构建 feature_id → 对照用 PRD 章节原文（与 write_cases 的上下文映射口径一致）。"""
    by_feature: dict[str, list[PrdSection]] = defaultdict(list)
    generic: list[PrdSection] = []

    for source in parsed_context.sources:
        for section in source.sections:
            sec = PrdSection(
                heading=section.heading,
                content=section.content,
                source_ref=section.source_ref,
                section_kind=getattr(section, "section_kind", "spec"),
            )
            matched = False
            for feature in parsed_context.features:
                if section.source_ref in feature.source_refs:
                    by_feature[feature.id].append(sec)
                    matched = True
                    break
            if not matched and source.trust_level <= 2:
                generic.append(sec)

    # 通用规范/汇总章节（如 §6 投放方式表、§7 监测链接、§9 字段约束）对所有功能点可见
    for fid in feature_ids:
        by_feature[fid].extend(generic)
    return by_feature


async def verify_node(state: PipelineState) -> dict:
    """Stage: 对最终用例集逐条事实核验 + 分桶。"""
    parsed_context: ParsedContext = state["parsed_context"]
    test_points: list[TestPointSchema] = state.get("test_points", [])
    final_cases: list[GeneratedTestCase] = state.get("final_test_cases") or state.get("test_cases", [])

    tp_feature_of: dict[str, str] = {tp.id: tp.feature_id for tp in test_points}

    # 用稳定的位置键（V{i}）做核验映射，避免 c.id 在极端情况下重复导致结论错配
    verify_inputs: list[VerifyCase] = []
    keys: list[str] = []
    for i, c in enumerate(final_cases):
        key = f"V{i}"
        keys.append(key)
        feature_id = tp_feature_of.get(c.test_point_id, "")
        verify_inputs.append(
            VerifyCase(
                case_id=key,
                feature_id=feature_id,
                title=c.title,
                steps=[
                    {
                        "action": s.action,
                        "input_data": s.input_data,
                        "expected_result": s.expected_result,
                        "source_quote": s.source_quote,
                    }
                    for s in c.steps
                ],
                expected_results=c.expected_results,
                preconditions=c.preconditions,
                provenance_excerpt=c.provenance.verbatim_excerpt if c.provenance else None,
            )
        )

    feature_ids = {vi.feature_id for vi in verify_inputs if vi.feature_id}
    sections_by_feature = _build_feature_sections(parsed_context, feature_ids)

    verifications = await verify_cases(verify_inputs, sections_by_feature)

    # 回挂结论（按位置键映射）
    for c, key in zip(final_cases, keys):
        c.verification = verifications.get(key)

    summary = summarize(verifications)
    logger.info("verify_node: %s", summary)

    return {
        "final_test_cases": final_cases,
        "verify_summary": summary,
        "current_stage": "verify",
    }
