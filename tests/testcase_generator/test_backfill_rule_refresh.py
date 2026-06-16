"""Task 2.3 — backfill 回填后刷新规则级覆盖。

回填令未覆盖规则的锚点测试点重新拿到用例后，audit_report 的规则覆盖字段须同步刷新，
使最终落库/导出反映回填后的真实规则覆盖。gate 关时不触碰规则字段。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.stages.review import backfill_node as bf_mod
from src.testcase_generator.stages.review.backfill_node import backfill_node
from src.testcase_generator.schemas.audit_report import AuditReport
from src.testcase_generator.schemas.parsed_context import ParsedContext
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.schemas.test_case import GeneratedTestCase, TestStep, Provenance

SYS_ID = "22222222-2222-2222-2222-222222222222"


def _tp(tp_id: str, rule_id: str | None) -> TestPointSchema:
    return TestPointSchema(
        id=tp_id, feature_id="F-001", dimension="access_control",
        description="锚点", priority="P0", derived_from=["PRD §5"], rule_id=rule_id,
    )


def _tc(tc_id: str, tp_id: str) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=tc_id, test_point_id=tp_id, title="用例", preconditions=["前置"],
        steps=[TestStep(step_number=1, action="操作", input_data="x", expected_result="ok")],
        expected_results=["ok"], priority="P0", dimensions=["access_control"],
        provenance=Provenance(derived_from=["PRD §5"], source_section="s", verbatim_excerpt="", trust_level=5),
        trust_level=5, confidence_note="",
    )


def _state() -> dict:
    test_points = [_tp("TP-001", "R-001"), _tp("TP-002", "R-002")]
    audit = AuditReport(
        total_test_points=2, per_test_point_covered=1,
        uncovered_test_point_ids=["TP-002"], weak_coverage_test_point_ids=[],
        dimension_cell_total=2, dimension_cell_covered=1, dimension_cell_coverage=0.5,
        total_rules=2, covered_rules=1, rule_coverage=0.5, uncovered_rule_codes=["R-002"],
    )
    return {
        "test_points": test_points,
        "final_test_cases": [_tc("TC-001", "TP-001")],
        "audit_report": audit,
        "parsed_context": ParsedContext(sources=[], features=[]),
        "system_id": SYS_ID,
        "reconcile_iterations": 0,
        "rules": [
            {"rule_code": "R-001", "module": "5.1", "rule": "r1", "category": "权限"},
            {"rule_code": "R-002", "module": "5.2", "rule": "r2", "category": "权限"},
        ],
    }


@pytest.mark.asyncio
async def test_backfill_refreshes_rule_coverage_when_gate_on(monkeypatch):
    monkeypatch.setattr(bf_mod.settings, "rule_coverage_gate_enabled", True)
    # 回填为 TP-002（R-002 锚点）生成用例
    fake_gen = AsyncMock(return_value=([_tc("TC-100", "TP-002")], []))
    with patch.object(bf_mod, "generate_cases", fake_gen):
        out = await backfill_node(_state())

    rep = out["audit_report"]
    assert rep.uncovered_test_point_ids == []  # TP-002 已补
    assert rep.covered_rules == 2  # R-001 + R-002
    assert rep.uncovered_rule_codes == []
    assert rep.rule_coverage == 1.0


@pytest.mark.asyncio
async def test_backfill_leaves_rule_fields_when_gate_off(monkeypatch):
    monkeypatch.setattr(bf_mod.settings, "rule_coverage_gate_enabled", False)
    fake_gen = AsyncMock(return_value=([_tc("TC-100", "TP-002")], []))
    with patch.object(bf_mod, "generate_cases", fake_gen):
        out = await backfill_node(_state())

    rep = out["audit_report"]
    # gate 关：覆盖回填仍发生（TP 级），但规则字段保持 review 传入值不被本节点改写
    assert rep.uncovered_test_point_ids == []
    assert rep.covered_rules == 1
    assert rep.uncovered_rule_codes == ["R-002"]
