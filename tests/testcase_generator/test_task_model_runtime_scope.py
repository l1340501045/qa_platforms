import sys
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    get_current_model_bundle,
)
from src.testcase_generator.tasks import iterate_task, pipeline_task, regenerate_task


def _bundle() -> ModelConfigBundle:
    return ModelConfigBundle(
        version_id=uuid.uuid4(),
        revision=7,
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
    def __init__(self, case=None):
        self.case = case
        self.execute = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def get(self, _model, _record_id):
        return self.case

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


async def test_resume_pipeline_uses_latest_model_when_execution_restarts(monkeypatch) -> None:
    bundle = _bundle()
    session = _Session()
    load_bundle = AsyncMock(return_value=bundle)

    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        load_bundle,
    )

    class _Graph:
        async def astream(self, _input, config):
            assert config["configurable"]["thread_id"] == "batch-id"
            if False:
                yield None

        async def aget_state(self, _config):
            return SimpleNamespace(next=(), tasks=[], values={})

    @asynccontextmanager
    async def _checkpointer():
        yield object()

    def _compile_pipeline(*, checkpointer):
        assert checkpointer is not None
        assert get_current_model_bundle() is bundle
        return _Graph()

    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.persistence",
        SimpleNamespace(open_async_checkpointer=_checkpointer),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.runner",
        SimpleNamespace(compile_pipeline=_compile_pipeline),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.tasks.callbacks",
        SimpleNamespace(
            on_pipeline_complete=AsyncMock(),
            on_pipeline_failed=AsyncMock(),
            on_pipeline_suspended=AsyncMock(),
        ),
    )

    result = await pipeline_task._resume_pipeline("batch-id", [])

    assert result["status"] == "completed"
    load_bundle.assert_awaited_once_with(session)


async def test_iterate_batch_uses_latest_model_when_execution_starts(monkeypatch) -> None:
    bundle = _bundle()
    session = _Session()
    load_bundle = AsyncMock(return_value=bundle)

    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        load_bundle,
    )

    async def _iterate(_self, *, batch_id, modified_case_ids, feedback):
        assert get_current_model_bundle() is bundle
        assert modified_case_ids == ["case-id"]
        assert feedback == {"reason": "补充边界"}
        return []

    monkeypatch.setattr(
        "src.testcase_generator.services.iteration_service.IterationService.iterate",
        _iterate,
    )

    result = await iterate_task._iterate(
        str(uuid.uuid4()),
        ["case-id"],
        {"reason": "补充边界"},
    )

    assert result["status"] == "completed"
    load_bundle.assert_awaited_once()


async def test_iterate_batch_never_exposes_provider_error_text(monkeypatch, caplog) -> None:
    bundle = _bundle()
    session = _Session()
    secret = "sk-provider-secret-in-error"

    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        AsyncMock(return_value=bundle),
    )

    async def _iterate(_self, **_kwargs):
        raise RuntimeError(f"upstream rejected key {secret}")

    monkeypatch.setattr(
        "src.testcase_generator.services.iteration_service.IterationService.iterate",
        _iterate,
    )

    result = await iterate_task._iterate(str(uuid.uuid4()), [], {})

    assert result["status"] == "failed"
    assert "RuntimeError" in result["error"]
    assert secret not in str(result)
    assert secret not in caplog.text


async def test_regenerate_case_uses_latest_model_when_execution_starts(monkeypatch) -> None:
    bundle = _bundle()
    case_id = uuid.uuid4()
    case = SimpleNamespace(
        id=case_id,
        batch_id=uuid.uuid4(),
        test_point_id=None,
        title="旧标题",
        preconditions={},
        steps=[],
        expected_results={},
        priority="P1",
        iteration=1,
        review_status="approved",
        review_comment=None,
    )
    sessions = [_Session(case), _Session(case)]
    load_bundle = AsyncMock(return_value=bundle)

    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        load_bundle,
    )

    class _LLMClient:
        async def generate_structured(self, **_kwargs):
            assert get_current_model_bundle() is bundle
            return SimpleNamespace(
                title="新标题",
                preconditions={},
                steps=[],
                expected_results={},
                priority="P1",
            )

    monkeypatch.setattr(
        "src.testcase_generator.services.llm_client.get_llm_client",
        lambda: _LLMClient(),
    )

    result = await regenerate_task._regenerate_case(str(case_id), "请补充异常场景")

    assert result["status"] == "completed"
    assert case.title == "新标题"
    load_bundle.assert_awaited_once()


async def test_regenerate_case_never_exposes_provider_error_text(monkeypatch, caplog) -> None:
    bundle = _bundle()
    case_id = uuid.uuid4()
    secret = "sk-provider-secret-in-error"
    case = SimpleNamespace(
        id=case_id,
        batch_id=uuid.uuid4(),
        test_point_id=None,
        title="旧标题",
        preconditions={},
        steps=[],
        expected_results={},
        priority="P1",
        iteration=1,
        review_status="approved",
        review_comment=None,
    )
    session = _Session(case)

    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        AsyncMock(return_value=bundle),
    )

    class _LLMClient:
        async def generate_structured(self, **_kwargs):
            raise RuntimeError(f"upstream rejected key {secret}")

    monkeypatch.setattr(
        "src.testcase_generator.services.llm_client.get_llm_client",
        lambda: _LLMClient(),
    )

    result = await regenerate_task._regenerate_case(str(case_id), "请补充异常场景")

    assert "RuntimeError" in result["error"]
    assert secret not in str(result)
    assert secret not in caplog.text


async def test_pipeline_failure_never_exposes_provider_error_text(monkeypatch, caplog) -> None:
    secret = "sk-provider-secret-in-error"
    failed_callback = AsyncMock()

    @asynccontextmanager
    async def _checkpointer():
        yield object()

    def _compile_pipeline(*, checkpointer):
        assert checkpointer is not None
        raise RuntimeError(f"upstream rejected key {secret}")

    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.persistence",
        SimpleNamespace(open_async_checkpointer=_checkpointer),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.runner",
        SimpleNamespace(compile_pipeline=_compile_pipeline),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.tasks.callbacks",
        SimpleNamespace(
            on_pipeline_complete=AsyncMock(),
            on_pipeline_failed=failed_callback,
            on_pipeline_suspended=AsyncMock(),
            on_stage_complete=AsyncMock(),
        ),
    )

    result = await pipeline_task._execute_pipeline_graph(
        "batch-id",
        "document-id",
        "system-id",
        {},
    )

    assert result["status"] == "failed"
    assert "RuntimeError" in result["error"]
    assert secret not in str(result)
    assert secret not in caplog.text
    assert secret not in str(failed_callback.await_args)
