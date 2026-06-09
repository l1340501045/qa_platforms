"""T031: 缺失维度自动补全 — 审计后自动填充覆盖缺口"""

from __future__ import annotations

from src.testcase_generator.schemas.audit_report import CoverageGap
from src.testcase_generator.schemas.test_case import (
    GeneratedTestCase,
    TestStep,
    Provenance,
)


class GapFiller:
    """缺失维度自动补全 — 对 AuditReport.gaps 自动生成补充用例"""

    def fill_gaps(self, gaps: list[CoverageGap], existing_cases: list[GeneratedTestCase]) -> list[GeneratedTestCase]:
        """为每个覆盖缺口生成一条补充用例

        返回新增的用例列表（不修改已有用例）。
        """
        additions: list[GeneratedTestCase] = []
        base_idx = len(existing_cases)

        for i, gap in enumerate(gaps, start=1):
            case_id = f"TC-{base_idx + i:03d}"
            case = GeneratedTestCase(
                id=case_id,
                test_point_id=f"TP-GAP-{i:03d}",
                title=f"[审计补全] {gap.description}",
                preconditions=["系统处于正常运行状态", "已进入相关功能模块"],
                steps=[
                    TestStep(
                        step_number=1,
                        action=f"针对 {gap.dimension} 维度执行验证操作",
                        input_data="按缺口描述准备测试数据",
                        expected_result=f"系统在 {gap.dimension} 维度表现符合预期",
                    ),
                    TestStep(
                        step_number=2,
                        action="验证结果并确认无副作用",
                        input_data="N/A",
                        expected_result="数据一致，功能正常",
                    ),
                ],
                expected_results=[
                    f"{gap.dimension} 维度覆盖验证通过",
                    "填补审计发现的覆盖缺口",
                ],
                priority="P1" if gap.severity == "high" else "P2",
                dimensions=[gap.dimension],
                provenance=Provenance(
                    derived_from=["audit_gap_fill"],
                    source_section="review_stage",
                    verbatim_excerpt=gap.suggested_test_point or gap.description,
                    trust_level=3,
                ),
                trust_level=3,
                confidence_note="审计补全用例，建议人工确认覆盖充分性",
            )
            additions.append(case)

        return additions
