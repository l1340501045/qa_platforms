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
from src.testcase_generator.stages.context_utils import collect_global_sections
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
- 步骤中的输入数据要用具体值举例，不能用占位符

【覆盖维度全面性（资深与初级的分水岭——每个 spec 测试点都要系统性过一遍以下清单，凡 PRD 有明文支撑的维度都要成条覆盖，不要只写正向 happy path）】
- 正常流：典型有效输入下的主流程。
- 边界值：上限/下限、刚好等于阈值/超出 1、空、0、1、最大长度/超长、最大条数/超量、列表恰好等于每页条数。
- 异常与逆向：非法/超长/特殊字符输入、必填缺失、格式错误、重复提交、网络失败/超时、部分失败与回滚、操作取消。
- 状态机：非法/逆向状态转移（不只正向），终态后再操作，并发态。
- 并发与一致性：多端同时操作、A 改动后 B 是否同步、聚合/计数刷新、缓存/同步延迟。
- 权限与可见性：水平越权/垂直越权、未登录、Token 过期、数据隔离边界（仅在 PRD 有定义时）。
- 幂等与重试副作用（仅在 PRD 有定义时）。
说明：以上维度只在 requirement_context 对该行为有明文支撑时才写确定断言；无支撑的维度按下面"需求待确认"规则处理，不要为凑维度编造。

【范围严格性（防过度断言/外推）】
- 断言不得超出 PRD 明文授予的范围：例如 PRD 只写"可读取/可查看全量"，绝不可推断为"可写/可编辑/可删除"；只写"展示置灰"不可写成"移除/隐藏"；只写"提示"不可编造具体文案除非 PRD 给了文案。
- 不得把某功能的取值/枚举套用到 PRD 另有明确定义的名目上（如通配符替换规则、投放方式≠竞价策略）。

【高频误读纠正（反例 → 正解，这些是历史上反复读错的点，务必按 requirement_context 原文核对）】
- emoji 处理：✗ 误判为"拦截/阻止输入/报错『不支持 emoji』"。✓ 正解（若 §5.0/字段约束如此定义）：自动剔除已输入/粘贴的 emoji，仅保留合法文本，并 toast 提示「emoji 已被自动剔除」。务必照原文写剔除而非拦截。
- 投放方式 vs 竞价策略：✗ 把"投放方式"的枚举/规则套到"竞价策略"上（或反之）。✓ 两者是 PRD 中**不同字段**，各有各的取值与约束，必须分别回到各自章节取原文，不可交叉套用。
- 字数算法：✗ 自行臆造计数规则（如"1 个 emoji 算 1 字""中英文都算 1"）。✓ 必须引用 §5.0/字段约束里的**字数算法原文**（全角/半角/emoji/换行如何计数），原文没写则按"需求待确认"。
- 通配符/替换规则：✗ 把某处的通配符替换枚举默认套到所有输入框。✓ 仅在该输入框 PRD 明确引用该规则时适用，否则回到该字段自身定义。
- 状态/置灰 vs 移除：✗ "置灰/禁用"写成"消失/移除/隐藏"。✓ 严格区分"可见但不可点"与"不可见"。

【每个测试点的产出规则（决定生成几条、是不是"待澄清"）】
- 先判断该测试点要验证的行为在 requirement_context 里是否有**明文规格**支撑：
  - 有明文支撑(spec)：可生成 1 条或多条确定性用例（正常/异常/边界各成条），每条预期都要可验证、可引用原文。
  - 无明文支撑（PRD 未定义 / 章节性质是 mock·future·flow·tbd / 找不到任何 source_quote）：
    **只生成唯一一条「需求待确认」型用例**，且：
      · title 以「【需求待确认】」开头；
      · 预期结果统一写成「PRD 未定义该行为，待 PM/需求方澄清后再补确定断言；当前不做确定性结果断言」；
      · 绝不编造任何确定的数值/状态/文案/错误码/流程作为预期。
