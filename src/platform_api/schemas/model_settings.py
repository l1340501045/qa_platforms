"""AI 模型设置接口的请求与脱敏响应。"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator

from src.platform_api.core.model_runtime import ModelRole

ApiKeyStatus = Literal["missing", "configured", "unreadable"]
ValidationStatus = Literal["untested", "passed", "key_unreadable"]
ConnectionCategory = Literal[
    "success",
    "network",
    "authentication",
    "model_not_found",
    "rate_limit",
    "capability_mismatch",
    "dimension_mismatch",
    "unknown",
]


class ModelConnectionRequest(BaseModel):
    base_url: str = Field(..., min_length=1, max_length=2048, description="OpenAI 兼容 API 根地址")
    model_name: str = Field(..., min_length=1, max_length=255, description="模型名称")
    # 不在 Pydantic 层对密钥长度做失败校验，避免默认 422 详情回显原始输入。
    api_key: SecretStr | None = Field(None, description="留空时沿用当前 Key")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API 地址必须是有效的 http/https 地址")
        if parsed.username or parsed.password:
            raise ValueError("API 地址不能包含用户名或密码")
        if parsed.query or parsed.fragment:
            raise ValueError("API 地址不能包含查询参数或片段，请只填写 API 根地址")
        return normalized

    @field_validator("model_name")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("模型名称不能为空")
        return normalized


class SaveModelSettingRequest(ModelConnectionRequest):
    expected_revision: int = Field(..., ge=0, description="页面读取到的当前配置版本")


class ModelSettingResponse(BaseModel):
    role: ModelRole
    display_name: str
    description: str
    base_url: str
    model_name: str
    api_key_status: ApiKeyStatus
    source: Literal["environment", "database"]
    validation_status: ValidationStatus
    tested_at: datetime | None = None
    vector_dimension: int | None = None


class AIModelSettingsResponse(BaseModel):
    version_id: UUID | None = None
    revision: int
    source: Literal["environment", "database"]
    persistence_ready: bool
    transport_security: Literal["trusted_intranet_http"] = "trusted_intranet_http"
    models: list[ModelSettingResponse]


class ModelConnectionTestResponse(BaseModel):
    ok: bool
    category: ConnectionCategory
    message: str
    latency_ms: int
    embedding_dimension: int | None = None
