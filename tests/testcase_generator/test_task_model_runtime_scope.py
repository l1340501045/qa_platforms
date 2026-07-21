import sys
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    get_current_model_bundle,
)
from src.platform_api.models.enums import BatchStatus
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
        self.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: self.case))
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def get(self, _model, _record_id):
        return self.case

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


async def test_pipeline_start_waits_for_dispatched_batch_commit(monkeypatch) -> None:
    bundle = _bundle()
    batch_id = uuid.uuid4()
    document_id = uuid.uuid4()
    system_id = uuid.uuid4()
    batch = SimpleNamespace(
        id=batch_id,
        document_id=document_id,
        system_id=system_id,
        taxonomy_version_id=None,
        status=BatchStatus.PENDING,
        current_stage=None,
        celery_task_id=None,
        started_at=None,
        generation_config=None,
    )

    class _DelayedBatchSession(_Session):
        def __init__(self):
            super().__init__()
            self.scalar_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else batch

    session = _DelayedBatchSession()
    load_bundle = AsyncMock(return_value=bundle)
    execute_graph = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        load_bundle,
    )
    monkeypatch.setattr(pipeline_task, "_execute_pipeline_graph", execute_graph)

    result = await pipeline_task._execute_pipeline(
        celery_task_id="celery-task",
        batch_id=str(batch_id),
        document_id=str(document_id),
        system_id=str(system_id),
        config={"profile": "test"},
    )

    assert result == {"status": "completed"}
    assert session.scalar_calls == 2
    assert batch.status == BatchStatus.RUNNING
    assert batch.current_stage == "parse"
    assert batch.celery_task_id == "celery-task"
    assert batch.generation_config == {"profile": "test"}
    session.commit.assert_awaited_once()
    load_bundle.assert_awaited_once_with(session)
    execute_graph.assert_awaited_once_with(
        str(batch_id),
        str(document_id),
        str(system_id),
        {"profile": "test"},
    )


async def test_resume_pipeline_uses_latest_model_when_execution_restarts(monkeypatch) -> None:
    bundle = _bundle()
    session = _Session(SimpleNamespace(status="suspended", taxonomy_version_id=None, current_stage=None))
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
            on_stage_progress=AsyncMock(),
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
    monkeypatch.setattr(
        "src.platform_api.services.review_service.lock_case_for_content_mutation",
        AsyncMock(side_effect=[case, case]),
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
    monkeypatch.setattr(
        "src.platform_api.services.review_service.lock_case_for_content_mutation",
        AsyncMock(return_value=case),
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


async def test_regenerate_case_rechecks_taxonomy_freeze_after_llm(monkeypatch) -> None:
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
    mutation_guard = AsyncMock(
        side_effect=[case, ApiError("E4092", "该批次的业务分类已固化")],
    )
    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: sessions.pop(0))
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        AsyncMock(return_value=bundle),
    )
    monkeypatch.setattr(
        "src.platform_api.services.review_service.lock_case_for_content_mutation",
        mutation_guard,
    )

    class _LLMClient:
        async def generate_structured(self, **_kwargs):
            return SimpleNamespace(
                title="不应落库的新标题",
                preconditions={},
                steps=[],
                expected_results={},
                priority="P1",
            )

    monkeypatch.setattr(
        "src.testcase_generator.services.llm_client.get_llm_client",
        lambda: _LLMClient(),
    )

    result = await regenerate_task._regenerate_case(str(case_id), "请修改")

    assert result == {"error": "case_not_mutable_after_llm"}
    assert case.title == "旧标题"
    assert mutation_guard.await_count == 2


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
            on_stage_progress=AsyncMock(),
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
