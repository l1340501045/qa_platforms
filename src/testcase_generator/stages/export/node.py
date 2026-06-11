"""T034: export 节点 — 双轨并行导出（硬约束#7）"""

from __future__ import annotations

import asyncio

from src.testcase_generator.schemas.pipeline_state import PipelineState
from src.testcase_generator.stages.export.yaml_exporter import YamlExporter
from src.testcase_generator.stages.export.markdown_exporter import MarkdownExporter


async def export_node(state: PipelineState) -> dict:
    """Stage 6: YAML 全字段 + Markdown 人评审，两轨并行（硬约束#7）

    并行执行两种格式导出，减少整体耗时。
    """
    final_test_cases = state["final_test_cases"]
    audit_report = state.get("audit_report")

    # 双轨并行导出
    yaml_task = asyncio.to_thread(_export_yaml, final_test_cases)
    md_task = asyncio.to_thread(_export_markdown, final_test_cases, audit_report)

    yaml_output, markdown_output = await asyncio.gather(yaml_task, md_task)

    # 三轨分桶计数（main / needs_spec / to_fix），便于回调与前端区分
    bucket_counts = {"main": 0, "needs_spec": 0, "to_fix": 0}
    for tc in final_test_cases:
        b = tc.verification.bucket if tc.verification else "main"
        bucket_counts[b] = bucket_counts.get(b, 0) + 1

    return {
        "yaml_output": yaml_output,
        "markdown_output": markdown_output,
        "bucket_counts": bucket_counts,
        "current_stage": "export",
    }


def _export_yaml(test_cases) -> str:
    """同步 YAML 导出（在线程中运行）"""
    exporter = YamlExporter()
    return exporter.export(test_cases)


def _export_markdown(test_cases, audit_report) -> str:
    """同步 Markdown 导出（在线程中运行）"""
    exporter = MarkdownExporter()
    return exporter.export(test_cases, audit_report)
