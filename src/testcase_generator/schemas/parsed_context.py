"""T003: ParsedContext — 解析阶段输出 schema"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


SectionKind = Literal["spec", "summary", "flow", "mock", "future", "tbd"]
"""章节性质分类，决定下游可生成何种 oracle：
- spec   可验证规范（有明确字段/数值/状态/文案）→ 允许完整行为断言
- summary 汇总/索引（目录、章节聚合、字段汇总表）→ 不单独派生行为断言
- flow   流程图/示意（仅节点名+一句话）→ 不可据此编造后端机制细节
- mock   本期模拟/未实现（明文 "mock/接口模拟/当前 UI 未实现"）→ 仅允许"占位/未实现"负向断言
- future 二期/规划（明文 "v2.0/二期/规划/后续接入"）→ 不在本期生成行为断言
- tbd    待拍板/待确认 → 不写具体行为断言，只可生成"需确认"提示
"""


class SectionExtract(BaseModel):
    """从文档中提取的章节片段"""

    heading: str = Field(description="章节标题")
    content: str = Field(description="章节内容摘要")
    source_ref: str = Field(description="来源引用，如 'PRD §2.3'")
    section_kind: SectionKind = Field(
        default="spec",
        description="章节性质分类，决定下游 oracle 策略（spec/summary/flow/mock/future/tbd）",
    )


class PrototypeObservation(BaseModel):
    """可交互原型的观察记录"""

    screen_name: str = Field(description="页面/屏幕名称")
    observation: str = Field(description="观察到的交互行为描述")
    screenshot_url: str | None = Field(default=None, description="截图 URL")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="观察置信度")


class FeatureItem(BaseModel):
    """提取出的功能点"""

    id: str = Field(description="功能 ID，如 F-001")
    name: str = Field(description="功能名称")
    description: str = Field(description="功能描述")
    source_refs: list[str] = Field(default_factory=list, description="来源引用列表")
    feature_type: str = Field(default="general", description="功能类型标签")
    sub_features: list[FeatureItem] = Field(default_factory=list, description="子功能")
    section_kind: SectionKind = Field(
        default="spec",
        description="对应 PRD 章节性质（透传自 SectionExtract.section_kind），决定下游"
                    "维度增强是否跳过：summary/flow/mock/future/tbd 章节不再做维度展开",
    )


class SourceItem(BaseModel):
    """单个源文档的解析结果"""

    doc_id: UUID = Field(description="文档 ID")
    doc_type: str = Field(description="文档类型（使用 DocType 枚举值）")
    trust_level: int = Field(ge=1, le=5, description="信任等级 1-5")
    title: str = Field(description="文档标题")
    sections: list[SectionExtract] = Field(default_factory=list, description="提取的章节列表")


class ParsedContext(BaseModel):
    """解析阶段的完整输出"""

    sources: list[SourceItem] = Field(default_factory=list, description="所有源文档")
    features: list[FeatureItem] = Field(default_factory=list, description="提取的功能点列表")
    prototype_observations: list[PrototypeObservation] | None = Field(default=None, description="原型观察记录（可选）")
    entity_graph_hints: list[dict] = Field(
        default_factory=list,
        description="实体图谱关系提示（section_priority/mutually_exclusive/unreachable），"
                    "entity_retrieval_enabled 关时为空列表",
    )
