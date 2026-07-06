"""Task 2.2 — review 规则级覆盖闸测试。

规则「被覆盖」= 其锚点测试点（携 rule_id）至少 1 条用例。
未覆盖（锚点无用例）或无锚点的规则进入 uncovered_rule_codes，交 backfill。
开关关时为默认值（total_rules=0），行为与历史一致。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.stages.review import node as review_node_mod
from src.testcase_generator.stages.review.node import AuditLLMOutput, review_node
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.schemas.test_case import GeneratedTestCase, TestStep, Provenance


def _tp(tp_id: str, rule_id: str | None) -> TestPointSchema:
    return TestPointSchema(
        id=tp_id, feature_id="F-001", dimension="access_control",
        description="规则锚点" if rule_id else "维度测试点", priority="P0",
        derived_from=["PRD §5.1"], rule_id=rule_id,
    )


def _tc(tc_id: str, tp_id: str) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=tc_id, test_point_id=tp_id, title="用例",
        preconditions=["前置"],
        steps=[TestStep(step_number=1, action="操作", input_data="x", expected_result="ok")],
        expected_results=["ok"], priority="P0", dimensions=["access_control"],
        provenance=Provenance(derived_from=["PRD §5.1"], source_section="s", verbatim_excerpt="", trust_level=5),
        trust_level=5, confidence_note="",
    )


def _state() -> dict:
    # R-001 锚点 TP-001 有用例 → 覆盖；R-002 锚点 TP-002 无用例 → 漏；R-003 无锚点 → 漏
    test_points = [
        _tp("TP-001", "R-001"),
        _tp("TP-002", "R-002"),
        _tp("TP-003", None),  # 维度增强，不计规则
    ]
    test_cases = [_tc("TC-001", "TP-001"), _tc("TC-003", "TP-003")]
    rules = [
        {"rule_code": "R-001", "module": "5.1", "rule": "r1", "category": "权限"},
        {"rule_code": "R-002", "module": "5.1", "rule": "r2", "category": "权限"},
        {"rule_code": "R-003", "module": "5.2", "rule": "r3", "category": "功能"},
    ]
    return {"test_points": test_points, "test_cases": test_cases, "rules": rules}


async def _run(monkeypatch, gate: bool):
    monkeypatch.setattr(review_node_mod.settings, "rule_coverage_gate_enabled", gate)
    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(
        return_value=AuditLLMOutput(gaps=[], dimension_issues=[], supplement_cases=[])
    )
    with patch.object(review_node_mod, "get_llm_client", return_value=fake_client):
        out = await review_node(_state())
    return out["audit_report"]


@pytest.mark.asyncio
async def test_gate_on_reports_uncovered_rules(monkeypatch):
    rep = await _run(monkeypatch, gate=True)
    assert rep.total_rules == 3
    assert rep.covered_rules == 1  # 仅 R-001
    assert rep.uncovered_rule_codes == ["R-002", "R-003"]  # 漏锚 + 无锚
    assert abs(rep.rule_coverage - 1 / 3) < 1e-6


@pytest.mark.asyncio
async def test_gate_off_is_noop(monkeypatch):
    rep = await _run(monkeypatch, gate=False)
    assert rep.total_rules == 0
    assert rep.covered_rules == 0
    assert rep.uncovered_rule_codes == []
    assert rep.rule_coverage == 1.0
