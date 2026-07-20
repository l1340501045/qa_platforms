import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.model_runtime import ModelRole
from src.platform_api.core.secret_cipher import ApiKeyCipher
from src.platform_api.core.settings import Settings
from src.platform_api.models.model_settings import AIModelConfigEntry, AIModelConfigState, AIModelConfigVersion
from src.platform_api.repositories.model_settings_repo import StoredModelVersion
from src.platform_api.schemas.model_settings import ModelConnectionRequest, SaveModelSettingRequest
from src.platform_api.services.model_connection_tester import ConnectionTestResult
from src.platform_api.services.model_settings_service import ModelSettingsService


def _settings(master_key: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        llm_base_url="https://primary.example/v1",
        llm_api_key="primary-env-key",
        llm_primary_model="primary-env-model",
        llm_vision_base_url="https://vision.example/v1",
        llm_vision_api_key="vision-env-key",
        llm_vision_model="vision-env-model",
        llm_verify_base_url="https://verify.example/v1",
        llm_verify_api_key="verify-env-key",
        llm_verify_model="verify-env-model",
        embedding_base_url="https://embedding.example/v1",
        embedding_api_key="embedding-env-key",
        openai_embedding_model="embedding-env-model",
        model_config_encryption_key=master_key,
    )


class FakeRepository:
    def __init__(self, stored: StoredModelVersion | None = None):
        self.state = AIModelConfigState(
            id=1,
            active_version_id=stored.version.id if stored else None,
            revision=stored.version.revision if stored else 0,
        )
        self.stored = stored
        self.added: tuple[AIModelConfigVersion, list[AIModelConfigEntry]] | None = None
        self.conflict_on_lock = False

    async def get_active_version(self, *, for_update: bool = False):
        if for_update and self.conflict_on_lock:
            self.state.revision += 1
        return self.state, self.stored

    async def get_version(self, version_id):
        if self.stored and self.stored.version.id == version_id:
            return self.stored
        return None

    async def add_version(self, version, entries):
        self.added = (version, entries)
        self.stored = StoredModelVersion(version=version, entries=tuple(entries))

    async def activate(self, state, version):
        state.active_version_id = version.id
        state.revision = version.revision


class FakeTester:
    def __init__(self, result: ConnectionTestResult):
        self.result = result
        self.endpoints = []

    async def test(self, endpoint):
        self.endpoints.append(endpoint)
        return self.result


def _success_result() -> ConnectionTestResult:
    return ConnectionTestResult(ok=True, category="success", message="连接成功", latency_ms=12)


async def test_get_settings_uses_environment_without_exposing_keys() -> None:
    repository = FakeRepository()
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=FakeTester(_success_result()),
        app_settings=_settings(),
    )

    response = await service.get_settings()
    payload = response.model_dump(mode="json")

    assert response.revision == 0
    assert response.source == "environment"
    assert response.persistence_ready is False
    assert {model.role for model in response.models} == set(ModelRole)
    assert all(model.api_key_status == "configured" for model in response.models)
    rendered = str(payload)
    assert "env-key" not in rendered
    assert "ciphertext" not in rendered


async def test_save_retests_and_creates_an_encrypted_four_role_version() -> None:
    master_key = Fernet.generate_key().decode()
    repository = FakeRepository()
    tester = FakeTester(_success_result())
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=tester,
        cipher=ApiKeyCipher(master_key),
        app_settings=_settings(master_key),
    )
    request = SaveModelSettingRequest(
        base_url="https://new-vision.example/v1",
        model_name="new-vision-model",
        api_key="new-vision-key",
        expected_revision=0,
    )

    response = await service.save_model(ModelRole.VISION, request)

    assert response.revision == 1
    assert repository.added is not None
    version, entries = repository.added
    assert version.revision == 1
    assert {entry.model_role for entry in entries} == {role.value for role in ModelRole}
    changed = next(entry for entry in entries if entry.model_role == ModelRole.VISION.value)
    assert changed.api_key_ciphertext != "new-vision-key"
    assert ApiKeyCipher(master_key).decrypt(changed.api_key_ciphertext or "") == "new-vision-key"
    assert changed.validation_status == "passed"
    assert tester.endpoints[0].api_key == "new-vision-key"
    assert "new-vision-key" not in str(response.model_dump(mode="json"))


