"""T033: Markdown 人可读视图导出"""

from __future__ import annotations

from src.testcase_generator.schemas.test_case import GeneratedTestCase
from src.testcase_generator.schemas.audit_report import AuditReport


class MarkdownExporter:
    """Markdown 人评审导出器（硬约束#7 双轨之一）

    输出面向人类可读的评审文档，含摘要统计和用例详情。
    """

    def export(
        self,
        test_cases: list[GeneratedTestCase],
        audit_report: AuditReport | None = None,
    ) -> str:
        """将用例列表导出为 Markdown 人可读格式"""
        lines: list[str] = []

        # 摘要头
        lines.append("# 测试用例评审文档\n")
        lines.append(f"**总用例数**: {len(test_cases)}\n")

        if audit_report:
            lines.append(f"**维度覆盖率**: {audit_report.dimension_coverage:.1%}\n")
            lines.append(f"**审计补全数**: {len(audit_report.additions)}\n")
            if audit_report.gaps:
                lines.append(f"**覆盖缺口**: {len(audit_report.gaps)} 个\n")

        # 事实核验分桶汇总（verify 关卡）
        bucket_dist = {"main": 0, "needs_spec": 0, "to_fix": 0}
        for tc in test_cases:
            b = tc.verification.bucket if tc.verification else "main"
            bucket_dist[b] = bucket_dist.get(b, 0) + 1
        if bucket_dist["needs_spec"] or bucket_dist["to_fix"]:
            lines.append("\n## 事实核验分桶（verify 关卡）\n")
            lines.append(f"- 主用例集（grounded）: {bucket_dist['main']} 条\n")
            lines.append(f"- 待补规格·超纲（mock/二期/PRD未定义）: {bucket_dist['needs_spec']} 条\n")
            lines.append(f"- 需修正（与 PRD 冲突）: {bucket_dist['to_fix']} 条\n")

        lines.append("\n---\n")

        # 优先级分布统计
        priority_dist = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for tc in test_cases:
            priority_dist[tc.priority] = priority_dist.get(tc.priority, 0) + 1

        lines.append("## 优先级分布\n")
        for p, count in priority_dist.items():
            lines.append(f"- {p}: {count} 条\n")
        lines.append("\n---\n")

        # 用例详情
        lines.append("## 用例详情\n")

        for tc in test_cases:
            lines.append(f"### {tc.id}: {tc.title}\n")
            lines.append(f"- **优先级**: {tc.priority}\n")
            lines.append(f"- **维度**: {', '.join(tc.dimensions)}\n")
            lines.append(f"- **信任等级**: {tc.trust_level}\n")
            if tc.verification and tc.verification.verdict not in (None, "grounded", "unverified"):
                lines.append(
                    f"- **核验**: {tc.verification.verdict} → {tc.verification.bucket}"
                    f"（{tc.verification.rationale}）\n"
                )
            if tc.confidence_note:
                lines.append(f"- **备注**: {tc.confidence_note}\n")
            lines.append(f"- **来源**: {', '.join(tc.provenance.derived_from)}\n")

            # 前置条件
            if tc.preconditions:
                lines.append("\n**前置条件**:\n")
                for pre in tc.preconditions:
                    lines.append(f"  - {pre}\n")

            # 测试步骤表格
            lines.append("\n**测试步骤**:\n")
            lines.append("| 步骤 | 操作 | 输入数据 | 预期结果 |\n")
            lines.append("| --- | --- | --- | --- |\n")
            for step in tc.steps:
                lines.append(f"| {step.step_number} | {step.action} | {step.input_data} | {step.expected_result} |\n")

            # 预期结果
            if tc.expected_results:
                lines.append("\n**预期结果汇总**:\n")
                for er in tc.expected_results:
                    lines.append(f"  - {er}\n")

            lines.append("\n---\n")

        return "".join(lines)
