"""按批次 generation_config 覆盖质量开关。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.platform_api.core.settings import settings
from src.testcase_generator.pipeline.config import (
    BEST_PRACTICE_GENERATION_CONFIG,
    effective_settings,
)
from src.testcase_generator.schemas.test_case import GeneratedTestCase, Provenance, TestStep
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.stages.dedup.node import dedup_node


def _case(case_id: str, tp_id: str, title: str) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=case_id,
        test_point_id=tp_id,
        title=title,
        preconditions=[],
        steps=[TestStep(step_number=1, action="执行操作", input_data="", expected_result="显示正确")],
        expected_results=["显示正确"],
        priority="P1",
        dimensions=["functional_correctness"],
        provenance=Provenance(
            derived_from=[],
            source_section="§5.1",
            verbatim_excerpt="摘录",
            trust_level=3,
        ),
        trust_level=3,
    )


def _tp(tp_id: str, rule_id: str) -> TestPointSchema:
    return TestPointSchema(
        id=tp_id,
        feature_id="F-001",
        dimension="functional_correctness",
        description="测试点",
        priority="P1",
        rule_id=rule_id,
    )


def test_effective_settings_prefers_generation_config(monkeypatch):
    monkeypatch.setattr(settings, "safe_dedup_enabled", False)

    runtime = effective_settings({"generation_config": {"safe_dedup_enabled": True}})

    assert runtime.safe_dedup_enabled is True


def test_effective_settings_falls_back_to_global_settings(monkeypatch):
    monkeypatch.setattr(settings, "safe_dedup_enabled", False)

    runtime = effective_settings({"generation_config": {}})

    assert runtime.safe_dedup_enabled is False


def test_frontend_best_practice_config_matches_backend_contract():
    """前端触发批次时必须显式传完整 best-practice 配置，避免审计只能靠默认值推断。"""
    frontend = (Path(__file__).parents[2] / "web" / "src" / "services" / "batchApi.ts").read_text(encoding="utf-8")
    start = frontend.index("export const BEST_PRACTICE_GENERATION_CONFIG = {")
    body = frontend[start : frontend.index("};", start)]

    parsed: dict[str, object] = {}
    for raw_line in body.splitlines()[1:]:
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if value == "true":
            parsed[key] = True
        elif value == "false":
            parsed[key] = False
        elif value.startswith("'") and value.endswith("'"):
            parsed[key] = value.strip("'")
        else:
            parsed[key] = int(value) if value.isdigit() else float(value)

    assert parsed == BEST_PRACTICE_GENERATION_CONFIG


@pytest.mark.asyncio
async def test_dedup_node_uses_generation_config_safe_dedup(monkeypatch):
    """配置开启 safe_dedup 时，即使全局默认关，也保护不同规则的唯一代表。"""
    monkeypatch.setattr(settings, "safe_dedup_enabled", False)

    state = {
        "generation_config": {"safe_dedup_enabled": True},
        "test_points": [_tp("TP-1", "R-001"), _tp("TP-2", "R-002")],
        "final_test_cases": [
            _case("TC-1", "TP-1", "切换每页显示条数为10条，验证列表数据条数正确"),
            _case("TC-2", "TP-2", "切换每页显示条数为50条，验证列表数据条数正确"),
        ],
    }

    out = await dedup_node(state)
    cases = out["final_test_cases"]

    assert all(c.duplicate_of is None for c in cases)
