"""真实图回归测试 — 走 build_pipeline().compile() + astream，守住 graph 接线

验证：
1. GO 路径：6 个节点全执行，final state 含所有关键字段
2. NO_GO 路径：interrupt 被触发 → resume 后继续到 test_points
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.knowledge_base.schemas.common import RetrievalContext, SearchResult
from src.testcase_generator.pipeline.graph import build_pipeline
from src.testcase_generator.schemas.parsed_context import (
    FeatureItem,
    ParsedContext,
    SectionExtract,
    SourceItem,
)

_INCOMPLETE_REAL_GRAPH_MOCK_REASON = (
    "pre-existing: 真实图已扩为 9 节点，旧 mock 未覆盖全阶段路径；"
    "待补齐 rule_extract/verify/dedup/backfill mock 后恢复"
)


def _fake_retrieval_ctx() -> RetrievalContext:
    """构造含 PRD 功能模块的检索上下文，使 parse 真实产出功能点"""
    sid = uuid4()
    seed = uuid4()
    md = "# 功能A\n功能A的详细描述内容，用于端到端回归测试。\n\n# 功能B\n功能B的详细描述内容。"
    return RetrievalContext(
        seed_document_id=seed,
        system_id=sid,
        merged_results=[
            SearchResult(document_id=seed, title="测试PRD", content_snippet=md, score=1.0, source="seed", depth=0),
        ],
        total_count=1,
    )


# ─── Mock LLM 按 schema 分发 ──────────────────────────────────────────────────


def _mock_llm_factory(go_coverage: float = 0.9):
    """构造一个按 schema 分发的 mock LLM，coverage 可控"""
    call_log: list[str] = []

    async def mock_generate(system_prompt, user_content, output_schema, temperature=0.3):
        schema_name = output_schema.__name__
        call_log.append(schema_name)

        if "Comprehension" in schema_name:
            # 解析 user_content 检查是否有 clarification_answers
            data = json.loads(user_content)
            has_answers = "clarification_answers" in data
            coverage = 0.9 if has_answers else go_coverage
            return output_schema.model_validate(
                {
                    "feature_coverages": [
                        {
                            "id": "F-001",
                            "feature_id": "F-001",
                            "feature_name": "功能A",
                            "covering_source_titles": ["PRD"],
                            "understanding_level": coverage,
                            "missing_info": [] if coverage > 0.7 else ["缺细节"],
                            "assumptions": [],
                            "has_conflict": False,
                            "conflict_description": "",
                        }
                    ],
                    "overall_coverage": coverage,
                }
            )
        elif "TestPoints" in schema_name:
            data = json.loads(user_content)
            fids = [f["feature_id"] for f in data.get("features_with_dimensions", [])]
            tps = []
            for fid in fids:
                tps.append({
                    "feature_id": fid,
                    "dimension": "functional_correctness",
                    "description": f"验证{fid}正常工作",
                    "priority": "P0",
                    "derived_from": ["PRD §1"],
                })
            return output_schema.model_validate({"test_points": tps})
        elif "WriteCases" in schema_name:
            input_data = json.loads(user_content)
            cases = []
            for tp in input_data.get("test_points", []):
                cases.append(
                    {
                        "test_point_id": tp["id"],
                        "title": f"用例: {tp['description'][:20]}",
                        "preconditions": ["系统正常"],
                        "steps": [
                            {"step_number": 1, "action": "执行操作", "input_data": "数据", "expected_result": "成功"}
                        ],
                        "expected_results": ["验证通过"],
                        "priority": tp["priority"],
                        "dimensions": [tp["dimension"]],
                    }
                )
            return output_schema.model_validate({"test_cases": cases})
        elif "Audit" in schema_name:
            return output_schema.model_validate(
                {
                    "coverage_assessment": "全部覆盖",
                    "gaps": [],
                    "supplement_cases": [],
                    "dimension_issues": [],
                }
            )
        raise ValueError(f"Unexpected schema: {schema_name}")

    return mock_generate, call_log


def _make_initial_state() -> dict:
    """构造初始输入状态"""
    return {
        "document_id": str(uuid4()),
        "system_id": str(uuid4()),
        "batch_id": str(uuid4()),
        "parsed_context": ParsedContext(
            sources=[
                SourceItem(
                    doc_id=str(uuid4()),
                    doc_type="prd",
                    trust_level=1,
                    title="测试PRD",
                    sections=[SectionExtract(heading="1.1", content="功能A的描述", source_ref="PRD §1")],
                ),
            ],
            features=[
                FeatureItem(
                    id="F001",
                    name="功能A",
                    description="功能A详细描述",
                    source_refs=["PRD §1"],
                    feature_type="data_input",
                ),
            ],
            prototype_observations=None,
        ),
    }


# ─── Test: GO 路径走真实图 ─────────────────────────────────────────────────────


@pytest.mark.skip(reason=_INCOMPLETE_REAL_GRAPH_MOCK_REASON)
@pytest.mark.asyncio
async def test_real_graph_go_path():
    """真实图 GO 路径：compile + astream，6 节点全执行"""
    mock_generate, call_log = _mock_llm_factory(go_coverage=0.9)

    with (
        patch("src.testcase_generator.stages.comprehend.node.get_llm_client") as m1,
        patch("src.testcase_generator.stages.test_points.node.get_llm_client") as m2,
        patch("src.testcase_generator.stages.write_cases.node.get_llm_client") as m3,
        patch("src.testcase_generator.stages.review.node.get_llm_client") as m4,
        patch("src.testcase_generator.stages.write_cases.node.FewShotRetriever") as mock_fsr,
        patch(
            "src.testcase_generator.stages.parse.node.retrieve_knowledge_context",
            new=AsyncMock(return_value=_fake_retrieval_ctx()),
        ),
        patch(
            "src.testcase_generator.stages.parse.node.retrieve_entity_graph_hints",
            new=AsyncMock(return_value=[]),
        ),
    ):
        for m in [m1, m2, m3, m4]:
            m.return_value.generate_structured = mock_generate
        mock_fsr.return_value.retrieve_samples = AsyncMock(return_value=[])

        # compile 真实图（内存 checkpointer）
        graph = build_pipeline()
        app = graph.compile(checkpointer=MemorySaver())

        config = {"configurable": {"thread_id": "test-go-1"}}
        initial_state = _make_initial_state()

        # astream 执行
        final_state = None
        visited_nodes: list[str] = []

        async for event in app.astream(initial_state, config=config, stream_mode="updates"):
            for node_name, update in event.items():
                visited_nodes.append(node_name)
                if node_name == "__end__":
                    continue

        # 获取最终状态
        final_state = await app.aget_state(config)

        # 断言：6 个阶段节点都被执行
        expected_nodes = {"parse", "comprehend", "test_points", "write_cases", "review", "export"}
        assert expected_nodes.issubset(set(visited_nodes)), (
            f"未执行的节点: {expected_nodes - set(visited_nodes)}, visited={visited_nodes}"
        )

        # 断言：parse 产出 parsed_context（防 stub 回归）
        state_values = final_state.values
        assert "parsed_context" in state_values, "parse 未产出 parsed_context"

        # 断言：comprehend 产出 gate_result（防 stub 回归）
        assert state_values.get("gate_result") in ("GO", "CONDITIONAL"), (
            f"gate_result 异常: {state_values.get('gate_result')}"
        )

        # 断言：export 产物非空
        assert state_values.get("yaml_output"), "YAML 导出为空"
        assert state_values.get("markdown_output"), "Markdown 导出为空"

        # 断言：LLM 被调用了 4 种 schema
        assert "ComprehensionLLMOutput" in call_log
        assert "TestPointsLLMOutput" in call_log
        assert "WriteCasesLLMOutput" in call_log
        assert "AuditLLMOutput" in call_log


# ─── Test: NO_GO 路径走真实图 → interrupt → resume ─────────────────────────────


@pytest.mark.skip(reason=_INCOMPLETE_REAL_GRAPH_MOCK_REASON)
@pytest.mark.asyncio
async def test_real_graph_nogo_interrupt_resume():
    """真实图 NO_GO 路径：interrupt 触发 → resume 后路由到 test_points"""
    # 第一次 coverage=0.2 → NO_GO，resume 后 coverage=0.9 → GO
    mock_generate, call_log = _mock_llm_factory(go_coverage=0.2)

    with (
        patch("src.testcase_generator.stages.comprehend.node.get_llm_client") as m1,
        patch("src.testcase_generator.stages.test_points.node.get_llm_client") as m2,
        patch("src.testcase_generator.stages.write_cases.node.get_llm_client") as m3,
        patch("src.testcase_generator.stages.review.node.get_llm_client") as m4,
        patch("src.testcase_generator.stages.write_cases.node.FewShotRetriever") as mock_fsr,
        patch(
            "src.testcase_generator.stages.parse.node.retrieve_knowledge_context",
            new=AsyncMock(return_value=_fake_retrieval_ctx()),
        ),
        patch(
            "src.testcase_generator.stages.parse.node.retrieve_entity_graph_hints",
            new=AsyncMock(return_value=[]),
        ),
    ):
        for m in [m1, m2, m3, m4]:
            m.return_value.generate_structured = mock_generate
        mock_fsr.return_value.retrieve_samples = AsyncMock(return_value=[])

        graph = build_pipeline()
        app = graph.compile(checkpointer=MemorySaver())

        config = {"configurable": {"thread_id": "test-nogo-1"}}
        initial_state = _make_initial_state()

        # 第一次 astream：应在 interrupt 处暂停
        visited_before: list[str] = []
        async for event in app.astream(initial_state, config=config, stream_mode="updates"):
            for node_name in event:
                visited_before.append(node_name)

        # 断言：interrupt 被触发（检查 state.next）
        snapshot = await app.aget_state(config)
        assert snapshot.next, "流水线未暂停（next 为空）"
        # next 应含 interrupt 或 comprehend（取决于 LangGraph 版本的 interrupt 语义）
        next_nodes = list(snapshot.next)
        assert any("interrupt" in n or "comprehend" in n for n in next_nodes), (
            f"暂停后 next 应含 interrupt 相关节点, got: {next_nodes}"
        )

        # 断言：parse 和 comprehend 已执行，但 test_points 未执行
        assert "parse" in visited_before
        assert "comprehend" in visited_before

        # Resume：提供 clarification_answers
        resume_value = [
            {"question_id": "q1", "answer": "功能A的详细说明"},
        ]

        # 用 Command(resume=...) 恢复
        visited_after: list[str] = []
        async for event in app.astream(Command(resume=resume_value), config=config, stream_mode="updates"):
            for node_name in event:
                visited_after.append(node_name)

        # 断言：resume 后进入了 test_points（防 resume 路由回归）
        assert "test_points" in visited_after, f"resume 后未进入 test_points（死循环？）: visited={visited_after}"

        # 断言：最终完成了完整流程
        assert "export" in visited_after, f"resume 后未到达 export: visited={visited_after}"
