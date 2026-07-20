"""全平台 AI 模型设置的读取、测试、保存和运行期配置加载。"""

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.model_runtime import (
    EMBEDDING_DIMENSION,
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    build_environment_model_bundle,
)
from src.platform_api.core.secret_cipher import (
    ApiKeyCipher,
    SecretCipherUnavailableError,
    SecretDecryptionError,
)
from src.platform_api.core.settings import Settings, settings
from src.platform_api.models.model_settings import AIModelConfigEntry, AIModelConfigState, AIModelConfigVersion
from src.platform_api.repositories.model_settings_repo import ModelSettingsRepository, StoredModelVersion
from src.platform_api.schemas.model_settings import (
    AIModelSettingsResponse,
    ModelConnectionRequest,
    ModelConnectionTestResponse,
    ModelSettingResponse,
    SaveModelSettingRequest,
)
from src.platform_api.services.model_connection_tester import ConnectionTestResult, ModelConnectionTester

_ROLE_COPY = {
    ModelRole.PRIMARY: ("推理/生成模型", "负责文本分析、规则与测试点抽取、测试用例生成"),
    ModelRole.VISION: ("视觉模型", "负责解析产品截图、流程图和状态机图"),
    ModelRole.VERIFY: ("校验模型", "负责事实核验和冲突复判"),
    ModelRole.EMBEDDING: ("向量模型", "负责文档向量化、检索和语义去重"),
}


