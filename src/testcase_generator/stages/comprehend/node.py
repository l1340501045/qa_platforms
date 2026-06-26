"""T019: Stage 2 — comprehend 节点：LLM 语义理解 + Gate 判定"""

from __future__ import annotations

import json
import logging
from typing import List

from pydantic import BaseModel, Field

from src.testcase_generator.schemas.comprehension_report import (
    BlindSpot,
    ComprehensionReport,
    ConflictDetail,
    FeatureUnderstanding,
    OpenQuestion,
    SourceConflict,
)
from src.testcase_generator.schemas.parsed_context import FeatureItem, ParsedContext, SourceItem
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.services.llm_client import get_llm_client
from src.testcase_generator.stages.comprehend.blind_spot_detector import BlindSpotDetector
from src.testcase_generator.stages.comprehend.gate import MAX_OPEN_QUESTIONS, evaluate_gate

logger = logging.getLogger(__name__)


# ─── LLM 输出 Schema ──────────────────────────────────────────────────────────


class FeatureCoverage(BaseModel):
    """单个功能点的信源覆盖分析结果"""

    feature_id: str = Field(description="功能 ID")
    feature_name: str = Field(description="功能名称")
    covering_source_titles: List[str] = Field(default_factory=list, description="语义覆盖该功能的信源标题列表")
    understanding_level: float = Field(ge=0.0, le=1.0, description="理解程度 0-1，基于信源充分性判断")
    missing_info: List[str] = Field(default_factory=list, description="缺失的信息描述")
    assumptions: List[str] = Field(default_factory=list, description="基于不充分信源做出的假设")
    has_conflict: bool = Field(default=False, description="是否存在信源冲突")
    conflict_description: str = Field(default="", description="冲突描述（如有）")


class ComprehensionLLMOutput(BaseModel):
    """LLM 语义理解的完整输出"""

    feature_coverages: List[FeatureCoverage] = Field(description="每个功能点的覆盖分析")
    overall_coverage: float = Field(ge=0.0, le=1.0, description="整体理解覆盖度")
    identified_conflicts: List[ConflictDetail] = Field(default_factory=list, description="结构化信源冲突列表")
    blind_spot_areas: List[str] = Field(default_factory=list, description="理解盲区名称列表")


# ─── Prompt ────────────────────────────────────────────────────────────────────

COMPREHEND_SYSTEM_PROMPT = """角色：你是资深测试工程师，当前任务是深度理解需求文档。

任务：
1. 对每个功能点，分析哪些信源覆盖了它（语义级别，不是字面匹配）。
   - "覆盖"意味着信源中有该功能的实质描述、规则或约束，而不仅仅是提及名称。
2. 计算理解覆盖度（有充分信源支撑的功能点占比）。
   - understanding_level: 0 = 无覆盖，0.5 = 部分覆盖（仅有粗略描述），1.0 = 充分覆盖（有完整规则和约束）。
3. 识别信源冲突（同一功能点被不同信源矛盾描述）。
   - 冲突判定标准：同一行为/规则被不同信源描述为不同结果或不同约束。
4. 识别理解盲区（功能点存在但无信源解释其细节）。
5. 信任顺序仲裁冲突：PRD(Level 1) > 技术文档(Level 2) > 口述(Level 3) > UI设计(Level 4) > 原型(Level 5)
   - 不同级：高级胜出
   - 同级冲突：标记 has_conflict=True 并描述冲突（需人工裁决）

冲突结构化输出要求（identified_conflicts 每个元素）：
- topic：冲突点简短标题。
- side_a / side_b：各含 location（章节号/表名，如 "§5.6.1"、"§9.2 表"）、
  statement（该处说法原文要点）、trust_level（同文档跨章节冲突时两方相同）。
- 同一文档不同章节自相矛盾，也必须上报，两方 trust_level 相同。
- location 尽量填真实章节号/表名；【禁止】编造 "未列"/"N/A"/"未知" 等占位词；
  确实定位不到时把 location 留空（""），仍要上报该冲突（由系统降级处理）。
- recommendation：side_a / side_b / neither；recommendation_reason：一句话理由（依据信任顺序/更具体/常识）。

输出要求：严格按指定 JSON Schema 输出。"""


# ─── Node ──────────────────────────────────────────────────────────────────────


