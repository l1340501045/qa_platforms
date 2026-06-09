"""T006: GeneratedTestCase — 生成的测试用例 schema"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TestStep(BaseModel):
    """测试步骤"""

    step_number: int = Field(description="步骤编号")
    action: str = Field(description="操作动作")
    input_data: str = Field(description="输入数据")
    expected_result: str = Field(description="预期结果")


class Provenance(BaseModel):
    """用例溯源信息"""

    derived_from: list[str] = Field(default_factory=list, description="来源引用列表")
    source_section: str = Field(description="来源章节")
    verbatim_excerpt: str = Field(description="原文摘录")
    trust_level: int = Field(ge=1, le=5, description="信任等级")


class GeneratedTestCase(BaseModel):
    """生成的完整测试用例"""

    id: str = Field(description="用例 ID，TC-001 格式")
    test_point_id: str = Field(description="关联测试点 ID")
    title: str = Field(description="用例标题")
    preconditions: list[str] = Field(default_factory=list, description="前置条件")
    steps: list[TestStep] = Field(default_factory=list, description="测试步骤")
    expected_results: list[str] = Field(default_factory=list, description="预期结果汇总")
    priority: Literal["P0", "P1", "P2", "P3"] = Field(description="优先级")
    dimensions: list[str] = Field(default_factory=list, description="覆盖的维度列表")
    provenance: Provenance = Field(description="溯源信息")
    trust_level: int = Field(ge=1, le=5, description="最终信任等级")
    confidence_note: str | None = Field(default=None, description="置信度备注（低置信度时说明原因）")
