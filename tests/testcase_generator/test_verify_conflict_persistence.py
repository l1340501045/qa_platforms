"""verify 矛盾结果落库 — 复现/定位/回归。"""
from __future__ import annotations

import pytest

from src.testcase_generator.schemas.test_case import (
    CaseVerification,
    CrossSectionConflictRef,
    GeneratedTestCase,
    Provenance,
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


def test_langgraph_serde_preserves_cross_section_conflict():
    """_PIPELINE_SERDE round-trip 不丢 cross_section_conflict（无 unregistered-type 警告）"""
    import warnings

    from src.testcase_generator.pipeline.persistence import _PIPELINE_SERDE

    case = _case_with_conflict()
    payload = {"final_test_cases": [case]}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        type_, blob = _PIPELINE_SERDE.dumps_typed(payload)
        restored = _PIPELINE_SERDE.loads_typed((type_, blob))

    unregistered = [w for w in caught if "unregistered" in str(w.message).lower()]
    assert not unregistered, f"仍有 unregistered-type 警告: {[str(w.message) for w in unregistered]}"

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
    """_PIPELINE_SERDE round-trip 后全字段一致（回归护栏）"""
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

        async def execute(self, *a, **k):
            # 模拟 SELECT 返回空（无旧数据）
            class _R:
                def scalars(self):
                    return self

                def all(self):
                    return []

            return _R()

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
