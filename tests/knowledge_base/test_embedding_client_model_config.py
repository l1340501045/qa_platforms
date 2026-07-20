import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.knowledge_base.services.embedding import embedding_client as embedding_client_module
from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient, EmbeddingDimensionError
from src.platform_api.core.model_runtime import ModelConfigBundle, ModelEndpointConfig, ModelRole


def _bundle() -> ModelConfigBundle:
    return ModelConfigBundle(
        version_id=uuid.uuid4(),
        revision=5,
        source="database",
        models={
            role: ModelEndpointConfig(
                role=role,
                base_url=f"https://{role.value}.example/v1",
                api_key=f"{role.value}-secret",
                model_name=f"{role.value}-model",
                vector_dimension=1024 if role is ModelRole.EMBEDDING else None,
                source="database",
                validation_status="passed",
            )
            for role in ModelRole
        },
    )


async def test_embedding_client_uses_embedding_role_endpoint() -> None:
    constructor_calls = []
    requests = []
    api = SimpleNamespace(embeddings=SimpleNamespace())

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * 1024)])

    api.embeddings.create = AsyncMock(side_effect=create)

    def factory(**kwargs):
        constructor_calls.append(kwargs)
        return api

    with patch("src.knowledge_base.services.embedding.embedding_client.openai.AsyncOpenAI", side_effect=factory):
        result = await EmbeddingClient(_bundle()).embed_single("hello")

    assert len(result) == 1024
    assert constructor_calls == [
        {
            "api_key": "embedding-secret",
            "base_url": "https://embedding.example/v1",
        }
    ]
    assert requests[0]["model"] == "embedding-model"


@pytest.mark.parametrize("dimension", [768, 1536])
async def test_embedding_client_rejects_wrong_runtime_dimension(dimension: int) -> None:
    api = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * dimension)]))
        )
    )

    with patch("src.knowledge_base.services.embedding.embedding_client.openai.AsyncOpenAI", return_value=api):
        with pytest.raises(EmbeddingDimensionError, match="1024"):
            await EmbeddingClient(_bundle()).embed_single("hello")


async def test_embedding_batch_validates_every_vector() -> None:
    response = SimpleNamespace(
        data=[
            SimpleNamespace(embedding=[0.0] * 1024),
            SimpleNamespace(embedding=[0.0] * 1000),
        ]
    )
    api = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(return_value=response)))

    with patch("src.knowledge_base.services.embedding.embedding_client.openai.AsyncOpenAI", return_value=api):
        with pytest.raises(EmbeddingDimensionError):
            await EmbeddingClient(_bundle()).embed_batch(["one", "two"])


async def test_embedding_provider_error_is_sanitized_before_leaving_client(caplog) -> None:
    api = SimpleNamespace(
        embeddings=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("provider-secret raw-response")))
    )

    with patch("src.knowledge_base.services.embedding.embedding_client.openai.AsyncOpenAI", return_value=api):
        with pytest.raises(embedding_client_module.EmbeddingInvocationError) as exc:
            await EmbeddingClient(_bundle()).embed_single("hello")

    rendered = f"{exc.value!s} {exc.value!r} {caplog.text}"
    assert "provider-secret" not in rendered
    assert "raw-response" not in rendered
