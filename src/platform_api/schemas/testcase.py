"""用例 review schemas"""

from datetime import datetime
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, Field


class UpdateTestCaseRequest(BaseModel):
    """人工编辑用例请求（全部可选，只更新传入字段）"""

    title: str | None = None
    preconditions: list[str] | None = None
    steps: list[dict] | None = None
    expected_results: list[str] | None = None
    priority: str | None = None


class RegenerateRequest(BaseModel):
    """单条 AI 重写请求"""

    comment: str = Field(..., min_length=1, description="QA 修改意见")


class TestCaseResponse(BaseModel):
    """完整用例响应"""

    id: UUID
    batch_id: UUID
    test_point_id: UUID | None = None
    title: str
    preconditions: dict | list
    steps: dict | list
    expected_results: dict | list
    priority: str
    dimensions: dict | list
    provenance: dict
    trust_level: int
    confidence_note: str | None = None
    review_status: str
    review_comment: str | None = None
    iteration: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    """单条用例 review 请求"""

    status: str = Field(..., description="confirmed / needs_modification / deleted")
    comment: str | None = None


class TestCaseListResponse(BaseModel):
    """用例列表响应"""

    items: Sequence[TestCaseResponse]
    total: int
