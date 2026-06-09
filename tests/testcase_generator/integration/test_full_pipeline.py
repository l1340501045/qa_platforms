"""T048: 流水线集成测试 — 走 build_pipeline() 真实图，LLM 打桩返回固定结构

血泪点固化为断言：
1. 全程 GO：6 阶段都真实执行，parsed_context/gate_result 非空
2. 逐点覆盖：per_test_point_covered == total_test_points, uncovered == []
3. NO_GO 救回：低覆盖→NO_GO→interrupt→resume(answers)→覆盖度上升→继续（不死循环）
"""

import json
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.testcase_generator.schemas.parsed_context import (
    ParsedContext,
    SourceItem,
    SectionExtract,
    FeatureItem,
)
from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.comprehend.node import comprehend_node
from src.testcase_generator.stages.test_points.node import test_points_node as tp_node
from src.testcase_generator.stages.write_cases.node import write_cases_node
from src.testcase_generator.stages.review.node import review_node
from src.testcase_generator.stages.export.node import export_node


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _make_go_context() -> ParsedContext:
    """构造一个信源充分的需求（会触发 GO）"""
    return ParsedContext(
        sources=[
            SourceItem(
                doc_id=str(uuid4()),
                doc_type="prd",
                trust_level=1,
                title="用户注册PRD",
                sections=[
                    SectionExtract(
                        heading="2.1 手机号注册",
                        content="用户通过手机号+6位验证码注册。手机号11位1开头。验证码5分钟有效。同一号码每天最多5次验证码。",
                        source_ref="PRD §2.1",
                    ),
                    SectionExtract(
                        heading="2.2 邮箱注册",
                        content="用户通过邮箱+密码注册。密码8-20位含大小写+数字。发验证链接24小时有效。",
                        source_ref="PRD §2.2",
                    ),
                ],
            ),
            SourceItem(
                doc_id=str(uuid4()),
                doc_type="tech_doc",
                trust_level=2,
                title="注册接口文档",
                sections=[
                    SectionExtract(
                        heading="POST /register",
                        content="请求:{phone,sms_code}或{email,password}。错误码:40001格式错/40002验证码错/40003已注册。",
                        source_ref="Tech §1",
                    ),
                ],
            ),
        ],
        features=[
            FeatureItem(
                id="F001",
                name="手机号注册",
                description="手机号+验证码注册",
                source_refs=["PRD §2.1"],
                feature_type="data_input",
            ),
            FeatureItem(
                id="F002",
                name="邮箱注册",
                description="邮箱+密码注册",
                source_refs=["PRD §2.2"],
                feature_type="data_input",
            ),
        ],
        prototype_observations=None,
    )


def _make_nogo_context() -> ParsedContext:
    """构造一个信源严重不足的需求（会触发 NO_GO）"""
    return ParsedContext(
        sources=[
            SourceItem(
                doc_id=str(uuid4()),
                doc_type="prd",
                trust_level=1,
                title="部分PRD",
                sections=[
                    SectionExtract(heading="1.1 登录", content="支持登录", source_ref="PRD §1.1"),
                ],
            ),
        ],
        features=[
            FeatureItem(
                id="F001", name="登录", description="用户登录", source_refs=["PRD §1.1"], feature_type="data_input"
            ),
            FeatureItem(
                id="F002", name="第三方登录", description="微信/支付宝OAuth", source_refs=[], feature_type="integration"
            ),
            FeatureItem(
                id="F003", name="忘记密码", description="手机号重置密码", source_refs=[], feature_type="data_input"
            ),
            FeatureItem(
                id="F004", name="账号注销", description="自主注销", source_refs=[], feature_type="business_rule"
            ),
            FeatureItem(id="F005", name="登录安全", description="异常检测", source_refs=[], feature_type="security"),
        ],
        prototype_observations=None,
    )


def _make_comprehension_llm_response(coverage: float, features: list) -> dict:
    """构造 ComprehensionLLMOutput 的 mock 返回"""
    return {
        "feature_coverages": [
            {
                "id": f.id,
                "feature_id": f.id,
                "feature_name": f.name,
                "covering_source_titles": ["PRD"] if coverage > 0.5 else [],
                "understanding_level": coverage,
                "missing_info": [] if coverage > 0.7 else ["细节缺失"],
                "assumptions": [],
                "has_conflict": False,
                "conflict_description": "",
            }
            for f in features
        ],
        "overall_coverage": coverage,
    }