async def comprehend_node(state: PipelineState) -> dict:
    """Stage 2: LLM 语义理解 + 建立理解矩阵 + Gate 判定

    流程：
    1. 从 parsed_context 提取所有功能点和信源
    2. 调用 LLM 进行语义级覆盖分析 → 构建 feature_matrix
    3. 计算 understanding_coverage
    4. 识别冲突（LLM 语义判断 + BlindSpotDetector 仲裁）
    5. 识别盲区
    6. 执行 Gate 判定
    7. NO_GO 时 interrupt() 挂起等待人工输入
    """
    parsed_context: ParsedContext = state["parsed_context"]
    features = parsed_context.features
    sources = parsed_context.sources

    # 检查是否有来自用户的澄清回答（Gate NO_GO 恢复后会带入）
    clarification_answers: list[dict] | None = state.get("clarification_answers")

    # 初始化检测器（用于仲裁规则）
    detector = BlindSpotDetector()

    # 1. 调用 LLM 构建语义理解矩阵（注入澄清回答作为补充信源）
    feature_matrix, understanding_coverage, llm_conflicts = await _build_feature_matrix_llm(
        features, sources, clarification_answers=clarification_answers
    )

    # 2. 结合 LLM 冲突检测和规则仲裁
    conflicts = _merge_conflicts(llm_conflicts, features, sources, detector)

    # 3. 检测盲区（结合 LLM 识别的盲区）
    blind_spots = detector.detect_blind_spots(features, sources)

    # 4. Gate 判定
    preliminary_report = ComprehensionReport(
        gate_result="GO",
        understanding_coverage=understanding_coverage,
        feature_matrix=feature_matrix,
        conflicts=conflicts,
        blind_spots=blind_spots,
        open_questions=[],
    )

    gate_result = evaluate_gate(preliminary_report)

    # 5. 构建 open_questions（仅 NO_GO 时——CONDITIONAL 直通 test_points 不挂起）
    open_questions: list[OpenQuestion] = []
    if gate_result == "NO_GO":
        open_questions = _build_open_questions(
            blind_spots=blind_spots,
            conflicts=conflicts,
            features=features,
            max_questions=MAX_OPEN_QUESTIONS,
        )

    # 6. 构建最终报告
    comprehension_report = ComprehensionReport(
        gate_result=gate_result,
        understanding_coverage=understanding_coverage,
        feature_matrix=feature_matrix,
        conflicts=conflicts,
        blind_spots=blind_spots,
        open_questions=open_questions,
    )

    logger.info(
        "comprehend_node: coverage=%.2f, conflicts=%d, blind_spots=%d, gate=%s",
        understanding_coverage,
        len(conflicts),
        len(blind_spots),
        gate_result,
    )

    # 7. 返回结果 — interrupt 逻辑由 graph.py 的 interrupt_node 独占
    #    comprehend_node 只负责产出 gate_result + open_questions，
    #    gate_router 根据 gate_result 决定路由到 test_points 或 interrupt_node。
    return {
        "comprehension_report": comprehension_report,
        "gate_result": gate_result,
        "open_questions": [_open_question_to_payload(q) for q in open_questions],
        "current_stage": "comprehend",
    }


async def _build_feature_matrix_llm(
    features: list[FeatureItem],
    sources: list[SourceItem],
    clarification_answers: list[dict] | None = None,
) -> tuple[list[FeatureUnderstanding], float, list[ConflictDetail]]:
    """调用 LLM 进行语义级覆盖分析，构建理解矩阵

    如果有 clarification_answers（Gate NO_GO 恢复后用户的回答），
    将其作为信任等级 3（用户口述）的补充信源注入 LLM prompt，
    使覆盖度与盲区据此重算。
    """

    # 组装用户内容：功能点列表 + 信源摘要
    features_desc = []
    for f in features:
        features_desc.append(
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "source_refs": f.source_refs,
            }
        )

    sources_desc = []
    for s in sources:
        sections_summary = [
            {"heading": sec.heading, "content": sec.content[:500], "source_ref": sec.source_ref} for sec in s.sections
        ]
        sources_desc.append(
            {
                "title": s.title,
                "doc_type": s.doc_type,
                "trust_level": s.trust_level,
                "sections": sections_summary,
            }
        )

    user_content_dict: dict = {
        "features": features_desc,
        "sources": sources_desc,
    }

    # 注入澄清回答作为补充信源（信任等级 3 = 用户口述）
    if clarification_answers:
        user_content_dict["clarification_answers"] = {
            "trust_level": 3,
            "note": "以下是用户对之前盲区/冲突的澄清回答，作为补充信源重新评估覆盖度",
            "answers": clarification_answers,
        }

    user_content = json.dumps(user_content_dict, ensure_ascii=False, indent=2)

    # 调用 LLM
    llm_output = await get_llm_client().generate_structured(
        system_prompt=COMPREHEND_SYSTEM_PROMPT,
        user_content=user_content,
        output_schema=ComprehensionLLMOutput,
        temperature=0.2,
    )

    # 转换为 FeatureUnderstanding 列表
    matrix: list[FeatureUnderstanding] = []
    coverage_map = {fc.feature_id: fc for fc in llm_output.feature_coverages}

    for feature in features:
        fc = coverage_map.get(feature.id)
        if fc:
            matrix.append(
                FeatureUnderstanding(
                    feature_id=fc.feature_id,
                    feature_name=fc.feature_name,
                    understanding_level=fc.understanding_level,
                    missing_info=fc.missing_info,
                    assumptions=fc.assumptions,
                )
            )
        else:
            # LLM 未返回该功能点 → 视为无覆盖
            matrix.append(
                FeatureUnderstanding(
                    feature_id=feature.id,
                    feature_name=feature.name,
                    understanding_level=0.0,
                    missing_info=[f"功能 '{feature.name}' 未被 LLM 分析覆盖"],
                    assumptions=[],
                )
            )

    understanding_coverage = llm_output.overall_coverage
    return matrix, understanding_coverage, llm_output.identified_conflicts


