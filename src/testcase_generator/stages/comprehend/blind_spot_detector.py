"""T020: 盲区检测 + 信源冲突识别"""

from __future__ import annotations

import yaml
from pathlib import Path
from uuid import uuid4

from src.testcase_generator.schemas.parsed_context import FeatureItem, SourceItem
from src.testcase_generator.schemas.comprehension_report import BlindSpot, SourceConflict

# 加载冲突仲裁配置
_config_path = Path(__file__).parent.parent.parent / "config" / "trust_order.yaml"
with open(_config_path) as _f:
    _trust_config = yaml.safe_load(_f)
    _conflict_resolution = _trust_config["conflict_resolution"]


class BlindSpotDetector:
    """检测理解盲区和信源冲突

    盲区：功能点存在但无对应信源覆盖
    冲突：同一功能点被多个信源描述，且描述矛盾（需信任仲裁）
    """

    def detect_blind_spots(
        self,
        features: list[FeatureItem],
        sources: list[SourceItem],
    ) -> list[BlindSpot]:
        """检测功能点中无信源覆盖的盲区

        Args:
            features: 提取的功能点列表
            sources: 排序后的信源列表

        Returns:
            盲区列表
        """
        blind_spots: list[BlindSpot] = []

        # 构建所有信源覆盖的功能集合（通过 source_ref 匹配）
        covered_features: set[str] = set()
        for source in sources:
            for section in source.sections:
                # 对每个功能点检查是否有信源的 section 匹配
                for feature in features:
                    if _feature_covered_by_section(feature, section.source_ref, source):
                        covered_features.add(feature.id)

        # 找出未被覆盖的功能点
        for feature in features:
            if feature.id not in covered_features:
                severity = "high" if not feature.source_refs else "medium"
                blind_spots.append(
                    BlindSpot(
                        area=feature.name,
                        reason=f"功能点 '{feature.name}' 无对应信源覆盖",
                        suggested_action="需补充说明或提供相关文档",
                        severity=severity,
                    )
                )

        return blind_spots

    def detect_conflicts(
        self,
        features: list[FeatureItem],
        sources: list[SourceItem],
    ) -> list[SourceConflict]:
        """检测同一功能点在不同信源间的描述冲突

        信任仲裁规则（硬约束#3）：
        - 不同级信源冲突 → 高级胜出（higher_wins）
        - 同级信源冲突 → 标记为 unresolved，触发 open_question

        Args:
            features: 功能点列表
            sources: 信源列表

        Returns:
            冲突列表（含仲裁结果）
        """
        conflicts: list[SourceConflict] = []
        conflict_counter = 0

        for feature in features:
            # 找出覆盖该功能点的所有信源
            covering_sources = _find_covering_sources(feature, sources)

            if len(covering_sources) < 2:
                continue

            # 两两对比，检查是否存在冲突
            for i in range(len(covering_sources)):
                for j in range(i + 1, len(covering_sources)):
                    src_a = covering_sources[i]
                    src_b = covering_sources[j]

                    # 判断是否存在内容冲突（简化：不同信源对同一功能有不同描述即视为潜在冲突）
                    if _sources_may_conflict(feature, src_a, src_b):
                        conflict_counter += 1
                        resolution, basis = _arbitrate(src_a, src_b)
                        conflicts.append(
                            SourceConflict(
                                conflict_id=f"C-{conflict_counter:03d}",
                                description=f"功能 '{feature.name}' 在不同信源中描述不一致",
                                source_a=src_a.title,
                                source_a_trust_level=src_a.trust_level,
                                source_b=src_b.title,
                                source_b_trust_level=src_b.trust_level,
                                resolution=resolution,
                                resolution_basis=basis,
                            )
                        )

        return conflicts


def _feature_covered_by_section(
    feature: FeatureItem,
    source_ref: str,
    source: SourceItem,
) -> bool:
    """判断某信源是否覆盖了该功能点"""
    # 如果功能点的 source_refs 中直接引用了该信源
    if source_ref in feature.source_refs:
        return True
    # 或者功能点名称出现在信源的某个 section 中
    for section in source.sections:
        if feature.name.lower() in section.content.lower():
            return True
    return False


def _find_covering_sources(
    feature: FeatureItem,
    sources: list[SourceItem],
) -> list[SourceItem]:
    """找出覆盖某功能点的所有信源"""
    covering: list[SourceItem] = []
    for source in sources:
        for section in source.sections:
            if _feature_covered_by_section(feature, section.source_ref, source):
                covering.append(source)
                break
    return covering


def _sources_may_conflict(
    feature: FeatureItem,
    src_a: SourceItem,
    src_b: SourceItem,
) -> bool:
    """简化冲突判定：不同信源对同一功能点的描述有差异

    实际生产中应使用 LLM 判断语义冲突，此处用启发式规则。
    """
    # 获取各信源中关于该功能的内容
    content_a = _get_feature_content(feature, src_a)
    content_b = _get_feature_content(feature, src_b)

    if not content_a or not content_b:
        return False

    # 简化：如果两段内容长度差距超过 3 倍，可能存在信息不对称（非直接冲突）
    # 真正的冲突判定应由 LLM 完成，此处仅标记潜在冲突
    # 当前实现保守：只有明确不同信源且内容均非空时才标记
    return content_a != content_b


def _get_feature_content(feature: FeatureItem, source: SourceItem) -> str:
    """从信源中提取关于某功能点的内容"""
    for section in source.sections:
        if feature.name.lower() in section.content.lower():
            return section.content
    return ""


def _arbitrate(src_a: SourceItem, src_b: SourceItem) -> tuple[str, str]:
    """信任仲裁

    Returns:
        (resolution, resolution_basis) 元组
    """
    if src_a.trust_level != src_b.trust_level:
        # 不同级 → 高级胜出（trust_level 数值越小优先级越高）
        winner = src_a.title if src_a.trust_level < src_b.trust_level else src_b.title
        return (
            f"采信 '{winner}' 的描述",
            "higher_wins",
        )
    else:
        # 同级冲突 → 标记为 unresolved，触发 Gate NO_GO
        return ("unresolved", "same_level_conflict_requires_human_decision")
