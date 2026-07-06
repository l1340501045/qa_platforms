"""关键业务流结构化锚点测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.testcase_generator.schemas.parsed_context import FeatureItem, ParsedContext, SectionExtract, SourceItem
from src.testcase_generator.stages.test_points import node as tp_node
from src.testcase_generator.stages.test_points.critical_flow import (
    build_critical_flow_test_points,
)


def _feature(feature_id: str, refs: list[str]) -> FeatureItem:
    return FeatureItem(
        id=feature_id,
        name=f"功能 {feature_id}",
        description="覆盖核心业务链路",
        source_refs=refs,
    )


def test_build_critical_flow_test_points_from_source_refs():
    points = build_critical_flow_test_points(
        [
            _feature("F-submit", ["PRD §5.8.13 批量提交"]),
            _feature("F-state", ["PRD §5.8.13.1 提交结果状态"]),
            _feature("F-event", ["PRD §8.2 事件资产检测", "PRD §8.3 事件资产创建"]),
            _feature("F-limit", ["PRD §8.4 批量提交防超限"]),
        ],
        start_idx=10,
    )

    by_key = {tp.structural_key: tp for tp in points}

    assert set(by_key) >= {"batch_submit", "submit_result_state", "event_asset", "submit_limit"}
    event = by_key["event_asset"]
    assert event.id == "TP-013"
    assert event.feature_id == "F-event"
    assert event.dimension == "functional_correctness"
    assert event.applicable_dimensions == ["functional_correctness"]
    assert event.priority == "P0"
    assert event.likelihood == 3
    assert event.impact == 3
    assert event.structural_type == "critical_flow"
    assert event.structural_key == "event_asset"
    assert event.derived_from == ["PRD §8.2 事件资产检测", "PRD §8.3 事件资产创建"]
    assert "事件资产" in event.description


def test_build_critical_flow_test_points_dedupes_one_anchor_per_flow():
    points = build_critical_flow_test_points(
        [
            _feature("F-event-a", ["PRD §8.2 事件资产检测"]),
            _feature("F-event-b", ["PRD §8.3 事件资产创建"]),
        ],
        start_idx=0,
    )

    assert [tp.structural_key for tp in points] == ["event_asset"]
    assert points[0].feature_id == "F-event-a"
    assert points[0].derived_from == ["PRD §8.2 事件资产检测", "PRD §8.3 事件资产创建"]


def test_build_critical_flow_test_points_does_not_match_section_prefix_collision():
    points = build_critical_flow_test_points(
        [_feature("F-state", ["PRD §5.8.13.1 提交结果状态"])],
        start_idx=0,
    )

    assert [tp.structural_key for tp in points] == ["submit_result_state"]


def test_build_critical_flow_test_points_ignores_unmatched_features():
    assert build_critical_flow_test_points([_feature("F-normal", ["PRD §5.6 标题包"])], start_idx=0) == []


@pytest.mark.asyncio
async def test_test_points_node_appends_critical_flow_anchors_when_structural_enabled(monkeypatch):
    parsed = ParsedContext(
        sources=[
            SourceItem(
                doc_id="11111111-1111-1111-1111-111111111111",
                doc_type="prd",
                trust_level=5,
                title="PRD",
                sections=[
                    SectionExtract(
                        heading="8.4 批量提交防超限",
                        content="提交限流、幂等、防重复",
                        source_ref="PRD §8.4",
                    )
                ],
            )
        ],
        features=[_feature("F-limit", ["PRD §8.4 批量提交防超限"])],
    )

    from src.testcase_generator.stages.test_points.structural import expander, permission_extractor, state_extractor

    monkeypatch.setattr(tp_node, "_generate_test_points_batched", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        permission_extractor, "extract_permission_matrix", AsyncMock(return_value=SimpleNamespace(grants=[]))
    )
    monkeypatch.setattr(state_extractor, "extract_state_machines", AsyncMock(return_value=[]))
    monkeypatch.setattr(expander, "expand_permission", lambda *args, **kwargs: [])
    monkeypatch.setattr(expander, "expand_state_machine", lambda *args, **kwargs: [])

    out = await tp_node.test_points_node(
        {
            "parsed_context": parsed,
            "generation_config": {
                "structural_coverage_enabled": True,
                "p0_quota_enabled": True,
                "p0_quota": 0.01,
            },
        }
    )

    tps = out["test_points"]
    assert len(tps) == 1
    assert tps[0].structural_type == "critical_flow"
    assert tps[0].structural_key == "submit_limit"
    assert tps[0].priority == "P0"
