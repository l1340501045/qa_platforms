"""四类 AI 模型配置与任务运行期作用域。"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from src.platform_api.core.settings import Settings, settings

EMBEDDING_DIMENSION = 1024


class ModelRole(StrEnum):
    """平台固定的四类模型职责。"""

    PRIMARY = "primary"
    VISION = "vision"
    VERIFY = "verify"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class ModelEndpointConfig:
    """单类模型的有效连接配置；密钥不得出现在 repr。"""

    role: ModelRole
    base_url: str | None
    api_key: str = field(repr=False)
    model_name: str
    vector_dimension: int | None = None
    source: str = "environment"
    validation_status: str = "untested"


@dataclass(frozen=True)
class ModelConfigBundle:
    """一次任务使用的完整四类模型配置。"""

    version_id: UUID | None
    revision: int
    source: str
    models: Mapping[ModelRole, ModelEndpointConfig]

    def __post_init__(self) -> None:
        missing = set(ModelRole) - set(self.models)
        extra = set(self.models) - set(ModelRole)
        if missing or extra:
            raise ValueError("模型配置必须且只能包含 primary、vision、verify、embedding")

    def for_role(self, role: ModelRole | str) -> ModelEndpointConfig:
        return self.models[ModelRole(role)]


def build_environment_model_bundle(app_settings: Settings = settings) -> ModelConfigBundle:
    """按兼容规则将环境变量统一转换为四类模型配置。"""

    models = {
        ModelRole.PRIMARY: ModelEndpointConfig(
            role=ModelRole.PRIMARY,
            base_url=app_settings.resolved_llm_base_url,
            api_key=app_settings.resolved_llm_api_key,
            model_name=app_settings.llm_primary_model,
        ),
        ModelRole.VISION: ModelEndpointConfig(
            role=ModelRole.VISION,
            base_url=app_settings.resolved_vision_base_url,
            api_key=app_settings.resolved_vision_api_key,
            model_name=app_settings.llm_vision_model,
        ),
        ModelRole.VERIFY: ModelEndpointConfig(
            role=ModelRole.VERIFY,
            base_url=app_settings.resolved_verify_base_url,
            api_key=app_settings.resolved_verify_api_key,
            model_name=app_settings.llm_verify_model or app_settings.llm_primary_model,
        ),
        ModelRole.EMBEDDING: ModelEndpointConfig(
            role=ModelRole.EMBEDDING,
            base_url=app_settings.resolved_embedding_base_url,
            api_key=app_settings.resolved_embedding_api_key,
            model_name=app_settings.openai_embedding_model,
            vector_dimension=EMBEDDING_DIMENSION,
        ),
    }
    return ModelConfigBundle(version_id=None, revision=0, source="environment", models=models)


_current_model_bundle: ContextVar[ModelConfigBundle | None] = ContextVar("current_model_bundle", default=None)


@contextmanager
def model_runtime_scope(bundle: ModelConfigBundle) -> Iterator[ModelConfigBundle]:
    """在当前异步任务上下文内固定一套模型配置，并在退出时可靠恢复。"""

    token = _current_model_bundle.set(bundle)
    try:
        yield bundle
    finally:
        _current_model_bundle.reset(token)


def get_current_model_bundle(fallback: ModelConfigBundle | None = None) -> ModelConfigBundle:
    """读取任务作用域配置；无作用域时兼容环境变量。"""

    return _current_model_bundle.get() or fallback or build_environment_model_bundle()
