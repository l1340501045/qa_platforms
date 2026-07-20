import inspect

from fastapi.params import Depends
from httpx import ASGITransport, AsyncClient

from src.platform_api.api.v1.model_settings import _get_service
from src.platform_api.core.model_runtime import ModelRole
from src.platform_api.main import app
from src.platform_api.schemas.model_settings import (
    AIModelSettingsResponse,
    ModelConnectionTestResponse,
    ModelSettingResponse,
)


def _settings_response() -> AIModelSettingsResponse:
    return AIModelSettingsResponse(
        revision=0,
        source="environment",
        persistence_ready=False,
        models=[
            ModelSettingResponse(
                role=role,
                display_name=role.value,
                description="用途",
                base_url=f"https://{role.value}.example/v1",
                model_name=f"{role.value}-model",
                api_key_status="configured",
                source="environment",
                validation_status="untested",
                vector_dimension=1024 if role is ModelRole.EMBEDDING else None,
            )
            for role in ModelRole
        ],
    )


def test_model_settings_session_commits_before_http_response() -> None:
    session_dependency = inspect.signature(_get_service).parameters["session"].default

    assert isinstance(session_dependency, Depends)
    assert session_dependency.scope == "function"


class FakeService:
    def __init__(self):
        self.test_request_repr = ""

    async def get_settings(self):
        return _settings_response()

    async def test_model(self, role, request):
        self.test_request_repr = repr(request)
        return ModelConnectionTestResponse(ok=True, category="success", message="连接成功", latency_ms=5)

    async def save_model(self, role, request):
        return _settings_response().model_copy(update={"revision": request.expected_revision + 1})


async def test_model_settings_routes_use_success_envelope_and_never_echo_api_key() -> None:
    service = FakeService()
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get_response = await client.get(
                "/api/v1/settings/ai-models",
                headers={"Origin": "http://test"},
            )
            test_response = await client.post(
                "/api/v1/settings/ai-models/vision/test",
                headers={"Origin": "http://test"},
                json={
                    "base_url": "https://vision.example/v1",
                    "model_name": "vision-model",
                    "api_key": "provider-secret",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert get_response.status_code == 200
    assert get_response.json()["code"] == 0
    assert len(get_response.json()["data"]["models"]) == 4
    assert test_response.status_code == 200
    assert test_response.json()["data"]["ok"] is True
    assert "provider-secret" not in test_response.text
    assert "provider-secret" not in service.test_request_repr


async def test_model_settings_route_rejects_unknown_role() -> None:
    service = FakeService()
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/settings/ai-models/audio/test",
                json={"base_url": "https://audio.example/v1", "model_name": "audio-model"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_model_settings_mutation_rejects_cross_origin_request() -> None:
    """无登录阶段也不能让任意网页借浏览器调用内网模型设置接口。"""
    service = FakeService()
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/settings/ai-models/vision/test",
                headers={"Origin": "https://malicious.example"},
                json={
                    "base_url": "https://vision.example/v1",
                    "model_name": "vision-model",
                    "api_key": "provider-secret",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert service.test_request_repr == ""
    assert "provider-secret" not in response.text


async def test_model_settings_validation_error_never_echoes_malformed_api_key() -> None:
    service = FakeService()
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/settings/ai-models/vision/test",
                headers={"Origin": "http://test"},
                json={
                    "base_url": "https://vision.example/v1",
                    "model_name": "vision-model",
                    "api_key": ["provider-secret"],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "provider-secret" not in response.text
    assert service.test_request_repr == ""


async def test_model_settings_rejects_secrets_in_api_address_query() -> None:
    service = FakeService()
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/settings/ai-models/vision/test",
                headers={"Origin": "http://test"},
                json={
                    "base_url": "https://vision.example/v1?api_key=plain-secret",
                    "model_name": "vision-model",
                    "api_key": "provider-secret",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "plain-secret" not in response.text
    assert "provider-secret" not in response.text
    assert service.test_request_repr == ""