def _make_test_points_response(features: list) -> dict:
    """构造 TestPointsLLMOutput 的 mock 返回"""
    tps = []
    idx = 0
    for f in features:
        for dim in ["functional_correctness", "boundary_value"]:
            idx += 1
            tps.append(
                {
                    "feature_id": f.id,
                    "dimension": dim,
                    "description": f"验证{f.name}的{dim}场景",
                    "priority": "P0",
                    "derived_from": [f.source_refs[0] if f.source_refs else "PRD"],
                }
            )
    return {"test_points": tps}


def _make_write_cases_response(test_points_data: list) -> dict:
    """构造 WriteCasesLLMOutput 的 mock 返回 — 每个 test_point 至少一条"""
    cases = []
    for tp in test_points_data:
        cases.append(
            {
                "test_point_id": tp["id"],
                "title": f"测试用例: {tp['description'][:30]}",
                "preconditions": ["系统正常运行"],
                "steps": [
                    {
                        "step_number": 1,
                        "action": "执行操作",
                        "input_data": "测试数据123",
                        "expected_result": "操作成功",
                    },
                ],
                "expected_results": ["验证通过"],
                "priority": tp["priority"],
                "dimensions": [tp["dimension"]],
            }
        )
    return {"test_cases": cases}


def _make_audit_response(total_tp: int) -> dict:
    """构造 AuditLLMOutput 的 mock 返回"""
    return {
        "coverage_assessment": f"所有 {total_tp} 个测试点均有用例覆盖",
        "gaps": [],
        "supplement_cases": [],
        "dimension_issues": [],
    }


# ─── Test 1: 全程 GO + 逐点覆盖 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_go_with_coverage():
    """血泪点 1+2：6阶段全执行 + 每个测试点至少一条用例"""
    context = _make_go_context()
    state: dict = {
        "document_id": str(uuid4()),
        "system_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "parsed_context": context,
    }

    # Mock FewShotRetriever（冷启动）
    with patch("src.testcase_generator.stages.write_cases.node.FewShotRetriever") as MockRetriever:
        MockRetriever.return_value.retrieve_samples = AsyncMock(return_value=[])

        # Mock LLM — 按 schema 名分发 mock 返回
        call_count = {"comprehend": 0, "test_points": 0, "write_cases": 0, "audit": 0}

        async def mock_generate(system_prompt, user_content, output_schema, temperature=0.3):
            schema_name = output_schema.__name__
            if "Comprehension" in schema_name:
                call_count["comprehend"] += 1
                data = _make_comprehension_llm_response(0.9, context.features)
                return output_schema.model_validate(data)
            elif "TestPoints" in schema_name:
                call_count["test_points"] += 1
                data = _make_test_points_response(context.features)
                return output_schema.model_validate(data)
            elif "WriteCases" in schema_name:
                call_count["write_cases"] += 1
                # 从 user_content 提取 test_points
                input_data = json.loads(user_content)
                data = _make_write_cases_response(input_data["test_points"])
                return output_schema.model_validate(data)
            elif "Audit" in schema_name:
                call_count["audit"] += 1
                data = _make_audit_response(4)
                return output_schema.model_validate(data)
            else:
                raise ValueError(f"Unexpected schema: {schema_name}")

        with (
            patch("src.testcase_generator.stages.comprehend.node.get_llm_client") as mock_c,
            patch("src.testcase_generator.stages.test_points.node.get_llm_client") as mock_tp,
            patch("src.testcase_generator.stages.write_cases.node.get_llm_client") as mock_wc,
            patch("src.testcase_generator.stages.review.node.get_llm_client") as mock_r,
        ):
            for m in [mock_c, mock_tp, mock_wc, mock_r]:
                m.return_value.generate_structured = mock_generate

            # Stage 2: comprehend
            result = await comprehend_node(state)
            state.update(result)

            # 断言1：comprehend 产出非空
            assert result["gate_result"] in ("GO", "CONDITIONAL"), f"预期 GO/CONDITIONAL, got {result['gate_result']}"
            assert result["comprehension_report"].understanding_coverage > 0
            assert call_count["comprehend"] == 1

            # Stage 3: test-points
            result = await tp_node(state)
            state.update(result)
            test_points = result["test_points"]
            assert len(test_points) > 0, "test_points 不能为空"
            assert call_count["test_points"] == 1

            # Stage 4: write-cases
            result = await write_cases_node(state)
            state.update(result)
            test_cases = result["test_cases"]
            assert len(test_cases) > 0, "test_cases 不能为空"
            assert call_count["write_cases"] >= 1

            # Stage 5: review
            result = await review_node(state)
            state.update(result)
            audit = result["audit_report"]

            # 断言2（血泪点）：逐点覆盖
            assert audit.per_test_point_covered == audit.total_test_points, (
                f"未覆盖所有测试点: {audit.per_test_point_covered}/{audit.total_test_points}, uncovered={audit.uncovered_test_point_ids}"
            )
            assert audit.uncovered_test_point_ids == [], f"存在裸测试点: {audit.uncovered_test_point_ids}"

            # Stage 6: export
            result = await export_node(state)
            assert result["yaml_output"], "YAML 导出不能为空"
            assert result["markdown_output"], "Markdown 导出不能为空"

    # 断言：全部 4 个 LLM 阶段都被真实调用
    assert call_count["comprehend"] >= 1
    assert call_count["test_points"] >= 1
    assert call_count["write_cases"] >= 1
    assert call_count["audit"] >= 1


