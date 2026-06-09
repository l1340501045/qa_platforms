"""T024: 维度适用性裁剪 — 根据 feature_types 过滤不适用维度"""

from __future__ import annotations


class ApplicabilityFilter:
    """维度适用性裁剪 — 根据 feature_types 过滤不适用维度

    规则优先级：not_applicable_to > applicable_to
    """

    def filter_dimensions(self, feature_types: list[str], all_dimensions: list[dict]) -> list[dict]:
        """返回适用该功能点的维度子集

        规则：
        - applicable_to = ["*"] → 全部适用
        - 否则 feature_types 与 applicable_to 有交集 → 适用
        - feature_types 与 not_applicable_to 有交集 → 不适用（优先级高于 applicable_to）
        """
        result: list[dict] = []
        ft_set = set(feature_types)

        for dim in all_dimensions:
            not_applicable = set(dim.get("not_applicable_to", []))
            applicable = dim.get("applicable_to", [])

            # 排除规则优先：feature_types 与 not_applicable_to 有交集则跳过
            if ft_set and ft_set & not_applicable:
                continue

            # 适用规则：通配符 / feature_types 为空（视为通用）/ 有交集
            if applicable == ["*"] or not ft_set or ft_set & set(applicable):
                result.append(dim)

        return result