async def test_failed_save_keeps_active_version_unchanged() -> None:
    master_key = Fernet.generate_key().decode()
    repository = FakeRepository()
    tester = FakeTester(ConnectionTestResult(ok=False, category="authentication", message="API Key 无效", latency_ms=4))
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=tester,
        cipher=ApiKeyCipher(master_key),
        app_settings=_settings(master_key),
    )

    with pytest.raises(ApiError) as exc:
        await service.save_model(
            ModelRole.PRIMARY,
            SaveModelSettingRequest(
                base_url="https://primary.example/v1",
                model_name="primary-model",
                api_key="wrong-key",
                expected_revision=0,
            ),
        )

    assert exc.value.error_code == "E4221"
    assert repository.added is None
    assert repository.state.revision == 0


async def test_reusing_saved_key_is_rejected_when_api_address_changes() -> None:
    """防止把现有 Key 作为 Authorization 发往新填的未知地址。"""
    master_key = Fernet.generate_key().decode()
    repository = FakeRepository()
    tester = FakeTester(_success_result())
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=tester,
        cipher=ApiKeyCipher(master_key),
        app_settings=_settings(master_key),
    )

    with pytest.raises(ApiError) as exc:
        await service.test_model(
            ModelRole.PRIMARY,
            ModelConnectionRequest(
                base_url="https://untrusted-endpoint.example/v1",
                model_name="primary-model",
            ),
        )

    assert exc.value.error_code == "E4221"
    assert "重新填写 API Key" in exc.value.message
    assert tester.endpoints == []


async def test_keyless_local_endpoint_can_change_address_without_dummy_key() -> None:
    master_key = Fernet.generate_key().decode()
    app_settings = _settings(master_key)
    app_settings.llm_api_key = ""
    app_settings.openai_api_key = ""
    tester = FakeTester(_success_result())
    service = ModelSettingsService(
        session=None,
        repository=FakeRepository(),
        tester=tester,
        cipher=ApiKeyCipher(master_key),
        app_settings=app_settings,
    )

    result = await service.test_model(
        ModelRole.PRIMARY,
        ModelConnectionRequest(
            base_url="http://local-model.internal/v1",
            model_name="local-model",
        ),
    )

    assert result.ok is True
    assert tester.endpoints[0].api_key == ""


async def test_concurrent_revision_change_is_rejected_after_connection_test() -> None:
    master_key = Fernet.generate_key().decode()
    repository = FakeRepository()
    repository.conflict_on_lock = True
    tester = FakeTester(_success_result())
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=tester,
        cipher=ApiKeyCipher(master_key),
        app_settings=_settings(master_key),
    )

    with pytest.raises(ApiError) as exc:
        await service.save_model(
            ModelRole.VERIFY,
            SaveModelSettingRequest(
                base_url="https://verify.example/v1",
                model_name="verify-model",
                api_key="verify-key",
                expected_revision=0,
            ),
        )

    assert exc.value.error_code == "E4091"
    assert len(tester.endpoints) == 1
    assert repository.added is None


async def test_unreadable_database_keys_are_reported_without_ciphertext() -> None:
    encryptor = ApiKeyCipher(Fernet.generate_key().decode())
    version = AIModelConfigVersion(id=uuid.uuid4(), revision=3)
    entries = tuple(
        AIModelConfigEntry(
            id=uuid.uuid4(),
            version_id=version.id,
            model_role=role.value,
            base_url=f"https://{role.value}.example/v1",
            model_name=f"{role.value}-model",
            api_key_ciphertext=encryptor.encrypt(f"{role.value}-key"),
            source="database",
            validation_status="passed",
            tested_at=datetime.now(timezone.utc),
            vector_dimension=1024 if role is ModelRole.EMBEDDING else None,
        )
        for role in ModelRole
    )
    repository = FakeRepository(StoredModelVersion(version=version, entries=entries))
    service = ModelSettingsService(
        session=None,
        repository=repository,
        tester=FakeTester(_success_result()),
        cipher=ApiKeyCipher(Fernet.generate_key().decode()),
        app_settings=_settings(),
    )

    response = await service.get_settings()
    rendered = str(response.model_dump(mode="json"))

    assert all(model.api_key_status == "unreadable" for model in response.models)
    assert all(model.validation_status == "key_unreadable" for model in response.models)
    assert "gAAAA" not in rendered


def test_request_repr_masks_api_key() -> None:
    request = ModelConnectionRequest(
        base_url="https://vision.example/v1",
        model_name="vision-model",
        api_key="provider-secret",
    )

    assert "provider-secret" not in repr(request)
