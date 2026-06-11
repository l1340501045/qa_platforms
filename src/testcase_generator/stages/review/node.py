"""T030: review 节点 — LLM 覆盖审计（对比 test_points 与 test_cases 的维度覆盖）"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.schemas.audit_report import AuditReport, CoverageGap
from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)

_DIMENSIONS_PATH = Path(__file__).resolve().parents[2] / "config" / "dimensions.yaml"


# ─── LLM 输出 Schema ──────────────────────────────────────────────────────────


class GapDetail(BaseModel):
    """单个覆盖缺口"""

    test_point_id: str = Field(description="缺失覆盖的测试点 ID")
    dimension: str = Field(description="缺失的维度")
    feature_id: str = Field(description="关联功能 ID")
    reason: str = Field(description="判定为缺口的原因")
    severity: str = Field(description="严重程度: high/medium/low")


class SupplementCase(BaseModel):
    """补充用例"""

    test_point_id: str = Field(description="关联测试点 ID")
    title: str = Field(description="用例标题")
    preconditions: List[str] = Field(description="前置条件")
    steps: List[dict] = Field(description="测试步骤列表，每项含 step_number, action, input_data, expected_result")
    expected_results: List[str] = Field(description="预期结果汇总")
    priority: str = Field(description="优先级 P0/P1/P2/P3")
    dimensions: List[str] = Field(description="覆盖维度")
    gap_reason: str = Field(description="补充原因")


class AuditLLMOutput(BaseModel):
    """LLM 审计的完整输出"""

    gaps: List[GapDetail] = Field(description="识别到的覆盖缺口")
    dimension_issues: List[str] = Field(default_factory=list, description="维度验证问题（用例声明了维度但步骤没体现）")
    weak_coverage_test_point_ids: List[str] = Field(
        default_factory=list,
        description="'假覆盖'测试点 ID：有用例但步骤未真正验证其声明维度，需接地重做",
    )
    supplement_cases: List[SupplementCase] = Field(default_factory=list, description="补充用例列表")


# ─── Prompt ────────────────────────────────────────────────────────────────────

REVIEW_SYSTEM_PROMPT = """角色：你是测试评审专家，当前任务是【仅诊断】用例集的维度覆盖完整性，不生成任何用例。

任务：
1. 检查每个测试点是否有对应用例覆盖。
   - 有对应用例 = 存在 test_point_id 匹配且步骤实质验证了该测试点描述的场景。
2. 检查每个用例是否真正验证了其声明的维度（不是只标了维度但步骤没体现）。
   - "真正验证"意味着步骤中有针对该维度的具体操作和预期结果。
   - 如发现"假覆盖"（标了维度但步骤是泛泛的模板，或步骤=查阅文档/无实质操作），把该用例的 test_point_id 列入 weak_coverage_test_point_ids，并在 dimension_issues 写明原因。
3. 识别覆盖缺口（有测试点但无用例，或有维度但步骤没验证），填入 gaps。

重要：你看不到 PRD 原文，因此【绝对不要】生成补充用例（supplement_cases 必须留空）。
零覆盖测试点会在后续 backfill 阶段用带 PRD 原文的接地生成补齐，避免无依据地编造预期。

