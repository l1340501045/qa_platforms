"""通知相关 Pydantic Schema"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


NotificationType = Literal[
    "batch_completed",
    "batch_failed",
    "batch_suspended",
]


class NotificationCreate(BaseModel):
    """创建通知请求（内部使用）"""

    type: NotificationType
    title: str
    body: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    actor: str = "system"


class NotificationResponse(BaseModel):
    """通知响应"""

    id: UUID
    type: str
    title: str
    body: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    is_read: bool = Field(serialization_alias="read")
    actor: str
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class UnreadCountResponse(BaseModel):
    """未读数响应"""

    count: int


class MarkAllReadResponse(BaseModel):
    """全部标记已读响应"""

    updated_count: int
