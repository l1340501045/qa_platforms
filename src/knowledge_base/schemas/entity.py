"""实体图谱 schema — LLM 抽取输出结构"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityItem(BaseModel):
    """单个实体"""

    entity_type: str = Field(description="实体类型: field/section/rule/concept/ui_element/state")
    name: str = Field(description="实体名称（人类可读）")
    canonical_key: str = Field(description="规范化唯一键（用于去重合并）")
    section_ref: str | None = Field(default=None, description="所属章节引用（如 §5.7.1）")
    description: str | None = Field(default=None, description="实体描述")
    source_quote: str | None = Field(default=None, description="PRD 原文引用")
    attributes: dict | None = Field(default=None, description="附加属性")


class RelationItem(BaseModel):
    """单条关系"""

    source_name: str = Field(description="源实体 canonical_key")
    target_name: str = Field(description="目标实体 canonical_key")
    relation_type: str = Field(description="关系类型: section_priority/field_defined_in/rule_constrains/mutually_exclusive/unreachable/belongs_to/transitions_to")
    note: str | None = Field(default=None, description="关系说明")
    source_quote: str | None = Field(default=None, description="PRD 原文依据")


class EntityGraph(BaseModel):
    """单个章节单元抽取的实体图谱"""

    entities: list[EntityItem] = Field(default_factory=list, description="抽取到的实体列表")
    relations: list[RelationItem] = Field(default_factory=list, description="抽取到的关系列表")