_PLACEHOLDER_TOKENS = {"未列", "未知", "n/a", "na", "无", "null", "none", "待定", "-", "—"}


def _is_placeholder(s: str | None) -> bool:
    """判定来源/章节定位是否为空或占位串（用于冲突卡片降级）。"""
    if s is None:
        return True
    t = s.strip().lower()
    return t == "" or t in _PLACEHOLDER_TOKENS


def _merge_conflicts(
    llm_conflicts: list[ConflictDetail],
    features: list[FeatureItem],
    sources: list[SourceItem],
    detector: BlindSpotDetector,
) -> list[SourceConflict]:
    """合并 LLM 识别的冲突与规则仲裁结果"""
    # 使用 detector 的规则仲裁逻辑处理冲突
    rule_conflicts = detector.detect_conflicts(features, sources)

    # LLM 额外识别的冲突（规则未检出的）补充进来
    existing_ids = {c.conflict_id for c in rule_conflicts}
    counter = len(rule_conflicts)

    for detail in llm_conflicts:
        counter += 1
        cid = f"C-{counter:03d}"
        if cid in existing_ids:
            continue
        placeholder = _is_placeholder(detail.side_a.location) or _is_placeholder(detail.side_b.location)
        rule_conflicts.append(
            SourceConflict(
                conflict_id=cid,
                description=f"{detail.topic}：'{detail.side_a.statement}' vs '{detail.side_b.statement}'",
                source_a=detail.side_a.location or "",
                source_a_trust_level=detail.side_a.trust_level,
                source_b=detail.side_b.location or "",
                source_b_trust_level=detail.side_b.trust_level,
                resolution="unresolved",
                resolution_basis="llm_structured_detection",
                conflict_detail=None if placeholder else detail,
            )
        )

    return rule_conflicts


def _open_question_to_payload(q: OpenQuestion) -> dict:
    """唯一前端序列化点：把 OpenQuestion 拼成前端契约 dict。"""
    return {
        "id": q.question_id,
        "question_id": q.question_id,
        "question": q.question,
        "context": q.context,
        "priority": q.severity,
        "question_type": q.question_type,
        "conflict_detail": q.conflict_detail.model_dump() if q.conflict_detail else None,
        "blocking": q.blocking,
    }


def _build_open_questions(
    blind_spots: list[BlindSpot],
    conflicts: list[SourceConflict],
    features: list[FeatureItem],
    max_questions: int,
) -> list[OpenQuestion]:
    """从盲区和冲突中构建待澄清问题"""
    questions: list[OpenQuestion] = []
    q_counter = 0

    # 同级冲突 → 阻塞性问题
    for conflict in conflicts:
        if conflict.resolution == "unresolved":
            q_counter += 1
            a_ok = not _is_placeholder(conflict.source_a)
            b_ok = not _is_placeholder(conflict.source_b)
            if a_ok and b_ok:
                ctx = (
                    f"'{conflict.source_a}'(Level {conflict.source_a_trust_level}) 与 "
                    f"'{conflict.source_b}'(Level {conflict.source_b_trust_level}) 描述不一致"
                )
            else:
                ctx = "同一文档内存在描述不一致，需人工确认以哪处为准"
            questions.append(
                OpenQuestion(
                    question_id=f"Q-{q_counter:03d}",
                    question=f"信源冲突需要人工裁决：{conflict.description}",
                    context=ctx,
                    related_features=[],
                    blocking=True,
                    question_type="conflict",
                    severity="high",
                    conflict_detail=conflict.conflict_detail,
                    conflict_id=conflict.conflict_id,
                )
            )
            if len(questions) >= max_questions:
                return questions

    # 高优先级盲区 → 阻塞性问题
    for blind_spot in blind_spots:
        if blind_spot.severity == "high":
            q_counter += 1
            questions.append(
                OpenQuestion(
                    question_id=f"Q-{q_counter:03d}",
                    question=f"关键盲区需补充：{blind_spot.area}",
                    context=blind_spot.reason,
                    related_features=[],
                    blocking=True,
                    question_type="blind_spot",
                    severity=blind_spot.severity,
                )
            )
            if len(questions) >= max_questions:
                return questions

    # 中低优先级盲区 → 非阻塞性问题
    for blind_spot in blind_spots:
        if blind_spot.severity != "high":
            q_counter += 1
            questions.append(
                OpenQuestion(
                    question_id=f"Q-{q_counter:03d}",
                    question=f"建议补充：{blind_spot.area}",
                    context=blind_spot.reason,
                    related_features=[],
                    blocking=False,
                    question_type="blind_spot",
                    severity=blind_spot.severity,
                )
            )
            if len(questions) >= max_questions:
                return questions

    return questions
