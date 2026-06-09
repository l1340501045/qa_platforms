"""回归测试：review 审计阶段必须按功能点分批，不能把全部用例塞进单次请求。

根因背景：原实现把全部 test_points + test_cases（含完整步骤）一次性送审计，
大 PRD（~1500 条用例）单请求达 150 万+ token → 爆模型上下文窗口
（ContextWindowExceededError）→ 流水线在落库前整体失败。
改为按 feature 分批审计 + 聚合 + 失败隔离后，单请求规模受控。
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.stages.review import node as review_node_mod
from src.testcase_generator.stages.review.node import review_node, AuditLLMOutput
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.schemas.test_case import GeneratedTestCase, TestStep, Provenance


def _tp(tp_id: str, feature_id: str) -> TestPointSchema:
    return TestPointSchema(
        id=tp_id, feature_id=feature_id, dimension="functional_completeness",
        description="测试点描述", priority="P0", derived_from=["PRD §1"],
    )


def _tc(tc_id: str, tp_id: str) -> GeneratedTestCase:
    return GeneratedTestCase(
        id=tc_id, test_point_id=tp_id, title="用例",
        preconditions=["前置"],
        steps=[TestStep(step_number=1, action="点击", input_data="x", expected_result="ok")],
        expected_results=["ok"], priority="P0", dimensions=["functional_completeness"],
        provenance=Provenance(derived_from=["PRD §1"], source_section="s", verbatim_excerpt="", trust_level=1),
        trust_level=1, confidence_note="",
    )


def _state(n_features: int, cases_per_feature: int) -> dict:
    tps, tcs = [], []
    for f in range(n_features):
        fid = f"F-{f:03d}"
        for c in range(cases_per_feature):
            tp_id = f"TP-{f}-{c}"
            tps.append(_tp(tp_id, fid))
            tcs.append(_tc(f"TC-{f}-{c}", tp_id))
    return {"test_points": tps, "test_cases": tcs}


@pytest.mark.asyncio
async def test_review_audits_per_feature_not_single_call():
    state = _state(n_features=5, cases_per_feature=10)
    calls = {"n": 0}

    async def fake(*, system_prompt, user_content, output_schema, temperature):
        calls["n"] += 1
        return AuditLLMOutput(gaps=[], dimension_issues=[], supplement_cases=[])

    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(side_effect=fake)
    with patch.object(review_node_mod, "get_llm_client", return_value=fake_client):
        out = await review_node(state)

    # 5 个功能点 → 5 次审计调用（而非 1 次巨型调用）
    assert calls["n"] == 5
    # 用例集完整保留
    assert len(out["final_test_cases"]) == 50


@pytest.mark.asyncio
async def test_review_failure_isolated_per_feature():
    state = _state(n_features=4, cases_per_feature=5)
    calls = {"n": 0}

    async def flaky(*, system_prompt, user_content, output_schema, temperature):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("上下文超限")  # 某功能点审计失败
        return AuditLLMOutput(gaps=[], dimension_issues=[], supplement_cases=[])

    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(side_effect=flaky)
    with patch.object(review_node_mod, "get_llm_client", return_value=fake_client):
        out = await review_node(state)

    # 单功能点审计失败不应让整个 review 崩溃，原用例集仍完整产出
    assert len(out["final_test_cases"]) == 20
    assert out["audit_report"] is not None