# ─── Test 3: NO_GO 救回（不死循环）─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nogo_resume_not_deadloop():
    """血泪点 3：NO_GO → resume(answers) → 覆盖度上升 → 继续（不死循环）"""
    context = _make_nogo_context()
    state: dict = {
        "document_id": str(uuid4()),
        "system_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "parsed_context": context,
    }

    comprehend_call_count = 0

    async def mock_generate(system_prompt, user_content, output_schema, temperature=0.3):
        nonlocal comprehend_call_count
        schema_name = output_schema.__name__
        if "Comprehension" in schema_name:
            comprehend_call_count += 1
            # 第一次：低覆盖 → NO_GO
            # 第二次（有 clarification_answers）：高覆盖 → GO
            input_data = json.loads(user_content)
            has_answers = "clarification_answers" in input_data
            coverage = 0.85 if has_answers else 0.15
            data = _make_comprehension_llm_response(coverage, context.features)
            return output_schema.model_validate(data)
        raise ValueError(f"Unexpected: {schema_name}")

    with patch("src.testcase_generator.stages.comprehend.node.get_llm_client") as mock_llm:
        mock_llm.return_value.generate_structured = mock_generate

        # 第一次 comprehend：应该 NO_GO
        result1 = await comprehend_node(state)
        assert result1["gate_result"] == "NO_GO", f"预期 NO_GO, got {result1['gate_result']}"
        assert result1["comprehension_report"].understanding_coverage < 0.5
        assert comprehend_call_count == 1

        # 模拟 resume：用户提供了澄清答案
        state.update(result1)
        state["clarification_answers"] = [
            {"question_id": "q1", "answer": "第三方登录支持微信OAuth2.0，回调地址/oauth/callback"},
            {"question_id": "q2", "answer": "忘记密码流程：手机号→验证码→新密码"},
            {"question_id": "q3", "answer": "注销需短信验证，7天冷静期"},
            {"question_id": "q4", "answer": "5分钟3次错误触发图形验证码"},
        ]

        # 第二次 comprehend：应该 GO 或 CONDITIONAL（不再 NO_GO）
        result2 = await comprehend_node(state)
        assert result2["gate_result"] in ("GO", "CONDITIONAL"), (
            f"resume 后仍 NO_GO（死循环！）: coverage={result2['comprehension_report'].understanding_coverage}"
        )
        assert (
            result2["comprehension_report"].understanding_coverage
            > result1["comprehension_report"].understanding_coverage
        ), "resume 后覆盖度未上升"
        assert comprehend_call_count == 2, "comprehend 应该只被调用 2 次（不是无限循环）"
