import inspect
import uuid
from unittest.mock import AsyncMock

import pytest

from src.knowledge_base.tasks import parse_task
from src.knowledge_base.tasks.parse_task import parse_batch_task, parse_document_task
from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    get_current_model_bundle,
)


def test_parse_tasks_select_model_when_worker_starts() -> None:
    assert set(inspect.signature(parse_document_task.run).parameters) == {"document_id"}
    assert set(inspect.signature(parse_batch_task.run).parameters) == {"document_ids"}


def _bundle(version_id: uuid.UUID) -> ModelConfigBundle:
    return ModelConfigBundle(
        version_id=version_id,
        revision=4,
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


class _Session:
    def __init__(self):
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


async def test_parse_document_runs_inside_latest_active_model_scope(monkeypatch) -> None:
    runner = getattr(parse_task, "_parse_document", None)
    assert runner is not None

    version_id = uuid.uuid4()
    bundle = _bundle(version_id)
    session = _Session()

    monkeypatch.setattr("src.knowledge_base.db.async_session_factory", lambda: session)

    async def _load_bundle(_self):
        return bundle

    async def _parse_document(_self, document_id):
        assert document_id == uuid.UUID("11111111-1111-1111-1111-111111111111")
        assert get_current_model_bundle() is bundle
        return True

    monkeypatch.setattr(
        "src.platform_api.services.model_settings_service.ModelSettingsService.load_active_bundle",
        _load_bundle,
    )
    monkeypatch.setattr(
        "src.knowledge_base.services.parse_service.ParseService.parse_document",
        _parse_document,
    )

    result = await runner("11111111-1111-1111-1111-111111111111")

    assert result is True
    session.commit.assert_awaited_once()


async def test_parse_batch_runs_inside_latest_active_model_scope(monkeypatch) -> None:
    runner = getattr(parse_task, "_parse_batch", None)
    assert runner is not None

    version_id = uuid.uuid4()
    bundle = _bundle(version_id)
    session = _Session()
    document_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    monkeypatch.setattr("src.knowledge_base.db.async_session_factory", lambda: session)

    async def _load_bundle(_self):
        return bundle

    async def _parse_batch(_self, document_ids):
        assert document_ids == [document_id]
        assert get_current_model_bundle() is bundle
        return {document_id: True}

    monkeypatch.setattr(
        "src.platform_api.services.model_settings_service.ModelSettingsService.load_active_bundle",
        _load_bundle,
    )
    monkeypatch.setattr(
        "src.knowledge_base.services.parse_service.ParseService.parse_batch",
        _parse_batch,
    )

    result = await runner([str(document_id)])

    assert result == {str(document_id): True}
    session.commit.assert_awaited_once()


def test_parse_document_task_sanitizes_retry_error(monkeypatch, caplog) -> None:
    secret = "sk-provider-secret-in-error"
    retried: dict = {}

    class _RetriedError(Exception):
        pass

    monkeypatch.setattr(parse_task, "_parse_document", lambda *_args: object())
    monkeypatch.setattr(
        parse_task,
        "_run_async",
        lambda _awaitable: (_ for _ in ()).throw(RuntimeError(f"upstream rejected key {secret}")),
    )

    def _retry(**kwargs):
        retried.update(kwargs)
        raise _RetriedError

    monkeypatch.setattr(parse_document_task, "retry", _retry)

    with pytest.raises(_RetriedError):
        parse_document_task.run("11111111-1111-1111-1111-111111111111")

    assert secret not in caplog.text
    assert secret not in str(retried)
    assert "RuntimeError" in str(retried["exc"])


def test_parse_batch_task_sanitizes_worker_error(monkeypatch, caplog) -> None:
    secret = "sk-provider-secret-in-error"

    monkeypatch.setattr(parse_task, "_parse_batch", lambda *_args: object())
    monkeypatch.setattr(
        parse_task,
        "_run_async",
        lambda _awaitable: (_ for _ in ()).throw(RuntimeError(f"upstream rejected key {secret}")),
    )

    with pytest.raises(RuntimeError) as raised:
        parse_batch_task.run(["22222222-2222-2222-2222-222222222222"])

    assert "RuntimeError" in str(raised.value)
    assert secret not in str(raised.value)
    assert secret not in caplog.text
