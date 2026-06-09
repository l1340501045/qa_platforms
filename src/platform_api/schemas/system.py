"""系统管理 Pydantic schemas"""

from datetime import datetime
from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, Field


# ─── 系统关联类型枚举 ───
SYSTEM_RELATION_TYPES = ("api_call", "data_share", "event")


# ─── System Schemas ───


class CreateSystemRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="系统名称（唯一）")
    description: str | None = Field(None, description="系统描述")


class UpdateSystemRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100, description="系统名称")
    description: str | None = Field(None, description="系统描述")


class SystemResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SystemListResponse(BaseModel):
    items: Sequence[SystemResponse]
    total: int
    offset: int
    limit: int


# ─── System Association Schemas ───


class CreateSystemAssociationRequest(BaseModel):
    source_system_id: UUID = Field(..., description="源系统 ID")
    target_system_id: UUID = Field(..., description="目标系统 ID")
    relation_type: str = Field(..., description="关联类型: api_call / data_share / event")
    description: str | None = Field(None, description="关联描述")


class SystemAssociationResponse(BaseModel):
    id: UUID
    source_system_id: UUID
    target_system_id: UUID
    relation_type: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SystemAssociationListResponse(BaseModel):
    items: Sequence[SystemAssociationResponse]
    total: int
    offset: int
    limit: int
