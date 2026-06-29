"""T005: TestPointSchema — 测试点 schema"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TestPointSchema(BaseModel):
    """单个测试点"""

    id: str = Field(description="测试点 ID，TP-001 格式")
    feature_id: str = Field(description="关联功能 ID")
    dimension: str = Field(description="主维度名称")
    description: str = Field(description="测试点描述")
    priority: Literal["P0", "P1", "P2", "P3"] = Field(description="优先级")
    derived_from: list[str] = Field(default_factory=list, description="来源引用列表")
    applicable_dimensions: list[str] = Field(default_factory=list, description="适用维度列表（裁剪后）")
    # 规则锚点：规则驱动测试点携带其规则码（如 "R-001"，运行期为字符串，落库时解析为 rules.id）；
    # 维度增强测试点为 None。用于规则级覆盖闸与规则锚定安全去重。
    rule_id: str | None = Field(default=None, description="关联规则码（规则驱动测试点），维度增强测试点为 None")
    structural_type: str | None = Field(default=None, description="结构化覆盖类型 permission/state_machine；普通点为 None")
    structural_key: str | None = Field(default=None, description="结构化点唯一标识（格子/转移），用于覆盖闸")
