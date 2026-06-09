"""T004: ComprehensionReport — 理解阶段输出 schema"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FeatureUnderstanding(BaseModel):
    """单个功能的理解状态"""

    feature_id: str = Field(description="功能 ID")
    feature_name: str = Field(description="功能名称")
    understanding_level: float = Field(ge=0.0, le=1.0, description="理解程度 0-1")
    missing_info: list[str] = Field(default_factory=list, description="缺失信息")
    assumptions: list[str] = Field(default_factory=list, description="做出的假设")


class SourceConflict(BaseModel):
    """不同来源间的冲突"""

    conflict_id: str = Field(description="冲突 ID")
    description: str = Field(description="冲突描述")
    source_a: str = Field(description="来源 A 引用")
    source_a_trust_level: int = Field(ge=1, le=5, description="来源 A 信任等级")
    source_b: str = Field(description="来源 B 引用")
    source_b_trust_level: int = Field(ge=1, le=5, description="来源 B 信任等级")
    resolution: str = Field(description="仲裁结果描述")
    resolution_basis: str = Field(description="仲裁依据（如 'higher_level_wins'）")


class BlindSpot(BaseModel):
    """理解盲区 — 文档未覆盖但可能需要测试的区域"""

    area: str = Field(description="盲区领域")
    reason: str = Field(description="识别为盲区的原因")
    suggested_action: str = Field(description="建议行动（如 '需补充说明'）")
    severity: Literal["high", "medium", "low"] = Field(default="medium")


class OpenQuestion(BaseModel):
    """待澄清的问题 — NO_GO 或 CONDITIONAL 时填充"""

    question_id: str = Field(description="问题 ID")
    question: str = Field(description="问题内容")
    context: str = Field(description="问题上下文")
    related_features: list[str] = Field(default_factory=list, description="关联功能 ID")
    blocking: bool = Field(default=False, description="是否为阻塞性问题")


class ComprehensionReport(BaseModel):
    """理解阶段的完整输出"""

    gate_result: Literal["GO", "CONDITIONAL", "NO_GO"] = Field(description="Gate 判定结果")
    understanding_coverage: float = Field(ge=0.0, le=1.0, description="理解覆盖度 0-1")
    feature_matrix: list[FeatureUnderstanding] = Field(default_factory=list, description="各功能理解状态矩阵")
    conflicts: list[SourceConflict] = Field(default_factory=list, description="来源冲突列表")
    blind_spots: list[BlindSpot] = Field(default_factory=list, description="理解盲区")
    open_questions: list[OpenQuestion] = Field(default_factory=list, description="待澄清问题（NO_GO 时填充）")
