"""关键业务流结构化测试点。

需求章节能定位到关键主链路时，确定性追加 1 个结构化锚点，保证风险测试不是只靠
LLM 在普通维度里“想到它”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from src.testcase_generator.schemas.parsed_context import FeatureItem
from src.testcase_generator.schemas.test_point import TestPointSchema
from src.testcase_generator.services.critical_flows import (
    CriticalFlowSpec,
    matching_critical_flow_specs,
    source_ref_matches_token,
)

_CRITICAL_FLOW_DIMENSION = "functional_correctness"
_CRITICAL_FLOW_STRUCTURAL_TYPE = "critical_flow"


@dataclass
class _FlowMatch:
    spec: CriticalFlowSpec
    feature_id: str
    source_refs: list[str] = field(default_factory=list)


def _matched_refs(refs: Iterable[str], spec: CriticalFlowSpec) -> list[str]:
    return [ref for ref in refs if any(source_ref_matches_token(ref, token) for token in spec.source_tokens)]


def _append_unique(target: list[str], values: Iterable[str]) -> None:
    seen = set(target)
    for value in values:
        if value and value not in seen:
            target.append(value)
            seen.add(value)


def build_critical_flow_test_points(features: list[FeatureItem], start_idx: int) -> list[TestPointSchema]:
    """按 feature.source_refs 确定性生成关键业务流锚点。

    每条关键流最多生成 1 个锚点；若多个章节共同描述同一流，锚点挂到首次命中的 feature，
    ``derived_from`` 保留所有命中的 source_ref，避免拆散主链路证据。
    """
    ordered_keys: list[str] = []
    matches: dict[str, _FlowMatch] = {}

    for feature in features:
        refs = [str(ref) for ref in feature.source_refs if ref]
        if not refs:
            continue
        for spec in matching_critical_flow_specs(refs):
            if spec.key not in matches:
                matches[spec.key] = _FlowMatch(spec=spec, feature_id=feature.id)
                ordered_keys.append(spec.key)
            _append_unique(matches[spec.key].source_refs, _matched_refs(refs, spec))

    points: list[TestPointSchema] = []
    for key in ordered_keys:
        match = matches[key]
        idx = start_idx + len(points) + 1
        points.append(
            TestPointSchema(
                id=f"TP-{idx:03d}",
                feature_id=match.feature_id,
                dimension=_CRITICAL_FLOW_DIMENSION,
                description=f"关键业务流：{match.spec.title}。{match.spec.description}",
                priority="P0",
                derived_from=match.source_refs,
                applicable_dimensions=[_CRITICAL_FLOW_DIMENSION],
                structural_type=_CRITICAL_FLOW_STRUCTURAL_TYPE,
                structural_key=match.spec.key,
                likelihood=3,
                impact=3,
            )
        )
    return points
