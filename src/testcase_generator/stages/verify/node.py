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
from src.testcase_generator.stages.context_utils import (
    collect_global_sections,
    CrossFeatureIndex,
)
from src.testcase_generator.stages.verify.verifier import (
    PrdSection,
    VerifyCase,
    summarize,
    verify_cases,
)

logger = logging.getLogger(__name__)


async def _build_feature_sections(
    parsed_context: ParsedContext,
    feature_ids: set[str],
    feature_query: dict[str, str] | None = None,
) -> dict[str, list[PrdSection]]:
    """构建 feature_id → 对照用 PRD 章节原文（与 write_cases 的上下文映射口径一致）。"""
    by_feature: dict[str, list[PrdSection]] = defaultdict(list)
    generic: list[PrdSection] = []
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)

    def _add(fid: str, sec: PrdSection) -> None:
        key = (sec.source_ref or "", sec.heading or "")
        if key in seen[fid]:
            return
        seen[fid].add(key)
        by_feature[fid].append(sec)

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
                    _add(feature.id, sec)
                    matched = True
                    break
            if not matched and source.trust_level <= 2:
                generic.append(sec)

    # 通用/汇总章节（未匹配到任何功能点的 PRD/技术文档）对所有功能点可见
    for fid in feature_ids:
        for sec in generic:
            _add(fid, sec)

    # 全局/常驻章节（§5.0 全局规则、投放方式、监测链接、字段约束、字数等）无条件注入
    # 每个功能点 —— 与 write_cases 口径一致，修复 §5.0 已定义行为被误判 needs_spec 的根因。
    for gs in collect_global_sections(parsed_context):
        sec = PrdSection(
            heading=gs.heading,
            content=gs.content,
            source_ref=gs.source_ref,
            section_kind=gs.section_kind,
        )
        for fid in feature_ids:
            _add(fid, sec)

    # 跨功能点规格检索注入（与 write_cases 口径一致，治"假阴性空壳"根因 A2）：
    # 核验时也要看到"被折到别处的规格"，否则会把据此写的确定断言误判 ungrounded/undefined。
    if feature_query:
        cross_index = await CrossFeatureIndex.build(parsed_context)
        for fid in feature_ids:
            q = feature_query.get(fid, "")
            if not q:
                continue
            for cs in await cross_index.query(q, seen[fid], top_k=3):
                _add(
                    fid,
                    PrdSection(
                        heading=cs.heading,
                        content=cs.content,
                        source_ref=cs.source_ref,
                        section_kind=cs.section_kind,
                    ),
                )
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
    # 每个功能点的检索 query = 其测试点描述（与 write_cases 同口径），驱动跨功能点规格召回
    feature_query: dict[str, str] = defaultdict(str)
    for tp in test_points:
        feature_query[tp.feature_id] += f"{tp.dimension} {tp.description}\n"
    sections_by_feature = await _build_feature_sections(parsed_context, feature_ids, dict(feature_query))

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
