"""T007: AuditReport — 审计报告 schema"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.testcase_generator.schemas.test_case import GeneratedTestCase


class CoverageGap(BaseModel):
    """覆盖度缺口"""

    dimension: str = Field(description="缺失维度名称")
    feature_id: str = Field(description="涉及功能 ID")
    description: str = Field(description="缺口描述")
    severity: str = Field(default="medium", description="严重程度")
    suggested_test_point: str = Field(default="", description="建议补充的测试点描述")


class AuditReport(BaseModel):
    """审计阶段的完整输出"""

    # 逐测试点定量对账（真实 test_point 粒度）
    total_test_points: int = Field(description="测试点总数（len(test_points) 真实值）")
    per_test_point_covered: int = Field(description="有 >=1 条用例（按 test_point_id 匹配）的测试点数")
    uncovered_test_point_ids: list[str] = Field(
        default_factory=list,
        description="无任何用例覆盖的测试点 ID 列表（即使 LLM gap 审计返回 0 也如实记录）",
    )
    weak_coverage_test_point_ids: list[str] = Field(
        default_factory=list,
        description="有用例但被判'假覆盖'(声明维度但步骤未真正验证)的测试点 ID，"
        "交由 backfill 用带 PRD 原文的接地生成重做替换",
    )

    # (feature × dimension) 维度覆盖率（原指标，改名避免混淆）
    dimension_cell_total: int = Field(description="去重 (feature_id, dimension) 组合总数")
    dimension_cell_covered: int = Field(description="有用例覆盖的 (feature_id, dimension) 组合数")
    dimension_cell_coverage: float = Field(ge=0.0, le=1.0, description="维度单元覆盖率")

    # 规则级覆盖（rule_coverage_gate_enabled 开时填充；关时为默认 0/空，行为同历史）。
    # 规则「被覆盖」= 其锚点测试点（携带 rule_id）至少有 1 条用例。结构性闸，确定性、无额外 LLM。
    total_rules: int = Field(default=0, description="规则台账条数（gate 关时为 0）")
    covered_rules: int = Field(default=0, description="锚点有 >=1 用例的规则数")
    rule_coverage: float = Field(default=1.0, ge=0.0, le=1.0, description="规则覆盖率 covered/total")
    uncovered_rule_codes: list[str] = Field(
        default_factory=list,
        description="未覆盖规则码列表（锚点测试点无用例），交 backfill 定向补齐",
    )

    # 兼容旧字段名（逐步废弃）
    @property
    def covered_test_points(self) -> int:
        return self.per_test_point_covered

    @property
    def dimension_coverage(self) -> float:
        return self.dimension_cell_coverage

    gaps: list[CoverageGap] = Field(default_factory=list, description="覆盖缺口列表")
    additions: list[GeneratedTestCase] = Field(default_factory=list, description="审计过程补充的用例")