- **禁矛盾孪生（但允许按方面正确拆分）**：
  · 对同一个"断言点/方面"，不允许既出「待确认版」又出「确定断言版」，也不允许两条结论互斥的用例。
  · 若一个测试点是复合的（部分方面 PRD 有明文、部分方面留白），正确做法是按方面拆成多条：有明文的方面写确定断言、留白的方面写「需求待确认」——这不算孪生，反而是资深做法。
  · 反例（禁止）：同一测试点同时出「管理员可写他人数据(断言)」和「管理员写权限待确认」——这是同一方面的矛盾孪生。

【事实接地强约束（最重要，违反将被核验关卡剔除）】
- 每个步骤的 expected_result 必须能在所给 requirement_context 原文中找到支撑，并把支撑原文摘录填入 source_quote、所在章节填入 source_ref。
- 找不到原文支撑的预期结果，不要编造——按上面的规则改写成「需求待确认」型用例。
- 高频禁区（除非 requirement_context 明文定义，否则一律按"待确认"处理，不得写确定断言）：
  自动重试/指数退避/熔断限流、HTTP 错误码契约(400/403/429 等)、超时阈值、性能 SLA(响应时间/P95/并发量)、
  幂等键、SSRF/SQL注入/XSS/CSRF 防护、Token 加密、redirect_uri/state 校验、空状态文案、分页枚举值、权限"写"操作范围。
- 注意：requirement_context 里包含【全局/常驻章节】（如 §5.0 全局规则、字段约束、字数算法、投放方式、监测链接）。
  这些是适用于本功能点的通用规则——若测试点行为被这些全局章节定义，就按 spec 处理、写确定断言，**不要误判为"待确认"**。
- 上下文中每个章节带有 section_kind：
  - spec：可正常据其写确定的预期结果；
  - mock：该行为本期为接口模拟/未实现，只能写"占位提示/未真正调用接口"类预期，不得断言真实后端行为；
  - future：留待二期，本期不生成其行为用例；
  - flow：仅流程图示意，不得据节点名编造后端机制（重试秒数/锁/续传等）；
  - tbd：待拍板，按上面"需求待确认"型唯一用例处理；
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
    # 记录每个 feature 已注入的章节键，避免与全局章节重复注入
    ctx_seen: dict[str, set[tuple[str, str]]] = defaultdict(set)

    def _append_ctx(fid: str, source, section) -> None:
        key = (section.source_ref or "", section.heading or "")
        if key in ctx_seen[fid]:
            return
        ctx_seen[fid].add(key)
        feature_context[fid].append(
            {
                "source": source.title,
                "trust_level": source.trust_level,
                "section_kind": getattr(section, "section_kind", "spec"),
                "source_ref": section.source_ref,
                "heading": section.heading,
                "content": section.content,  # 不截断，给足上下文
            }
        )

    for source in parsed_context.sources:
        for section in source.sections:
            # 按 source_ref 匹配功能点
            for feature in parsed_context.features:
                if section.source_ref in feature.source_refs:
                    _append_ctx(feature.id, source, section)
                    break
            else:
                # 通用上下文（技术文档等）关联所有功能点
                if source.trust_level <= 2:  # PRD 和技术文档
                    for fid in tp_by_feature:
                        _append_ctx(fid, source, section)

    # 全局/常驻章节（§5.0 全局规则、投放方式、监测链接、字段约束、字数等）无条件注入
    # 每个功能点 —— 修复"§5.0 只给到 F-002 导致其它功能点把已定义行为误判 needs_spec"。
    global_sections = collect_global_sections(parsed_context)
    if global_sections:
        for fid in tp_by_feature:
            for gs in global_sections:
                key = (gs.source_ref or "", gs.heading or "")
                if key in ctx_seen[fid]:
                    continue
                ctx_seen[fid].add(key)
                feature_context[fid].append(
                    {
                        "source": gs.source_title,
                        "trust_level": gs.trust_level,
                        "section_kind": gs.section_kind,
                        "source_ref": gs.source_ref,
                        "heading": gs.heading,
                        "content": gs.content,
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
