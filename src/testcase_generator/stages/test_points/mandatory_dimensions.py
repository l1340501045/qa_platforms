"""T025: 漏测 Bug 强制维度注入 — 从知识库漏测记录中提取必须覆盖的维度"""

from __future__ import annotations

from src.platform_api.models.enums import DocType
from src.testcase_generator.schemas.parsed_context import ParsedContext
from src.testcase_generator.schemas.test_point import TestPointSchema


class MandatoryDimensionInjector:
    """漏测 Bug 强制维度注入 — 从知识库漏测记录中提取必须覆盖的维度

    当 parsed_context 中存在 bug_record 类型信源时，
    从 Bug 描述中推断涉及维度，确保相关功能点一定覆盖。
    """

    # Bug 描述关键词到维度的映射（可配置化扩展）
    KEYWORD_DIMENSION_MAP: dict[str, str] = {
        "边界": "boundary_value",
        "并发": "concurrent_conflict",
        "超时": "timeout",
        "权限": "permission_denied",
        "幂等": "idempotency",
        "状态": "state_transition",
        "缓存": "cache_consistency",
        "注入": "input_injection",
        "溢出": "data_range",
        "精度": "data_calculation",
        "同步": "data_sync",
        "回退": "reversibility",
        "网络": "network_error",
    }

    def inject_mandatory(
        self, test_points: list[TestPointSchema], parsed_context: ParsedContext
    ) -> list[TestPointSchema]:
        """如果 parsed_context 中有 bug_record 类型的信源，
        提取其涉及的维度，确保相关功能点一定覆盖这些维度。
        如果已有 → 跳过；如果缺失 → 强制追加 TestPoint。
        """
        bug_sources = [s for s in parsed_context.sources if s.doc_type == DocType.BUG_RECORD]
        if not bug_sources:
            return test_points

        # 收集 Bug 涉及的强制维度
        mandatory_dims = self._extract_bug_dimensions(bug_sources)
        if not mandatory_dims:
            return test_points

        # 构建已覆盖索引：(feature_id, dimension)
        covered = {(tp.feature_id, tp.dimension) for tp in test_points}

        # 对所有功能点检查缺失的强制维度
        additions: list[TestPointSchema] = []
        existing_count = len(test_points)

        for feature in parsed_context.features:
            for dim_name in mandatory_dims:
                if (feature.id, dim_name) not in covered:
                    existing_count += 1
                    tp = TestPointSchema(
                        id=f"TP-{existing_count:03d}",
                        feature_id=feature.id,
                        dimension=dim_name,
                        description=f"[漏测强制] {feature.name} - {dim_name} 维度覆盖（来源：历史 Bug）",
                        priority="P1",
                        derived_from=[f"BUG:{s.title}" for s in bug_sources],
                        applicable_dimensions=[dim_name],
                    )
                    additions.append(tp)
                    covered.add((feature.id, dim_name))

        return test_points + additions

    def _extract_bug_dimensions(self, bug_sources: list) -> set[str]:
        """从 Bug 信源的 sections 中推断涉及维度"""
        dims: set[str] = set()
        for source in bug_sources:
            for section in source.sections:
                text = f"{section.heading} {section.content}"
                for keyword, dimension in self.KEYWORD_DIMENSION_MAP.items():
                    if keyword in text:
                        dims.add(dimension)
        return dims
