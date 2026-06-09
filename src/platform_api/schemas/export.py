"""导出任务 schemas"""

from datetime import datetime
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    """创建导出任务请求"""

    scope: str = Field(..., description="batch | system")
    batch_id: UUID | None = None
    system_id: UUID | None = None
    format: str = Field("markdown", description="markdown | excel")


class ExportResponse(BaseModel):
    """导出任务响应"""

    id: UUID
    status: str
    file_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExportListResponse(BaseModel):
    """导出任务列表响应"""

    items: Sequence[ExportResponse]
    total: int
