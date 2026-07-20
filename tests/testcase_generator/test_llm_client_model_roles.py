import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    model_runtime_scope,
)
from src.testcase_generator.services import llm_client as llm_client_module
from src.testcase_generator.services.llm_client import (
    LLMClient,
    get_llm_client,
    llm_stats,
    reset_llm_client_cache,
)


class DummyOutput(BaseModel):
    value: str


def _bundle(revision: int = 1) -> ModelConfigBundle:
    return ModelConfigBundle(
        version_id=uuid.uuid4(),
        revision=revision,
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


def _response():
    message = SimpleNamespace(content=json.dumps({"value": "ok"}), tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None)


async def test_llm_client_routes_primary_vision_and_verify_to_independent_endpoints() -> None:
    constructor_calls = []
    request_calls = []

    def client_factory(**kwargs):
        constructor_calls.append(kwargs)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace()))

        async def create(**request):
            request_calls.append((kwargs["base_url"], request))
            return _response()

        client.chat.completions.create = AsyncMock(side_effect=create)
        return client

    with patch("src.testcase_generator.services.llm_client.AsyncOpenAI", side_effect=client_factory):
        client = LLMClient(_bundle())
        await client.generate_structured("system", "primary", DummyOutput)
        await client.generate_structured("system", "vision", DummyOutput, images=[b"png"])
        await client.generate_structured(
            "system",
            "verify",
            DummyOutput,
            model_role=ModelRole.VERIFY,
        )

    assert {(call["base_url"], call["api_key"]) for call in constructor_calls} == {
        ("https://primary.example/v1", "primary-secret"),
        ("https://vision.example/v1", "vision-secret"),
        ("https://verify.example/v1", "verify-secret"),
    }
    assert [request["model"] for _, request in request_calls] == [
        "primary-model",
        "vision-model",
        "verify-model",
    ]
    assert [str(base_url) for base_url, _ in request_calls] == [
        "https://primary.example/v1",
        "https://vision.example/v1",
        "https://verify.example/v1",
    ]


def test_get_llm_client_cache_is_scoped_by_model_bundle() -> None:
    reset_llm_client_cache()
    first_bundle = _bundle(revision=3)
    second_bundle = _bundle(revision=4)

    with patch("src.testcase_generator.services.llm_client.AsyncOpenAI"):
        with model_runtime_scope(first_bundle):
            first = get_llm_client()
            assert get_llm_client() is first
        with model_runtime_scope(second_bundle):
            second = get_llm_client()

    assert second is not first
    assert first.bundle.revision == 3
    assert second.bundle.revision == 4


async def test_call_stats_record_role_model_and_config_revision() -> None:
    llm_stats.calls.clear()
    bundle = _bundle(revision=7)
    mock_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_response())))
    )

    with patch("src.testcase_generator.services.llm_client.AsyncOpenAI", return_value=mock_client):
        await LLMClient(bundle).generate_structured(
            "system",
            "verify",
            DummyOutput,
            model_role=ModelRole.VERIFY,
        )

    stats = llm_stats.calls[-1]
    assert stats.model_role == "verify"
    assert stats.model_name == "verify-model"
    assert stats.config_revision == 7


async def test_provider_error_is_sanitized_before_leaving_llm_client(monkeypatch, caplog) -> None:
    client = LLMClient(_bundle())

    async def fail_call(*_args, **_kwargs):
        raise RuntimeError("provider-secret raw-response")

    monkeypatch.setattr(client, "_call", fail_call)
    monkeypatch.setattr(llm_client_module.settings, "llm_max_retries", 1)

    with pytest.raises(llm_client_module.ModelInvocationError) as exc:
        await client.generate_structured("system", "user", DummyOutput)

    rendered = f"{exc.value!s} {exc.value!r} {caplog.text}"
    assert "provider-secret" not in rendered
    assert "raw-response" not in rendered