class ModelSettingsService:
    """模型设置业务层；数据库事务由外层 session 生命周期统一提交。"""

    def __init__(
        self,
        session: AsyncSession | None,
        *,
        repository: ModelSettingsRepository | None = None,
        tester: ModelConnectionTester | None = None,
        cipher: ApiKeyCipher | None = None,
        app_settings: Settings = settings,
    ):
        if repository is None and session is None:
            raise ValueError("ModelSettingsService 需要 session 或 repository")
        self.repository = repository or ModelSettingsRepository(session)  # type: ignore[arg-type]
        self.app_settings = app_settings
        self.cipher = cipher or ApiKeyCipher(app_settings.model_config_encryption_key)
        self.tester = tester or ModelConnectionTester(timeout=app_settings.model_connection_test_timeout)

    async def get_settings(self) -> AIModelSettingsResponse:
        state, stored = await self.repository.get_active_version()
        return self._build_response(state, stored)

    async def test_model(
        self,
        role: ModelRole,
        request: ModelConnectionRequest,
    ) -> ModelConnectionTestResponse:
        _, stored = await self.repository.get_active_version()
        candidate = self._build_candidate(role, request, stored)
        result = await self.tester.test(candidate)
        return self._test_response(result)

    async def save_model(
        self,
        role: ModelRole,
        request: SaveModelSettingRequest,
    ) -> AIModelSettingsResponse:
        if not self.cipher.ready:
            raise ApiError("E5031", "服务器尚未配置有效的模型配置总加密密钥，暂时不能保存")

        state, stored = await self.repository.get_active_version()
        current_revision = state.revision if state is not None else 0
        if current_revision != request.expected_revision:
            raise ApiError("E4091", "模型配置已被其他页面更新，请刷新后重试")

        candidate = self._build_candidate(role, request, stored)
        test_result = await self.tester.test(candidate)
        if not test_result.ok:
            raise ApiError("E4221", test_result.message)

        locked_state, locked_stored = await self.repository.get_active_version(for_update=True)
        if locked_state is None:
            raise ApiError("E5001", "模型配置状态不存在，请先执行数据库迁移")
        if locked_state.revision != request.expected_revision:
            raise ApiError("E4091", "模型配置已被其他页面更新，请刷新后重试")

        version = AIModelConfigVersion(id=uuid.uuid4(), revision=locked_state.revision + 1)
        tested_at = datetime.now(timezone.utc)
        entries = self._clone_entries(
            version_id=version.id,
            stored=locked_stored,
            changed_role=role,
            candidate=candidate,
            tested_at=tested_at,
        )
        await self.repository.add_version(version, entries)
        await self.repository.activate(locked_state, version)
        return self._build_response(locked_state, StoredModelVersion(version=version, entries=tuple(entries)))

    async def load_active_bundle(self) -> ModelConfigBundle:
        _, stored = await self.repository.get_active_version()
        return self._bundle_from_stored(stored) if stored else build_environment_model_bundle(self.app_settings)

    def _build_candidate(
        self,
        role: ModelRole,
        request: ModelConnectionRequest,
        stored: StoredModelVersion | None,
    ) -> ModelEndpointConfig:
        request_key = request.api_key.get_secret_value().strip() if request.api_key else ""
        current = self._endpoint_for_role(role, stored, require_key=not bool(request_key))
        current_base_url = (current.base_url or "").rstrip("/")
        if not request_key and current.api_key and request.base_url != current_base_url:
            raise ApiError("E4221", "API 地址变更时必须重新填写 API Key，防止现有 Key 被发送到未知地址")
        return ModelEndpointConfig(
            role=role,
            base_url=request.base_url,
            api_key=request_key or current.api_key,
            model_name=request.model_name,
            vector_dimension=EMBEDDING_DIMENSION if role is ModelRole.EMBEDDING else None,
            source="database",
            validation_status="passed",
        )

    def _endpoint_for_role(
        self,
        role: ModelRole,
        stored: StoredModelVersion | None,
        *,
        require_key: bool = True,
    ) -> ModelEndpointConfig:
        if stored is None:
            return build_environment_model_bundle(self.app_settings).for_role(role)
        entry = self._entry_map(stored).get(role)
        if entry is None:
            raise ApiError("E5001", f"当前模型配置版本缺少 {role.value} 类别")
        api_key = ""
        if require_key and entry.api_key_ciphertext:
            try:
                api_key = self.cipher.decrypt(entry.api_key_ciphertext)
            except (SecretCipherUnavailableError, SecretDecryptionError) as exc:
                raise ApiError("E4221", "当前 API Key 无法读取，请重新填写") from exc
        return ModelEndpointConfig(
            role=role,
            base_url=entry.base_url or None,
            api_key=api_key,
            model_name=entry.model_name,
            vector_dimension=entry.vector_dimension,
            source=entry.source,
            validation_status=entry.validation_status,
        )

    def _clone_entries(
        self,
        *,
        version_id: UUID,
        stored: StoredModelVersion | None,
        changed_role: ModelRole | None = None,
        candidate: ModelEndpointConfig | None = None,
        tested_at: datetime | None = None,
    ) -> list[AIModelConfigEntry]:
        stored_entries = self._entry_map(stored) if stored else {}
        environment = build_environment_model_bundle(self.app_settings)
        entries: list[AIModelConfigEntry] = []

        for role in ModelRole:
            if role is changed_role:
                if candidate is None:
                    raise ValueError("changed_role 需要 candidate")
                entries.append(
                    AIModelConfigEntry(
                        id=uuid.uuid4(),
                        version_id=version_id,
                        model_role=role.value,
                        base_url=candidate.base_url or "",
                        model_name=candidate.model_name,
                        api_key_ciphertext=self.cipher.encrypt(candidate.api_key) if candidate.api_key else None,
                        source="database",
                        validation_status="passed",
                        tested_at=tested_at,
                        vector_dimension=EMBEDDING_DIMENSION if role is ModelRole.EMBEDDING else None,
                    )
                )
                continue

            existing = stored_entries.get(role)
            if existing is not None:
                entries.append(
                    AIModelConfigEntry(
                        id=uuid.uuid4(),
                        version_id=version_id,
                        model_role=role.value,
                        base_url=existing.base_url,
                        model_name=existing.model_name,
                        api_key_ciphertext=existing.api_key_ciphertext,
                        source=existing.source,
                        validation_status=existing.validation_status,
                        tested_at=existing.tested_at,
                        vector_dimension=existing.vector_dimension,
                    )
                )
                continue

            endpoint = environment.for_role(role)
            entries.append(
                AIModelConfigEntry(
                    id=uuid.uuid4(),
                    version_id=version_id,
                    model_role=role.value,
                    base_url=endpoint.base_url or "",
                    model_name=endpoint.model_name,
                    api_key_ciphertext=self.cipher.encrypt(endpoint.api_key) if endpoint.api_key else None,
                    source="environment",
                    validation_status="untested",
                    tested_at=None,
                    vector_dimension=EMBEDDING_DIMENSION if role is ModelRole.EMBEDDING else None,
                )
            )
        return entries

    def _build_response(
        self,
        state: AIModelConfigState | None,
        stored: StoredModelVersion | None,
    ) -> AIModelSettingsResponse:
        if stored is None:
            bundle = build_environment_model_bundle(self.app_settings)
            models = [
                self._endpoint_response(
                    endpoint=bundle.for_role(role),
                    api_key_status="configured" if bundle.for_role(role).api_key else "missing",
                )
                for role in ModelRole
            ]
            return AIModelSettingsResponse(
                version_id=None,
                revision=state.revision if state else 0,
                source="environment",
                persistence_ready=self.cipher.ready,
                models=models,
            )

        entry_map = self._entry_map(stored)
        if set(entry_map) != set(ModelRole):
            raise ApiError("E5001", "当前模型配置版本不完整")
        models = [self._entry_response(role, entry_map[role]) for role in ModelRole]
        return AIModelSettingsResponse(
            version_id=stored.version.id,
            revision=stored.version.revision,
            source="database",
            persistence_ready=self.cipher.ready,
            models=models,
        )

    def _entry_response(self, role: ModelRole, entry: AIModelConfigEntry) -> ModelSettingResponse:
        key_status = "missing"
        validation_status = entry.validation_status
        if entry.api_key_ciphertext:
            try:
                self.cipher.decrypt(entry.api_key_ciphertext)
                key_status = "configured"
            except (SecretCipherUnavailableError, SecretDecryptionError):
                key_status = "unreadable"
                validation_status = "key_unreadable"
        return self._endpoint_response(
            endpoint=ModelEndpointConfig(
                role=role,
                base_url=entry.base_url or None,
                api_key="",
                model_name=entry.model_name,
                vector_dimension=entry.vector_dimension,
                source=entry.source,
                validation_status=validation_status,
            ),
            api_key_status=key_status,
            tested_at=entry.tested_at,
        )

    @staticmethod
    def _endpoint_response(
        *,
        endpoint: ModelEndpointConfig,
        api_key_status: str,
        tested_at: datetime | None = None,
    ) -> ModelSettingResponse:
        display_name, description = _ROLE_COPY[endpoint.role]
        return ModelSettingResponse(
            role=endpoint.role,
            display_name=display_name,
            description=description,
            base_url=endpoint.base_url or "",
            model_name=endpoint.model_name,
            api_key_status=api_key_status,
            source=endpoint.source,
            validation_status=endpoint.validation_status,
            tested_at=tested_at,
            vector_dimension=endpoint.vector_dimension,
        )

    def _bundle_from_stored(self, stored: StoredModelVersion) -> ModelConfigBundle:
        entries = self._entry_map(stored)
        if set(entries) != set(ModelRole):
            raise ApiError("E5001", "任务引用的模型配置版本不完整")
        models = {role: self._endpoint_for_role(role, stored) for role in ModelRole}
        return ModelConfigBundle(
            version_id=stored.version.id,
            revision=stored.version.revision,
            source="database",
            models=models,
        )

    @staticmethod
    def _entry_map(stored: StoredModelVersion | None) -> dict[ModelRole, AIModelConfigEntry]:
        if stored is None:
            return {}
        return {ModelRole(entry.model_role): entry for entry in stored.entries}

    @staticmethod
    def _test_response(result: ConnectionTestResult) -> ModelConnectionTestResponse:
        return ModelConnectionTestResponse(
            ok=result.ok,
            category=result.category,
            message=result.message,
            latency_ms=result.latency_ms,
            embedding_dimension=result.embedding_dimension,
        )
