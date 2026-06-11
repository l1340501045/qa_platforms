"""T032: YAML 全字段导出 — 含 provenance/dimensions/trust_level"""

from __future__ import annotations

import yaml

from src.testcase_generator.schemas.test_case import GeneratedTestCase


class YamlExporter:
    """YAML 全字段导出器（硬约束#7 双轨之一）

    输出包含完整结构化信息，供机器消费和版本管理。
    """

    def export(self, test_cases: list[GeneratedTestCase]) -> str:
        """将用例列表导出为 YAML 格式字符串

        包含全部字段：provenance, dimensions, trust_level, confidence_note 等。
        """
        cases_data: list[dict] = []

        for tc in test_cases:
            case_dict = {
                "id": tc.id,
                "test_point_id": tc.test_point_id,
                "title": tc.title,
                "priority": tc.priority,
                "preconditions": tc.preconditions,
                "steps": [
                    {
                        "step_number": s.step_number,
                        "action": s.action,
                        "input_data": s.input_data,
                        "expected_result": s.expected_result,
                        "source_quote": s.source_quote,
                        "source_ref": s.source_ref,
                    }
                    for s in tc.steps
                ],
                "expected_results": tc.expected_results,
                "dimensions": tc.dimensions,
                "provenance": {
                    "derived_from": tc.provenance.derived_from,
                    "source_section": tc.provenance.source_section,
                    "verbatim_excerpt": tc.provenance.verbatim_excerpt,
                    "trust_level": tc.provenance.trust_level,
                },
                "trust_level": tc.trust_level,
                "confidence_note": tc.confidence_note,
            }
            if tc.verification is not None:
                case_dict["verification"] = {
                    "verdict": tc.verification.verdict,
                    "bucket": tc.verification.bucket,
                    "rationale": tc.verification.rationale,
                    "prd_evidence": tc.verification.prd_evidence,
                    "unsupported_assertions": tc.verification.unsupported_assertions,
                }
            cases_data.append(case_dict)

        output = {
            "version": "1.0",
            "total_cases": len(cases_data),
            "test_cases": cases_data,
        }

        return yaml.dump(output, allow_unicode=True, default_flow_style=False, sort_keys=False)
