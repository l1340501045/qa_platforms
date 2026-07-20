import importlib
import inspect
import sys
import uuid
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace

import pytest

from src.platform_api.core.model_runtime import (
    ModelConfigBundle,
    ModelEndpointConfig,
    ModelRole,
    get_current_model_bundle,
)
from src.testcase_generator.cli import rule_coverage_probe


def _bundle() -> ModelConfigBundle:
    version_id = uuid.uuid4()
    return ModelConfigBundle(
        version_id=version_id,
        revision=9,
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


@pytest.fixture
def pipeline_runner(monkeypatch):
    """隔离 runner 的完整图导入，避免单测收集所有流水线节点。"""
    runner_module_name = "src.testcase_generator.pipeline.runner"
    graph_module_name = "src.testcase_generator.pipeline.graph"
    previous_runner = sys.modules.pop(runner_module_name, None)
    graph_module = ModuleType(graph_module_name)
    graph_module.build_pipeline = lambda: None
    monkeypatch.setitem(sys.modules, graph_module_name, graph_module)

    checkpoint_module = ModuleType("langgraph.checkpoint.base")
    checkpoint_module.BaseCheckpointSaver = object
    graph_state_module = ModuleType("langgraph.graph.state")
    graph_state_module.CompiledStateGraph = object

    class _Command:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    command_module = ModuleType("langgraph.types")
    command_module.Command = _Command
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.base", checkpoint_module)
    monkeypatch.setitem(sys.modules, "langgraph.graph.state", graph_state_module)
    monkeypatch.setitem(sys.modules, "langgraph.types", command_module)
    module = importlib.import_module(runner_module_name)
    try:
        yield module
    finally:
        sys.modules.pop(runner_module_name, None)
        if previous_runner is not None:
            sys.modules[runner_module_name] = previous_runner


def test_public_pipeline_runners_require_explicit_model_bundle(pipeline_runner) -> None:
    for public_runner in (pipeline_runner.run_pipeline, pipeline_runner.resume_pipeline):
        parameter = inspect.signature(public_runner).parameters["model_bundle"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


async def test_public_pipeline_runners_reject_explicit_null_bundle(pipeline_runner) -> None:
    with pytest.raises(ValueError, match="model_bundle"):
        await pipeline_runner.run_pipeline("document-id", "system-id", "batch-id", model_bundle=None)

    with pytest.raises(ValueError, match="model_bundle"):
        await pipeline_runner.resume_pipeline("thread-id", [], model_bundle=None)


async def test_run_pipeline_uses_supplied_model_bundle_for_compile_and_stream(monkeypatch, pipeline_runner) -> None:
    bundle = _bundle()

    class _Graph:
        async def astream(self, graph_input, *, config):
            assert get_current_model_bundle() is bundle
            assert graph_input["batch_id"] == "batch-id"
            assert config["configurable"]["thread_id"] == "thread-id"
            yield {"verify": {"status": "completed"}}

    def _compile_pipeline():
        assert get_current_model_bundle() is bundle
        return _Graph()

    monkeypatch.setattr(pipeline_runner, "compile_pipeline", _compile_pipeline)

    result = await pipeline_runner.run_pipeline(
        document_id="document-id",
        system_id="system-id",
        batch_id="batch-id",
        thread_id="thread-id",
        model_bundle=bundle,
    )

    assert result == {"status": "completed"}


async def test_resume_pipeline_uses_supplied_model_bundle_for_compile_and_stream(monkeypatch, pipeline_runner) -> None:
    bundle = _bundle()

    class _Graph:
        async def astream(self, _graph_input, *, config):
            assert get_current_model_bundle() is bundle
            assert config["configurable"]["thread_id"] == "thread-id"
            yield {"export": {"status": "completed"}}

    def _compile_pipeline():
        assert get_current_model_bundle() is bundle
        return _Graph()

    monkeypatch.setattr(pipeline_runner, "compile_pipeline", _compile_pipeline)

    result = await pipeline_runner.resume_pipeline(
        thread_id="thread-id",
        clarification_answers=[],
        model_bundle=bundle,
    )

    assert result == {"status": "completed"}


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


async def test_rule_coverage_probe_loads_latest_bundle_before_creating_client(monkeypatch, tmp_path) -> None:
    bundle = _bundle()
    batch = SimpleNamespace(id=uuid.uuid4(), document_id=uuid.uuid4())
    session = _Session()
    client = object()
    events: list[str] = []

    async def _resolve_batch(received_session, batch_prefix):
        assert received_session is session
        assert batch_prefix == str(batch.id)[:8]
        events.append("resolve")
        return batch

    async def _fetch_cases(received_session, batch_id):
        assert received_session is session
        assert batch_id == batch.id
        events.append("fetch")
        return []

    async def _load_bundle(received_session):
        assert received_session is session
        events.append("load")
        return bundle

    def _get_client():
        assert get_current_model_bundle() is bundle
        events.append("client")
        return client

    async def _build_ledger(document_id, received_client, ledger_path):
        assert get_current_model_bundle() is bundle
        assert document_id == batch.document_id
        assert received_client is client
        assert ledger_path is None
        events.append("ledger")
        return {"total": 0, "failed_units": 0, "rules": []}

    async def _judge_all(_ledger, _cases, received_client):
        assert get_current_model_bundle() is bundle
        assert received_client is client
        events.append("judge")
        return {
            "total_rules": 0,
            "judged_rules": 0,
            "covered": 0,
            "missed": 0,
            "coverage": 0.0,
            "failed_modules": 0,
            "by_module": [],
        }

    monkeypatch.setattr(rule_coverage_probe, "OUT_DIR", tmp_path)
    monkeypatch.setattr(rule_coverage_probe, "_resolve_batch", _resolve_batch)
    monkeypatch.setattr(rule_coverage_probe, "_fetch_cases", _fetch_cases)
    monkeypatch.setattr(rule_coverage_probe, "_build_ledger", _build_ledger)
    monkeypatch.setattr(rule_coverage_probe, "_judge_all", _judge_all)
    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        _load_bundle,
    )
    monkeypatch.setattr("src.testcase_generator.services.llm_client.get_llm_client", _get_client)

    args = SimpleNamespace(batch_id=str(batch.id)[:8], freeze=False, ledger=None)
    await rule_coverage_probe._run(args)

    assert events == ["resolve", "fetch", "load", "client", "ledger", "judge"]


async def test_reverify_batch_runs_verify_dedup_and_persist_in_batch_scope(monkeypatch) -> None:
    from scripts import reverify_batch
    from src.testcase_generator.schemas.parsed_context import ParsedContext

    bundle = _bundle()
    batch_id = str(uuid.uuid4())
    session = _Session()
    events: list[str] = []
    state = {
        "parsed_context": ParsedContext(),
        "final_test_cases": [{"id": "case-1"}],
        "test_points": [],
        "rules": [],
    }

    async def _load_bundle(received_session):
        assert received_session is session
        events.append("load")
        return bundle

    class _Graph:
        async def aget_state(self, config):
            assert config["configurable"]["thread_id"] == batch_id
            return SimpleNamespace(values=state)

    @asynccontextmanager
    async def _open_checkpointer():
        yield object()

    async def _verify(received_state):
        assert received_state is not None
        assert get_current_model_bundle() is bundle
        events.append("verify")
        return {"verify_summary": {"total": 1, "cross_section_conflicts": 0}}

    async def _dedup(received_state):
        assert received_state is not None
        assert get_current_model_bundle() is bundle
        events.append("dedup")
        return {"dedup_summary": {"total": 1, "duplicate_count": 0}}

    async def _clear(received_batch_id):
        assert received_batch_id == batch_id
        assert get_current_model_bundle() is bundle
        events.append("clear")
        return (1, 1, 1)

    async def _persist(**kwargs):
        assert kwargs["batch_id"] == batch_id
        assert get_current_model_bundle() is bundle
        events.append("persist")

    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.persistence",
        SimpleNamespace(open_async_checkpointer=_open_checkpointer),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.pipeline.runner",
        SimpleNamespace(compile_pipeline=lambda *, checkpointer: _Graph()),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.stages.verify.node",
        SimpleNamespace(verify_node=_verify),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.stages.dedup.node",
        SimpleNamespace(dedup_node=_dedup),
    )
    monkeypatch.setitem(
        sys.modules,
        "src.testcase_generator.tasks.callbacks",
        SimpleNamespace(on_pipeline_complete=_persist),
    )
    monkeypatch.setattr(reverify_batch, "_clear_old_records", _clear)
    monkeypatch.setattr("src.testcase_generator.db.async_session_factory", lambda: session)
    monkeypatch.setattr(
        "src.platform_api.services.task_model_runtime.load_active_model_bundle",
        _load_bundle,
    )
    monkeypatch.setattr(reverify_batch, "async_session_factory", lambda: session, raising=False)
    monkeypatch.setattr(reverify_batch, "load_active_model_bundle", _load_bundle, raising=False)

    await reverify_batch.main(batch_id)

    assert events == ["load", "verify", "dedup", "clear", "persist"]
