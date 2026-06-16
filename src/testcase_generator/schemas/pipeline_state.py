"""LangGraph 流水线状态定义 — 各阶段间传递的 TypedDict"""

from typing import TypedDict
from uuid import UUID

from src.testcase_generator.schemas.parsed_context import ParsedContext
from src.testcase_generator.schemas.comprehension_report import ComprehensionReport
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.audit_report import AuditReport


class PipelineState(TypedDict, total=False):
    """LangGraph StateGraph 的状态容器

    各阶段按顺序填充对应字段，下游阶段消费上游产物。
    total=False 允许初始状态只含部分字段。
    """

    # 输入
    document_id: str
    system_id: str
    batch_id: str
    generation_config: dict

    # Stage 1: parse 产物
    parsed_context: ParsedContext

    # Stage 2: comprehend + gate 产物
    comprehension_report: ComprehensionReport
    gate_result: str  # "GO" | "CONDITIONAL" | "NO_GO"
    open_questions: list[dict]  # Gate NO_GO 时的待澄清问题
    clarification_answers: list[dict] | None  # 用户回答（interrupt 恢复后填入）

    # Stage 2.5: rule_extract 产物（规则台账；rule_extract_enabled 关时为空）
    rules: list[dict]  # [{rule_code, module, rule, source_quote, category}]

    # Stage 3: test-points 产物
    test_points: list[TestPointSchema]

    # Stage 4: write-cases 产物
    test_cases: list[GeneratedTestCase]

    # Stage 5: review 产物
    audit_report: AuditReport
    final_test_cases: list[GeneratedTestCase]  # 审计补全后的最终用例集
    reconcile_iterations: int  # 覆盖回填回环已执行轮数（防无限循环）

    # Stage 5.5: verify 产物（grounding 事实核验关卡）
    verify_summary: dict  # {total, by_verdict, by_bucket}

    # Stage 5.6: dedup 产物（全局去重）
    dedup_summary: dict  # {total, duplicate_count, cluster_count, unique_after_dedup}

    # Stage 6: export 产物
    yaml_output: str
    markdown_output: str
    bucket_counts: dict  # {main, needs_spec, to_fix}

    # 元数据
    current_stage: str
    error: str | None
