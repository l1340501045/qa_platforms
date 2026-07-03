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

ReviewIssueType = Literal["case_wrong", "prd_conflict", "verify_uncertain"]
"""审查诊断类型：
- case_wrong       用例断言与明确 PRD 事实相反，或生成了不应执行的具体 oracle
- prd_conflict     PRD 条款之间存在实质互斥，需要产品裁决
- verify_uncertain verify 判断跨实体/跨层级/证据不足，需人工复核或补同层证据
"""


class CrossSectionConflictRef(BaseModel):
    """跨条款矛盾的一对出处（PRD 两条互斥条款）"""

    ref_a: str = Field(description="条款 A 的章节标识")
    quote_a: str = Field(description="条款 A 原文")
    ref_b: str = Field(description="条款 B 的章节标识")
    quote_b: str = Field(description="条款 B 原文")


class CaseVerification(BaseModel):
    """用例事实核验结论（verify 关卡产出）"""

    verdict: Verdict = Field(default="unverified", description="核验结论")
    bucket: Bucket = Field(default="main", description="分桶归属")
    rationale: str = Field(default="", description="判定理由（一句话，引 PRD 依据）")
    prd_evidence: str | None = Field(default=None, description="支撑/反驳该用例的 PRD 原文摘录")
    unsupported_assertions: list[str] = Field(
        default_factory=list, description="无 PRD 支撑或与 PRD 冲突的具体断言列表"
    )
    cross_section_conflict: bool = Field(
        default=False, description="该用例断言虽被某条款支持，但 PRD 另有条款与之实质互斥（PRD 内部矛盾）"
    )
    conflicting_refs: list[CrossSectionConflictRef] = Field(
        default_factory=list, description="互斥条款对清单（cross_section_conflict=True 时给出）"
    )
    conflict_subject_case: str = Field(default="", description="（verdict=conflict 时）用例断言所约束的对象/字段")
    conflict_subject_prd: str = Field(default="", description="（verdict=conflict 时）PRD 反驳条款所约束的对象/字段")
    conflict_entity_mismatch: bool = Field(
        default=False, description="conflict 双方非同一实体（疑似概念混淆假矛盾，已被同实体门控降级）"
    )
    same_entity: bool | None = Field(default=None, description="LLM 对 conflict 双方是否同一实体的结构化判断")
    review_issue_type: ReviewIssueType | None = Field(
        default=None,
        description="审查诊断类型：case_wrong / prd_conflict / verify_uncertain，用于报告和待处理队列分流",
    )


class Provenance(BaseModel):
    """用例溯源信息"""

    derived_from: list[str] = Field(default_factory=list, description="来源引用列表")
    source_section: str = Field(description="来源章节")
    verbatim_excerpt: str = Field(description="原文摘录")
    trust_level: int = Field(ge=1, le=5, description="信任等级")
    grounding: dict | None = Field(
        default=None,
        description="溯源校验统计 {verified,fuzzy,relocated,unresolved}；None=未启用 grounded 模式",
    )


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
