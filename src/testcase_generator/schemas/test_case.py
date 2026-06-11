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
    source_quote: str | None = Field(
        default=None,
        description="支撑该步骤预期结果的 PRD 原文片段（生成期强制引用；找不到支撑应留空并降级用例）",
    )
    source_ref: str | None = Field(default=None, description="该 source_quote 所在章节标识，如 'PRD §5.8.13'")


Verdict = Literal["grounded", "ungrounded", "conflict", "undefined", "unverified"]
"""单条用例的事实核验结论：
- grounded   断言能在 PRD 找到原文支撑
- ungrounded 断言无 PRD 支撑（凭空编造的 oracle）
- conflict   断言与 PRD 明文相反（事实冲突）
- undefined  断言针对 PRD 未定义/mock/二期 行为
- unverified 尚未核验
"""

Bucket = Literal["main", "needs_spec", "to_fix"]
"""分桶：main=主用例集 / needs_spec=待补规格·超纲 / to_fix=与 PRD 冲突需修正"""


class CaseVerification(BaseModel):
    """用例事实核验结论（verify 关卡产出）"""

    verdict: Verdict = Field(default="unverified", description="核验结论")
    bucket: Bucket = Field(default="main", description="分桶归属")
    rationale: str = Field(default="", description="判定理由（一句话，引 PRD 依据）")
    prd_evidence: str | None = Field(default=None, description="支撑/反驳该用例的 PRD 原文摘录")
    unsupported_assertions: list[str] = Field(
        default_factory=list, description="无 PRD 支撑或与 PRD 冲突的具体断言列表"
    )


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
    verification: CaseVerification | None = Field(
        default=None, description="事实核验结论（verify 关卡产出；None 表示未核验）"
    )
    duplicate_of: str | None = Field(
        default=None, description="近重复簇的规范用例 id（dedup 关卡产出；None 表示非重复或为簇内规范用例）"
    )
