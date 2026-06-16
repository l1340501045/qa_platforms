"""Task 2.1 — 规则驱动测试点（规则锚点）测试。

验证：每条规则确定性产出 1 个带 rule_id 的锚点测试点，按章节号/标题就近匹配到 feature；
维度增强测试点 rule_id=None；开关关时不产锚点。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.testcase_generator.schemas.parsed_context import (
    FeatureItem,
    ParsedContext,
    SectionExtract,
    SourceItem,
)
from src.testcase_generator.stages.test_points import node as tp_node
from src.testcase_generator.stages.test_points.node import TestPointsLLMOutput
from src.testcase_generator.stages.test_points.rule_anchor import (
    build_rule_anchored_test_points,
    match_feature_for_rule,
)

FEATURES = [
    FeatureItem(id="F-001", name="5.1 账户授权", description="授权管理", source_refs=["PRD §5.1"]),
    FeatureItem(id="F-002", name="5.8 批量创建", description="批量建广告", source_refs=["PRD §5.8"]),
]

RULES = [
    {"rule_code": "R-001", "module": "5.1 头条账户授权管理 › 5.1.2 字段说明", "rule": "高级别权限包含低级别", "category": "权限", "source_quote": "q1"},
    {"rule_code": "R-002", "module": "5.8 批量创建", "rule": "单次批量上限一千条", "category": "边界", "source_quote": "q2"},
]


def test_match_feature_by_section_number():
    # "5.1 ..." 锚到 F-001（章节号 5.1 强信号），"5.8 ..." 锚到 F-002
    assert match_feature_for_rule("5.1 头条账户授权管理 › 5.1.2 字段说明", FEATURES) == "F-001"
    assert match_feature_for_rule("5.8 批量创建", FEATURES) == "F-002"


def test_match_feature_fallback_when_no_overlap():
    # 完全无重叠时回退到第一个 feature（保证有上下文，不丢规则）
    assert match_feature_for_rule("99.9 完全无关模块", FEATURES) == "F-001"
    # 无 feature 时返回空串（write_cases 走 PRD 通用上下文分支）
    assert match_feature_for_rule("任意", []) == ""


def test_build_one_anchor_per_rule_with_rule_id():
    tps = build_rule_anchored_test_points(RULES, FEATURES, start_idx=5)
    assert len(tps) == 2  # 每条规则恰 1 个锚点
    assert [tp.id for tp in tps] == ["TP-006", "TP-007"]
    assert [tp.rule_id for tp in tps] == ["R-001", "R-002"]
    # 锚点就近匹配 feature
    by_code = {tp.rule_id: tp for tp in tps}
    assert by_code["R-001"].feature_id == "F-001"
    assert by_code["R-002"].feature_id == "F-002"
    # 规则文本进入描述，且权限类规则优先级 P0
    assert "高级别权限包含低级别" in by_code["R-001"].description
    assert by_code["R-001"].priority == "P0"


def test_empty_rules_yield_no_anchors():
    assert build_rule_anchored_test_points([], FEATURES, start_idx=0) == []


# ── 节点级集成：开关控制规则锚点是否进入 test_points ──────────────────────────────

def _state_with_rules() -> dict:
    parsed = ParsedContext(
        sources=[
            SourceItem(
                doc_id="11111111-1111-1111-1111-111111111111",
                doc_type="prd",
                trust_level=5,
                title="PRD",
                sections=[SectionExtract(heading="5.1 账户授权", content="授权说明", source_ref="PRD §5.1")],
            )
        ],
        features=FEATURES,
    )
    return {"parsed_context": parsed, "rules": RULES}


async def _run_node(monkeypatch, enabled: bool) -> list:
    monkeypatch.setattr(tp_node.settings, "rule_driven_testpoints_enabled", enabled)
    # LLM 维度路径返回空（不影响开关验证），锚点路径独立于 LLM
    fake_client = AsyncMock()
    fake_client.generate_structured = AsyncMock(return_value=TestPointsLLMOutput(test_points=[]))
    with patch.object(tp_node, "get_llm_client", return_value=fake_client):
        out = await tp_node.test_points_node(_state_with_rules())
    return out["test_points"]


@pytest.mark.asyncio
async def test_node_appends_anchors_when_enabled(monkeypatch):
    tps = await _run_node(monkeypatch, enabled=True)
    anchored = [tp for tp in tps if tp.rule_id]
    assert {tp.rule_id for tp in anchored} == {"R-001", "R-002"}  # 每条规则被锚定
    # ID 连续无重复
    ids = [tp.id for tp in tps]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_node_no_anchors_when_disabled(monkeypatch):
    tps = await _run_node(monkeypatch, enabled=False)
    assert all(tp.rule_id is None for tp in tps)  # 开关关：零规则锚点，行为同历史
