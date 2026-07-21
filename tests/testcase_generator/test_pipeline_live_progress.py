"""流水线实时进度回调测试。"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.testcase_generator.tasks import pipeline_task


async def test_execute_pipeline_graph_updates_progress_as_stream_events_arrive(monkeypatch):
    """LangGraph 每个节点完成后应立即推进 batch.current_stage。"""
    progress_calls: list[str] = []
    completed_calls: list[tuple[str, str | None]] = []

    class _FakeApp:
        async def astream(self, _initial_state, config):
            assert config == {"configurable": {"thread_id": "batch-id"}}
            yield {"parse": {"current_stage": "parse"}}
            yield {"comprehend": {"current_stage": "comprehend", "gate_result": "GO"}}
            yield {"rule_extract": {"current_stage": "rule_extract", "rules": []}}
            yield {"test_points": {"current_stage": "test_points", "test_points": []}}
            yield {"write_cases": {"current_stage": "write_cases", "test_cases": []}}
            yield {"review": {"current_stage": "review", "final_test_cases": [], "audit_report": {}}}
            yield {"verify": {"current_stage": "verify", "verify_summary": {}}}
            yield {"dedup": {"current_stage": "dedup", "dedup_summary": {}}}
            yield {"export": {"current_stage": "export", "yaml_output": "", "markdown_output": ""}}

        async def aget_state(self, _config):
            return SimpleNamespace(next=())

    @asynccontextmanager
    async def _checkpointer():
        yield object()

    def _compile_pipeline(*, checkpointer):
        assert checkpointer is not None
        return _FakeApp()

    async def _on_stage_progress(*, batch_id: str, stage: str):
        assert batch_id == "batch-id"
        progress_calls.append(stage)

    async def _on_stage_complete(*, batch_id: str, stage: str, artifact: dict, current_stage: str | None = None):
        assert batch_id == "batch-id"
        completed_calls.append((stage, current_stage))

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
            on_stage_complete=_on_stage_complete,
            on_stage_progress=_on_stage_progress,
        ),
    )

    result = await pipeline_task._execute_pipeline_graph(
        "batch-id",
        "document-id",
        "system-id",
        {},
    )

    assert result == {"status": "completed", "batch_id": "batch-id"}
    assert progress_calls == [
        "parse",
        "comprehend",
        "gate",
        "test_points",
        "write_cases",
        "review",
        "review",
        "review",
        "export",
        "export",
    ]
    assert completed_calls == []
