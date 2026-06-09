"""批次管理 Pydantic schemas"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """触发生成请求"""

    config: dict | None = None  # 可选生成配置


class BatchResponse(BaseModel):
    """批次详情响应"""

    id: UUID
    document_id: UUID
    system_id: UUID
    status: str  # BatchStatus 枚举值
    current_stage: str | None = None
    total_cases: int | None = None
    document_title: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchStatusResponse(BaseModel):
    """批次状态轮询响应（含阶段进度）"""

    id: UUID
    status: str
    current_stage: str | None = None
    total_cases: int | None = None
    open_questions: list[dict] | None = None  # status=suspended 时有值


class ClarificationRequest(BaseModel):
    """提交澄清答案"""

    answers: list[dict] = Field(..., description="[{question_id, answer}]")


class IterateRequest(BaseModel):
    """触发迭代"""

    modified_case_ids: list[str] = Field(..., description="需要重新生成的用例 ID 列表")
    feedback: dict | None = None
