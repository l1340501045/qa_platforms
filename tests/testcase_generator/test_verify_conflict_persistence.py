"""verify 矛盾结果落库 — 复现/定位/回归。"""
from __future__ import annotations

import pytest

from src.testcase_generator.schemas.test_case import (
    CaseVerification,
    CrossSectionConflictRef,
    GeneratedTestCase,
    Provenance,
    TestStep as _TestStep,
)


def _case_with_conflict() -> GeneratedTestCase:
    return GeneratedTestCase(
        id="TC-0001",
        test_point_id="TP-001",
        title="t",
        priority="P0",
        trust_level=3,
        provenance=Provenance(
            source_section="§x", verbatim_excerpt="e", trust_level=1
        ),
        steps=[
            _TestStep(
                step_number=1,
                action="点击提交",
                input_data="",
                expected_result="显示成功",
                source_quote="提交按钮应触发校验",
                source_ref="§3.1",
            )
        ],
        verification=CaseVerification(
            verdict="grounded",
            bucket="main",
            cross_section_conflict=True,
            conflicting_refs=[
                CrossSectionConflictRef(
                    ref_a="§5.6",
                    quote_a="组长可查看所有人",
                    ref_b="§10.2",
                    quote_b="组长看本组",
                )
            ],
        ),
    )


# ─── Task 1: serde 层 round-trip（使用生产实际配置的 _PIPELINE_SERDE）───


def test_langgraph_serde_no_unregistered_log(caplog):
    """_PIPELINE_SERDE round-trip 无 unregistered/blocked 日志（caplog 捕 logging 层，非 warnings）"""
    import logging

    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    payload = {"final_test_cases": [_case_with_conflict()]}
    with caplog.at_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus"):
        t, blob = _PIPELINE_SERDE.dumps_typed(payload)
        _PIPELINE_SERDE.loads_typed((t, blob))
    bad = [
        r.getMessage()
        for r in caplog.records
        if "unregistered" in r.getMessage().lower() or "blocked" in r.getMessage().lower()
    ]
    assert not bad, f"仍有 unregistered/blocked 日志: {bad}"


def test_langgraph_serde_preserves_cross_section_conflict():
    """_PIPELINE_SERDE round-trip 不丢 cross_section_conflict"""
    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    case = _case_with_conflict()
    payload = {"final_test_cases": [case]}
    type_, blob = _PIPELINE_SERDE.dumps_typed(payload)
    restored = _PIPELINE_SERDE.loads_typed((type_, blob))

    rc = restored["final_test_cases"][0]
    assert rc.verification.cross_section_conflict is True, "serde 丢失了 cross_section_conflict"


def test_langgraph_serde_preserves_conflicting_refs():
    """_PIPELINE_SERDE round-trip 保留 conflicting_refs 列表"""
    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    case = _case_with_conflict()
    payload = {"final_test_cases": [case]}
    type_, blob = _PIPELINE_SERDE.dumps_typed(payload)
    restored = _PIPELINE_SERDE.loads_typed((type_, blob))
    rc = restored["final_test_cases"][0]
    refs = rc.verification.conflicting_refs
    assert refs and len(refs) == 1, "serde 丢失了 conflicting_refs"


def test_langgraph_serde_full_field_roundtrip():
    """_PIPELINE_SERDE round-trip 后全字段一致（含 TestStep）"""
    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    case = _case_with_conflict()
    original_dump = case.model_dump()
    payload = {"final_test_cases": [case]}
    type_, blob = _PIPELINE_SERDE.dumps_typed(payload)
    restored = _PIPELINE_SERDE.loads_typed((type_, blob))
    rc = restored["final_test_cases"][0]
    restored_dump = rc.model_dump()
    assert restored_dump == original_dump, (
        f"round-trip 前后不一致:\n"
        f"  丢失/变化的 keys: {set(original_dump) - set(restored_dump)}"
    )


def test_serde_unregistered_type_degrades_to_dict():
    """未注册顶层类型经 _PIPELINE_SERDE round-trip 降级为 dict（allowlist 有实际约束的证明）"""
    from pydantic import BaseModel

    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    class _NotRegisteredForTest(BaseModel):
        value: int = 42

    obj = _NotRegisteredForTest(value=99)
    payload = {"top": obj}
    type_, blob = _PIPELINE_SERDE.dumps_typed(payload)
    restored = _PIPELINE_SERDE.loads_typed((type_, blob))
    # 白名单外类型 → 降级成 dict（不是 _NotRegisteredForTest）
    assert isinstance(restored["top"], dict), (
        f"期望 dict（降级），实际得到 {type(restored['top']).__name__}"
    )
    assert restored["top"]["value"] == 99


# ─── Task 2: 落库层 ───


@pytest.mark.asyncio
async def test_on_pipeline_complete_persists_cross_section_conflict(monkeypatch):
    """on_pipeline_complete 落库时 verification 含 cross_section_conflict"""
    from src.testcase_generator.tasks import callbacks as cb

    added = []

    class _FakeSession:
        def add(self, obj):
            added.append(obj)

        async def flush(self): ...
        async def commit(self): ...
        async def execute(self, *a, **k): ...  # on_pipeline_complete 仅 INSERT + UPDATE，无 SELECT

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...

    monkeypatch.setattr(cb, "async_session_factory", lambda: _FakeSession())

    case = _case_with_conflict().model_dump()
    await cb.on_pipeline_complete(
        batch_id="00000000-0000-0000-0000-000000000001",
        final_cases=[case],
        audit_report={},
        test_points=[],
        rules=[],
    )
    tc = [o for o in added if o.__class__.__name__ == "TestCase"][0]
    assert (tc.verification or {}).get("cross_section_conflict") is True
