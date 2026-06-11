"""T026: write-cases 节点 — LLM + few-shot 生成具体用例（最重要节点）

硬约束#3: 每条用例必带 provenance
硬约束#6: few-shot 从 quality_flywheel 拉取
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import List, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, Field

from src.platform_api.core.settings import settings

from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.schemas.test_case import (
    GeneratedTestCase,
    TestStep,
    Provenance,
)
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.write_cases.provenance_tagger import (
    ProvenanceTagger,
)
from src.testcase_generator.stages.write_cases.confidence_scorer import (
    ConfidenceScorer,
)
from src.testcase_generator.services.few_shot_retriever import (
    FewShotRetriever,
)
from src.testcase_generator.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# ─── LLM 输出 Schema ──────────────────────────────────────────────────────────


class LLMTestStep(BaseModel):
    """LLM 生成的测试步骤"""

    step_number: int = Field(description="步骤编号")
    action: str = Field(description="具体操作动作（含明确操作动词）")
    input_data: str = Field(description="具体的输入数据值")
    expected_result: str = Field(description="可观测的预期结果")
    source_quote: str = Field(
        default="",
        description="支撑本步骤预期结果的需求原文片段（直接摘录）；若在所给上下文找不到支撑，留空",
    )
    source_ref: str = Field(default="", description="上述原文所在章节标识，如 'PRD §5.8.13'")


class LLMGeneratedCase(BaseModel):
    """LLM 生成的单条用例"""

    test_point_id: str = Field(description="关联测试点 ID")
    title: str = Field(description="用例标题")
    preconditions: List[str] = Field(description="前置条件列表（完整列出所有必要准备）")
    steps: List[LLMTestStep] = Field(description="测试步骤列表")
    expected_results: List[str] = Field(description="预期结果汇总")
    priority: str = Field(description="优先级 P0/P1/P2/P3")
    dimensions: List[str] = Field(description="覆盖的维度列表")


class WriteCasesLLMOutput(BaseModel):
    """LLM 用例生成的完整输出"""

    test_cases: List[LLMGeneratedCase] = Field(description="生成的测试用例列表")


# ─── Prompt ────────────────────────────────────────────────────────────────────

WRITE_CASES_SYSTEM_PROMPT = """角色：你是拥有 10 年经验的资深测试工程师，当前任务是将测试点展开为完整的、可执行的测试用例。

方法论约束：
- 每条用例的步骤必须具体到可执行：有明确的操作动词、具体的输入数据值、可观测的预期结果
- 不使用"按需求执行"等模糊描述
- 前置条件必须完整列出所有必要准备（环境、数据、账号状态等）
- 预期结果必须可验证（有具体值或可观测状态变化）
- 质量优先不设数量上限
- 每个测试点至少生成一条用例，复杂测试点应拆分为多条用例（正常/异常/边界）
- 步骤中的输入数据要用具体值举例，不能用占位符

【事实接地强约束（最重要，违反将被核验关卡剔除）】
- 每个步骤的 expected_result 必须能在所给 requirement_context 原文中找到支撑，并把支撑原文摘录填入 source_quote、所在章节填入 source_ref。
- 找不到原文支撑的预期结果，不要编造——要么不写该断言，要么换成需求确有定义的可观测结果。
- 严禁对需求未定义的行为编造预期（如自动重试/指数退避/熔断限流、HTTP 错误码契约、超时阈值、性能 SLA、幂等键、SSRF/SQL/XSS 防护、Token 加密、redirect_uri/state 校验等），除非 requirement_context 明文定义了它们。
- 上下文中每个章节带有 section_kind：
  - spec：可正常据其写确定的预期结果；
  - mock：该行为本期为接口模拟/未实现，只能写"占位提示/未真正调用接口"类预期，不得断言真实后端行为；
  - future：留待二期，本期不生成其行为用例；
  - flow：仅流程图示意，不得据节点名编造后端机制（重试秒数/锁/续传等）；
  - tbd：待拍板，不写具体行为断言，只可生成"需求待确认"提示；
  - summary：汇总索引，行为细节以其引用的 spec 章节为准。

步骤编写标准：
- action: 使用具体操作动词（点击、输入、选择、拖拽、滑动、长按...）+ 操作对象
- input_data: 给出具体测试数据值，如 "用户名: test_user_001" 或 "金额: 0.01"
- expected_result: 描述可观测的系统响应，如 "页面跳转至订单详情，显示订单号 xxx"

输入格式：测试点列表 + 需求文档上下文 + 技术文档约束。

