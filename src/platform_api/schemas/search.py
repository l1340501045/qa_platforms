"""搜索相关 Pydantic Schema"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CaseSearchParams(BaseModel):
    """用例搜索请求参数"""

    q: str = Field(min_length=1, max_length=200, description="搜索关键词")
    system_id: UUID | None = Field(default=None, description="系统 ID 筛选")
    priority: Literal["P0", "P1", "P2", "P3"] | None = Field(default=None, description="优先级筛选")
    review_status: Literal["pending", "confirmed", "needs_modification", "deleted"] | None = Field(
        default=None, description="review 状态筛选"
    )
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


class CaseSearchResult(BaseModel):
    """搜索结果单条"""

    id: UUID
    title: str
    priority: str
    trust_level: int
    review_status: str
    system_id: UUID
    system_name: str
    document_id: UUID
    document_title: str
    batch_id: UUID
    score: float = Field(description="pg_trgm 相似度分数")
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    """搜索响应（含分页）"""

    items: list[CaseSearchResult]
    total: int
    page: int
    per_page: int
    total_pages: int
    query: str
