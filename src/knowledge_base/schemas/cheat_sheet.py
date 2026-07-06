"""cheat sheet 服务层 DTO。"""

from uuid import UUID

from pydantic import BaseModel, Field

from src.platform_api.models.enums import CheatSheetType


class CheatSheetItemCreate(BaseModel):
    """提取器写入 repo 的 cheat sheet 条目。"""

    sheet_type: CheatSheetType = Field(description="条目类型")
    title: str = Field(description="QA 可读标题")
    dedup_key: str = Field(description="稳定合并键；用于 re-extract 继承 QA 裁定")
    ai_content: dict = Field(description="AI 提取内容")
    review_tier: str | None = Field(default=None, description="审核档位：must/sample/batch")
    source_entity_ids: list[str] | None = Field(default=None, description="溯源实体 ID")
    source_relation_ids: list[str] | None = Field(default=None, description="溯源关系 ID")
    source_section_refs: list[str] | None = Field(default=None, description="溯源章节号")
    sort_order: int = Field(default=0, description="同 sheet 内排序")


class CheatSheetItemSchema(BaseModel):
    """cheat sheet 条目读模型。"""

    id: UUID
    sheet_id: UUID
    sheet_type: CheatSheetType
    title: str
    dedup_key: str
    ai_content: dict
    qa_content: dict | None = None
    review_status: str
    review_tier: str | None = None
    review_comment: str | None = None
    reviewed_by: str | None = None
    source_entity_ids: list[str] | None = None
    source_relation_ids: list[str] | None = None
    source_section_refs: list[str] | None = None
    sort_order: int = 0

    model_config = {"from_attributes": True}


class CheatSheetInjectionItem(BaseModel):
    """注入 write_cases 的已审核 cheat sheet 条目。"""

    id: UUID
    sheet_type: CheatSheetType
    title: str
    content: dict
    review_tier: str | None = None
    source_entity_ids: list[str] | None = None
    source_relation_ids: list[str] | None = None
    source_section_refs: list[str] | None = None
    sort_order: int = 0