输出要求：严格按指定 JSON Schema 输出。"""


# ─── Constants ─────────────────────────────────────────────────────────────────

_PRIORITY_MAP: dict[str, str] = {"P0": "P0", "P1": "P1", "P2": "P2", "P3": "P3"}

# 单批最多生成的用例条数（控制 LLM 单次输出长度以规避网关 504）。
# 注意：这是"分几次调用"的切分，不减少测试点/用例总数——各批结果会被聚合。
MAX_TPS_PER_BATCH = 12


def _split_by_count(tps: list, max_per_batch: int = MAX_TPS_PER_BATCH) -> list[list]:
    """按测试点条数切批：仅控制单次输出条数，保证测试点一个不少（切批前后总数恒等）。"""
    if len(tps) <= max_per_batch:
        return [tps] if tps else []
    return [tps[i : i + max_per_batch] for i in range(0, len(tps), max_per_batch)]


# ─── Node ──────────────────────────────────────────────────────────────────────


async def generate_cases(
    parsed_context,
    test_points: list[TestPointSchema],
    system_id: UUID,
    *,
    start_counter: int = 0,
) -> tuple[list[GeneratedTestCase], list[dict]]:
    """对给定测试点集生成用例的核心例程（write_cases 与 backfill 共用）。

    返回 (生成的用例列表, 失败子批列表)。用例编号从 start_counter+1 起递增。
    """
    # 推断 feature_types 用于 few-shot 查询
    all_feature_types: list[str] = []
    for feature in parsed_context.features:
        if feature.feature_type and feature.feature_type != "general":
            all_feature_types.append(feature.feature_type)

    # 加载 few-shot 样本（硬约束#6，冷启动返回空列表不影响流程）
    retriever = FewShotRetriever()
    few_shot_samples = await retriever.retrieve_samples(system_id, all_feature_types)

    # 构建 few-shot 注入段（全局共享，只构建一次）
    few_shot_section = ""
    if few_shot_samples:
        few_shot_section = "\n\n以下是该系统已确认的高质量用例样本，请参考其风格和详细程度：\n" + yaml.dump(
            few_shot_samples[:3], allow_unicode=True, default_flow_style=False
        )

    # 按 feature_id 分组 test_points
    tp_by_feature: dict[str, list[TestPointSchema]] = defaultdict(list)
    for tp in test_points:
        tp_by_feature[tp.feature_id].append(tp)

    # 构建 feature_id → 相关上下文的映射（给足上下文，不粗暴截断）
    feature_context: dict[str, list[dict]] = defaultdict(list)
    for source in parsed_context.sources:
        for section in source.sections:
            # 按 source_ref 匹配功能点
            for feature in parsed_context.features:
                if section.source_ref in feature.source_refs:
                    feature_context[feature.id].append(
                        {
                            "source": source.title,
                            "trust_level": source.trust_level,
                            "section_kind": getattr(section, "section_kind", "spec"),
                            "source_ref": section.source_ref,
                            "heading": section.heading,
                            "content": section.content,  # 不截断，给足上下文
                        }
                    )
                    break
            else:
                # 通用上下文（技术文档等）关联所有功能点
                if source.trust_level <= 2:  # PRD 和技术文档
                    for fid in tp_by_feature:
                        feature_context[fid].append(
                            {
                                "source": source.title,
                                "trust_level": source.trust_level,
                                "section_kind": getattr(section, "section_kind", "spec"),
                                "source_ref": section.source_ref,
                                "heading": section.heading,
                                "content": section.content,
                            }
                        )

    provenance_tagger = ProvenanceTagger()
    confidence_scorer = ConfidenceScorer()
    all_test_cases: list[GeneratedTestCase] = []
    failed_features: list[dict] = []
    case_counter = start_counter

    # 并发单位 = feature（同一 feature 的所有 test_points 一起处理，保住内部上下文连贯）。
    # 大功能点测试点很多，若一次生成上百条用例 → 输出超长 → 网关生成超时 504 → 该功能点零用例。
    # 根因是「单次输出的用例条数」，不是输入大小。故按测试点条数硬切批（_split_by_count）：
    # 每批最多生成 MAX_TPS_PER_BATCH 条用例（输出短、稳返回），各批结果再聚合 —— 测试点一个不少、
    # 用例一条不少。上下文保持完整注入（不截断），保证每条用例都带完整背景，契合"维度全面"的诉求。
    semaphore = asyncio.Semaphore(settings.llm_concurrency)

    def _split_feature_if_needed(
        feature_id: str, tps: list[TestPointSchema]
    ) -> list[list[TestPointSchema]]:
        sub_batches = _split_by_count(tps)
        if len(sub_batches) > 1:
            logger.warning(
                f"feature {feature_id} 共 {len(tps)} 个测试点 > 单批上限 {MAX_TPS_PER_BATCH}，"
                f"切成 {len(sub_batches)} 批分别生成后聚合（用例总数不变）"
            )
        return sub_batches

    async def _process_feature(feature_id: str, feature_tps: list[TestPointSchema]) -> list[GeneratedTestCase] | None:
        """处理单个 feature 的所有 test_points（可能含子分批），失败时返回 None"""
        async with semaphore:
            relevant_context = feature_context.get(feature_id, [])  # 完整上下文，不截断
            sub_batches = _split_feature_if_needed(feature_id, feature_tps)

            feature_cases: list[GeneratedTestCase] = []

            for sub_idx, batch_tps in enumerate(sub_batches):
                test_points_data = [
                    {
                        "id": tp.id,
                        "feature_id": tp.feature_id,
                        "dimension": tp.dimension,
                        "description": tp.description,
                        "priority": tp.priority,
                    }
                    for tp in batch_tps
                ]

                full_system_prompt = WRITE_CASES_SYSTEM_PROMPT + few_shot_section

                user_content = json.dumps(
                    {"test_points": test_points_data, "requirement_context": relevant_context},
                    ensure_ascii=False,
                    indent=2,
                )

                try:
                    llm_output = await get_llm_client().generate_structured(
                        system_prompt=full_system_prompt,
                        user_content=user_content,
                        output_schema=WriteCasesLLMOutput,
                        temperature=0.3,
                    )
                except Exception as e:
                    logger.error(
                        f"write-cases 子批失败 (feature={feature_id}, "
                        f"sub_batch={sub_idx + 1}/{len(sub_batches)}, "
                        f"tps={[tp.id for tp in batch_tps]}): {e}"
                    )
                    # 子批失败隔离：只记录该子批的测试点待回填，不丢弃同 feature 其它子批已生成的用例
                    failed_features.append(
                        {
                            "feature_id": feature_id,
                            "test_point_ids": [tp.id for tp in batch_tps],
                            "error": str(e),
                        }
                    )
                    continue  # 跳过本子批，继续生成同 feature 的后续子批

                # 后处理
                tp_map: dict[str, TestPointSchema] = {tp.id: tp for tp in batch_tps}

                for llm_case in llm_output.test_cases:
                    tp = tp_map.get(llm_case.test_point_id)
                    if not tp:
                        logger.warning("LLM generated case for unknown test_point_id: %s", llm_case.test_point_id)
                        continue

                    provenance = provenance_tagger.tag_provenance(tp, parsed_context)
                    trust_level, confidence_note = confidence_scorer.score(provenance)

                    steps = [
                        TestStep(
                            step_number=s.step_number,
                            action=s.action,
                            input_data=s.input_data,
                            expected_result=s.expected_result,
                            source_quote=s.source_quote or None,
                            source_ref=s.source_ref or None,
                        )
                        for s in llm_case.steps
                    ]

                    feature_cases.append(
                        GeneratedTestCase(
                            id="",  # 编号稍后统一分配
                            test_point_id=llm_case.test_point_id,
                            title=llm_case.title,
                            preconditions=llm_case.preconditions,
                            steps=steps,
                            expected_results=llm_case.expected_results,
                            priority=_PRIORITY_MAP.get(llm_case.priority, "P2"),
                            dimensions=llm_case.dimensions,
                            provenance=provenance,
                            trust_level=trust_level,
                            confidence_note=confidence_note,
                        )
                    )

            return feature_cases

    # 并发执行所有 feature（return_exceptions=True 防止单个异常取消其它）
    feature_ids = list(tp_by_feature.keys())
    logger.info(f"write-cases: {len(feature_ids)} 个 feature 并发, 并发度={settings.llm_concurrency}")
    tasks = [_process_feature(fid, tp_by_feature[fid]) for fid in feature_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 收集成功结果 + 统一编号
    for i, batch_result in enumerate(results):
        if isinstance(batch_result, Exception):
            # _process_feature 内部已 try/except 记录 failed_features，
            # 但如果后处理本身抛异常会走到这里
            fid = feature_ids[i]
            logger.error(f"write-cases feature {fid} 后处理异常: {batch_result}")
            failed_features.append(
                {
                    "feature_id": fid,
                    "test_point_ids": [tp.id for tp in tp_by_feature[fid]],
                    "error": str(batch_result),
                }
            )
        elif batch_result is not None:
            for case in batch_result:
                case_counter += 1
                case.id = f"TC-{case_counter:03d}"
                all_test_cases.append(case)

    if failed_features:
        logger.warning(f"write-cases: {len(failed_features)} 个子批失败，已保留成功结果")

    return all_test_cases, failed_features


async def write_cases_node(state: PipelineState) -> dict:
    """Stage 4: LLM + few-shot 生成完整测试用例

    流程：
    1. 加载 few-shot 样本（硬约束#6）
    2. 按 feature_id 分批（每批 ≤ MAX_TPS_PER_BATCH 个 test_points）
    3. 每批组装 prompt（角色 + 方法论 + few-shot + 相关上下文 + section_kind）
    4. 调用 LLM 生成用例（强制逐条引用 source_quote）
    5. 标注 provenance（硬约束#3）+ 可信度
    """
    parsed_context = state["parsed_context"]
    test_points: list[TestPointSchema] = state["test_points"]
    system_id = UUID(state["system_id"])

    all_test_cases, failed_features = await generate_cases(parsed_context, test_points, system_id)

    return {
        "test_cases": all_test_cases,
        "failed_features": failed_features,
        "current_stage": "write_cases",
    }
