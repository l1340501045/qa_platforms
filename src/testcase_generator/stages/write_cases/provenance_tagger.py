"""T027: provenance 标注 — 为每条用例标注溯源信息"""

from __future__ import annotations

from src.testcase_generator.schemas.parsed_context import ParsedContext, FeatureItem
from src.testcase_generator.schemas.test_case import Provenance
from src.testcase_generator.schemas.test_point import TestPointSchema


class ProvenanceTagger:
    """为每条用例标注溯源信息 — 审计的命根（硬约束#3）

    必须包含：
    - derived_from: 来源文档引用列表
    - source_section: 具体章节标识
    - verbatim_excerpt: 原文摘录
    - trust_level: 最低信源等级（多源取最低）
    """

    def tag_provenance(
        self,
        test_point: TestPointSchema,
        parsed_context: ParsedContext,
    ) -> Provenance:
        """标注每条用例的信息来源

        根据 test_point.derived_from 和 feature_id 在 parsed_context 中
        定位原始章节，提取溯源信息。
        """
        feature = self._find_feature(test_point.feature_id, parsed_context)
        source_refs = test_point.derived_from or (feature.source_refs if feature else [])

        # 提取 verbatim_excerpt：从匹配的 sections 中取第一段内容
        excerpt = ""
        source_section = ""
        trust_levels: list[int] = []

        for source in parsed_context.sources:
            for section in source.sections:
                if section.source_ref in source_refs or self._section_matches(section, test_point, feature):
                    if not excerpt:
                        excerpt = section.content[:200]
                        source_section = section.source_ref
                    trust_levels.append(source.trust_level)

        # 兜底：如果找不到精确匹配，使用 feature 级别信息
        if not excerpt and feature:
            excerpt = feature.description[:200]
            source_section = feature.source_refs[0] if feature.source_refs else "unknown"

        if not trust_levels:
            # 取所有信源中最高信任等级（数字最小）
            trust_levels = [s.trust_level for s in parsed_context.sources] or [5]

        # 硬约束#5: 不同级取高（数字小的优先级高）
        final_trust_level = min(trust_levels)

        return Provenance(
            derived_from=source_refs or ["unresolved"],
            source_section=source_section or "unresolved",
            verbatim_excerpt=excerpt or "[无法定位原文]",
            trust_level=final_trust_level,
        )

    def _find_feature(self, feature_id: str, parsed_context: ParsedContext) -> FeatureItem | None:
        """在 parsed_context.features 中查找匹配 feature"""
        for f in parsed_context.features:
            if f.id == feature_id:
                return f
            for sub in f.sub_features:
                if sub.id == feature_id:
                    return sub
        return None

    def _section_matches(self, section, test_point: TestPointSchema, feature: FeatureItem | None) -> bool:
        """检查 section 是否与当前测试点相关"""
        if feature and feature.name.lower() in section.heading.lower():
            return True
        if test_point.dimension in section.content.lower():
            return True
        return False
