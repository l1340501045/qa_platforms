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
