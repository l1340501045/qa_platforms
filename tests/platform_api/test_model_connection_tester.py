from types import SimpleNamespace

import pytest

from src.platform_api.core.model_runtime import ModelEndpointConfig, ModelRole
from src.platform_api.services.model_connection_tester import ModelConnectionTester


class FakeCompletions:
    def __init__(self, *, content: str = "OK", error: Exception | None = None):
        self.content = content
        self.error = error
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class FakeEmbeddings:
    def __init__(self, dimension: int = 1024):
        self.dimension = dimension
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * self.dimension)])


class FakeClient:
    def __init__(self, *, content: str = "OK", dimension: int = 1024, error: Exception | None = None):
        self.chat = SimpleNamespace(completions=FakeCompletions(content=content, error=error))
        self.embeddings = FakeEmbeddings(dimension)


def _endpoint(role: ModelRole) -> ModelEndpointConfig:
    return ModelEndpointConfig(
        role=role,
        base_url=f"https://{role.value}.example/v1",
        api_key="provider-secret",
        model_name=f"{role.value}-model",
        vector_dimension=1024 if role is ModelRole.EMBEDDING else None,
    )


@pytest.mark.parametrize(
    ("role", "content"),
    [
        (ModelRole.PRIMARY, "OK"),
        (ModelRole.VISION, "红色"),
        (ModelRole.VERIFY, '{"ok": true}'),
    ],
)
async def test_chat_roles_execute_their_real_capability_probe(role: ModelRole, content: str) -> None:
    client = FakeClient(content=content)
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return client

    result = await ModelConnectionTester(client_factory=factory).test(_endpoint(role))

    assert result.ok is True
    assert result.category == "success"
    assert factory_calls[0]["max_retries"] == 0
    request = client.chat.completions.requests[0]
    assert request["model"] == f"{role.value}-model"
    if role is ModelRole.VISION:
        assert request["messages"][0]["content"][1]["type"] == "image_url"


async def test_embedding_probe_rejects_non_1024_dimension() -> None:
    result = await ModelConnectionTester(client_factory=lambda **_: FakeClient(dimension=768)).test(
        _endpoint(ModelRole.EMBEDDING)
    )

    assert result.ok is False
    assert result.category == "dimension_mismatch"
    assert result.embedding_dimension == 768
    assert "1024" in result.message


async def test_unknown_provider_error_is_redacted() -> None:
    result = await ModelConnectionTester(
        client_factory=lambda **_: FakeClient(error=RuntimeError("provider-secret appeared in upstream body"))
    ).test(_endpoint(ModelRole.PRIMARY))

    assert result.ok is False
    assert result.category == "unknown"
    assert "provider-secret" not in result.message