输出要求：严格按指定 JSON Schema 输出，supplement_cases 一律输出空数组。"""


# ─── Helper ────────────────────────────────────────────────────────────────────


def _load_all_dimension_names() -> set[str]:
    """加载全部维度名称"""
    with open(_DIMENSIONS_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {d["name"] for d in data.get("dimensions", [])}


# ─── Node ──────────────────────────────────────────────────────────────────────


async def review_node(state: PipelineState) -> dict:
    """Stage 5: LLM 覆盖审计 + 缺失维度自动补全

    1. 组装用例集和测试点信息
    2. 调用 LLM 进行语义级覆盖审计
    3. 对 LLM 识别的缺口生成补充用例
    4. 输出 AuditReport + final_test_cases
    """
    test_points: list[TestPointSchema] = state["test_points"]
    test_cases: list[GeneratedTestCase] = state["test_cases"]

    # 1. 按功能点分批审计再聚合。
    #    一次性把全部用例（含步骤）塞进单个审计请求，大 PRD 会达到 100 万+ token、
    #    爆模型上下文窗口（ContextWindowExceededError）→ 整个流水线在落库前失败。
    #    审计本就按功能点天然可切：某功能点的用例只需对照该功能点的测试点做覆盖/维度审计。
    #    故按 feature 分批并发审计，单批失败隔离，结果聚合，规避上下文超限。
    tp_by_feature: dict[str, list[TestPointSchema]] = defaultdict(list)
    for tp in test_points:
        tp_by_feature[tp.feature_id].append(tp)

    tp_feature_of: dict[str, str] = {tp.id: tp.feature_id for tp in test_points}
    tc_by_feature: dict[str, list[GeneratedTestCase]] = defaultdict(list)
    for tc in test_cases:
        tc_by_feature[tp_feature_of.get(tc.test_point_id, "")].append(tc)

    def _tp_payload(tps: list[TestPointSchema]) -> list[dict]:
        return [
            {"id": tp.id, "feature_id": tp.feature_id, "dimension": tp.dimension,
             "description": tp.description, "priority": tp.priority}
            for tp in tps
        ]

    def _tc_payload(tcs: list[GeneratedTestCase]) -> list[dict]:
        out = []
        for tc in tcs:
            out.append({
                "id": tc.id,
                "test_point_id": tc.test_point_id,
                "title": tc.title,
                "dimensions": tc.dimensions,
                "steps": [
                    {"step_number": s.step_number, "action": s.action,
                     "input_data": s.input_data, "expected_result": s.expected_result}
                    for s in tc.steps
                ],
                "preconditions": tc.preconditions,
                "expected_results": tc.expected_results,
            })
        return out

    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    async def _audit_feature(feature_id: str) -> AuditLLMOutput | None:
        async with semaphore:
            user_content = json.dumps(
                {
                    "test_points": _tp_payload(tp_by_feature.get(feature_id, [])),
                    "test_cases": _tc_payload(tc_by_feature.get(feature_id, [])),
                },
                ensure_ascii=False,
                indent=2,
            )
            try:
                return await get_llm_client().generate_structured(
                    system_prompt=REVIEW_SYSTEM_PROMPT,
                    user_content=user_content,
                    output_schema=AuditLLMOutput,
                    temperature=0.2,
                )
            except Exception as e:  # noqa: BLE001 — 单功能点审计失败不拖垮整阶段
                logger.error("review 审计失败 (feature=%s): %s", feature_id, e)
                return None

    # 以"出现过用例或测试点"的功能点为审计单位
    audit_feature_ids = sorted(set(tp_by_feature) | set(tc_by_feature))
    logger.info("review: %d 个功能点分批审计, 并发度=%d", len(audit_feature_ids), settings.llm_concurrency)
    results = await asyncio.gather(*[_audit_feature(fid) for fid in audit_feature_ids])

    # 2. 聚合各功能点审计结果
    agg_gaps: list[GapDetail] = []
    agg_dim_issues: list[str] = []
    agg_supplements: list[SupplementCase] = []
    agg_weak: list[str] = []
    audit_failed = 0
    for r in results:
        if r is None:
            audit_failed += 1
            continue
        agg_gaps.extend(r.gaps)
        agg_dim_issues.extend(r.dimension_issues)
        agg_supplements.extend(r.supplement_cases)
        agg_weak.extend(r.weak_coverage_test_point_ids)
    if audit_failed:
        logger.warning("review: %d/%d 个功能点审计失败，已保留其余结果", audit_failed, len(audit_feature_ids))

    llm_output = AuditLLMOutput(
        gaps=agg_gaps, dimension_issues=agg_dim_issues, supplement_cases=agg_supplements
    )

    # 3. 构建 CoverageGap 列表
    gaps: list[CoverageGap] = []
    for gap in llm_output.gaps:
        tp_desc = ""
        for tp in test_points:
            if tp.id == gap.test_point_id:
                tp_desc = tp.description
                break

        gaps.append(
            CoverageGap(
                dimension=gap.dimension,
                feature_id=gap.feature_id,
                description=gap.reason,
                severity=gap.severity if gap.severity in ("high", "medium", "low") else "medium",
                suggested_test_point=tp_desc,
            )
        )

    # 4. review 只做诊断，不再生成补充用例（无 PRD 原文必然编造 oracle）。
    #    零覆盖测试点交由 backfill 阶段用带 PRD 原文 + 留白约束的接地生成补齐。
    additions: list[GeneratedTestCase] = []
    if llm_output.supplement_cases:
        logger.info(
            "review_node: 忽略 LLM 返回的 %d 条无接地补全用例，改由 backfill 接地补齐",
            len(llm_output.supplement_cases),
        )

    # 6. 最终用例集 = 原始用例（补齐在 backfill 阶段完成）
    final_test_cases = test_cases + additions

    # 7. 计算覆盖率（两个维度）

    # 7a. 逐测试点定量对账：每个 test_point 是否有 >=1 条 test_case 匹配
    covered_tp_ids: set[str] = set()
    for tc in final_test_cases:
        if tc.test_point_id:
            covered_tp_ids.add(tc.test_point_id)

    all_tp_ids = {tp.id for tp in test_points}
    uncovered_tp_ids = sorted(all_tp_ids - covered_tp_ids)

    # 假覆盖测试点：去重、限定为真实存在且非零覆盖（零覆盖已在 uncovered 里）
    weak_tp_ids = sorted({w for w in agg_weak if w in all_tp_ids and w in covered_tp_ids})

    # 7b. (feature × dimension) 维度单元覆盖率
    expected_cells: set[tuple[str, str]] = set()
    for tp in test_points:
        expected_cells.add((tp.feature_id, tp.dimension))

    actual_cells: set[tuple[str, str]] = set()
    tp_id_to_feature: dict[str, str] = {tp.id: tp.feature_id for tp in test_points}
    for tc in final_test_cases:
        feature_id = tp_id_to_feature.get(tc.test_point_id, "")
        for dim in tc.dimensions:
            actual_cells.add((feature_id, dim))

    cell_total = len(expected_cells)
    cell_covered = len(actual_cells & expected_cells)

    if uncovered_tp_ids:
        logger.warning(f"review_node: {len(uncovered_tp_ids)} 个测试点无任何用例覆盖: {uncovered_tp_ids[:10]}")

    audit_report = AuditReport(
        total_test_points=len(all_tp_ids),
        per_test_point_covered=len(covered_tp_ids & all_tp_ids),
        uncovered_test_point_ids=uncovered_tp_ids,
        weak_coverage_test_point_ids=weak_tp_ids,
        dimension_cell_total=cell_total,
        dimension_cell_covered=cell_covered,
        dimension_cell_coverage=cell_covered / cell_total if cell_total > 0 else 1.0,
        gaps=gaps,
        additions=additions,
    )
    if weak_tp_ids:
        logger.info("review_node: 标记 %d 个假覆盖测试点，交 backfill 接地重做", len(weak_tp_ids))

    # 记录维度验证问题
    if llm_output.dimension_issues:
        logger.warning(
            "review_node: %d dimension issues detected: %s",
            len(llm_output.dimension_issues),
            "; ".join(llm_output.dimension_issues[:5]),
        )

    return {
        "audit_report": audit_report,
        "final_test_cases": final_test_cases,
        "current_stage": "review",
    }
