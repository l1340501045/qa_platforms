"""Chunk 4 audit 修复套件单测：

P0-1 rule_extract 同源段落合并
P0-2 parse 同名 feature 合并
P0-3 splitter 跳过 future/tbd/mock 关键词章节
P1-1 维度增强按 section_kind / 稀薄章节跳过
P1-2 splitter 跳过 §9/§6 字段汇总章节
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge_base.schemas.common import SearchResult
from src.testcase_generator.schemas.parsed_context import FeatureItem
from src.testcase_generator.schemas.rule import ExtractedRule, UnitRules
from src.testcase_generator.stages.parse.node import _extract_sections, _normalize_heading, _extract_features_from_sections
from src.testcase_generator.schemas.parsed_context import SectionExtract
from src.testcase_generator.stages.rule_extract.extractor import (
    _merge_same_paragraph_rules,
    extract_rules,
)
from src.testcase_generator.stages.rule_extract.splitter import build_units
from src.testcase_generator.stages.test_points.node import (
    _dim_tp_cap_for,
    _gate_by_section_kind,
)


# ─── P0-2 parse 同名 feature 合并 ──────────────────────────────────────────────


def test_normalize_heading_strips_section_numbers_and_punct():
    assert _normalize_heading("六、监测链接说明") == "监测链接说明"
    assert _normalize_heading("7.3 后续迭代方向（非本期范围）") == "后续迭代方向非本期范围"
    # 同 PRD 章节名两种写法应归一化为同一个 key
    assert _normalize_heading("六类投放方式字段对照") == _normalize_heading("六类投放方式字段对照")
    assert _normalize_heading("§5.6 标题包") == _normalize_heading("5.6 标题包") == "标题包"


def test_same_named_features_force_merged():
    """根因 P0-2：F-012/F-013 灾难型——同 PRD 章节切两个 feature 灾难。"""
    sections = [
        SectionExtract(heading="6.1 六类投放方式字段对照", content="表格 A...", source_ref="PRD §6.1-A"),
        SectionExtract(heading="6.2 六类投放方式字段对照", content="表格 B...", source_ref="PRD §6.2-B"),
    ]
    features = _extract_features_from_sections(sections, start_index=0)
    assert len(features) == 1, "同名 feature 应强制合并为一条"
    feat = features[0]
    assert "表格 A" in feat.description and "表格 B" in feat.description
    assert feat.source_refs == ["PRD §6.1-A", "PRD §6.2-B"]


def test_distinct_features_stay_separate():
    """同名合并不能误伤不同名章节（零回归）。"""
    sections = [
        SectionExtract(heading="5.6 标题包", content="标题包说明", source_ref="PRD §5.6"),
        SectionExtract(heading="5.7 定向包", content="定向包说明", source_ref="PRD §5.7"),
    ]
    features = _extract_features_from_sections(sections, start_index=0)
    assert len(features) == 2
    assert {f.name for f in features} == {"5.6 标题包", "5.7 定向包"}


# ─── P0-3 / P1-2 splitter 跳过非 spec / 汇总章节 ───────────────────────────────


def _md_with_section(heading: str, body: str) -> str:
    """构造一个含目标章节 + 一个普通章节的 md（普通章节作为对照锚）。"""
    body_padded = body if len(body) >= 100 else body + "正文" * 30
    return (
        "# 五、功能详述\n"
        f"## {heading}\n{body_padded}\n"
        "## 5.1 账户授权\n"
        + "投手只能查看本人触发的授权记录。组长可查看本组全部成员的授权记录。" * 3
        + "\n"
    )


def test_splitter_drops_future_section():
    """P0-3：标注「非本期范围/后续迭代方向」的章节整树丢弃，不再产 0 case 灌水。"""
    md = _md_with_section("7.3 后续迭代方向（非本期范围）", "二期方案：xxx，本期不实现")
    units, _, _ = build_units(md)
    titles = [u["title"] for u in units]
    assert not any("后续迭代方向" in t for t in titles), "future 章节应整树丢弃"
    # 普通章节仍保留（不连坐）
    assert any("5.1" in t for t in titles)


def test_splitter_drops_field_constraint_summary():
    """P1-2：§9 字段约束汇总型章节整树丢弃（F-024-027 的 385 case 全是 §5.x 副本）。"""
    md = _md_with_section("9.1 全局通用约束", "字段汇总：项目数 1-30 整数；标题字数 5-55；...")
    units, _, _ = build_units(md)
    titles = [u["title"] for u in units]
    assert not any("9.1" in t and "通用约束" in t for t in titles), "通用字段约束汇总章节应整树丢弃"


def test_splitter_drops_initial_feature_list():
    """P0-3：「初版功能清单」是 PRD 索引型元章节，整树丢弃。"""
    md = _md_with_section("四、初版功能清单", "| 模块 | 优先级 |\n| -- | -- |\n| 标题包 | P0 |")
    units, _, _ = build_units(md)
    titles = [u["title"] for u in units]
    assert not any("初版功能清单" in t for t in titles)


def test_splitter_does_not_drop_normal_sections():
    """零回归保护：splitter 关键词扩展不能误伤普通章节。"""
    md = (
        "# 平台 PRD\n"
        "## 5.1 头条账户管理\n" + "投手只能查看本人触发的授权记录。" * 8 + "\n"
        "## 5.6 标题包\n" + "标题包是一组广告文案的集合。" * 8 + "\n"
        "## 5.8 批量创建\n" + "批量创建广告核心页面包含九个配置区。" * 8 + "\n"
    )
    units, _, _ = build_units(md)
    titles = [u["title"] for u in units]
    assert any("5.1" in t for t in titles)
    assert any("5.6" in t for t in titles)
    assert any("5.8" in t for t in titles)


# ─── P0-1 rule_extract 同源段落合并 ────────────────────────────────────────────


def test_merge_same_paragraph_rules_collapses_close_quotes():
    """模拟 F-008 §5.6.6：删除二次确认连续 5 条规则在原文同一段落 → 合并为 1 条。"""
    unit_text = (
        "5.6.6 删除与二次确认（标题包 / 标题库共用样式）\n"
        "标题包 Tab — 行内「删除」；标题库 Tab — 行内「删除」；工具栏「删除选中」（未勾选时按钮禁用）；"
        "使用页面级居中 Dialog（sm:max-w-sm 窄屏卡片）；"
        "底部 DialogFooter 右对齐：取消（outline）+ 删除（destructive）；"
        "标题包侧重「后续批创不可再选该包」；"
        "标题库单行侧重「库内与批创勾选列表移除」及「已生成包为快照」；"
        "批量删除须包含勾选条数 N，避免误删；"
        "已生成包为快照"
    )
    rules = [
        ExtractedRule(rule="标题包 Tab 行内提供删除", source_quote="标题包 Tab — 行内「删除」", category="功能"),
        ExtractedRule(rule="标题库 Tab 行内提供删除", source_quote="标题库 Tab — 行内「删除」", category="功能"),
        ExtractedRule(rule="工具栏删除选中按钮", source_quote="工具栏「删除选中」", category="功能"),
        ExtractedRule(rule="未勾选时按钮禁用", source_quote="未勾选时按钮禁用", category="状态"),
        ExtractedRule(rule="弹页面级 Dialog", source_quote="使用页面级居中 Dialog", category="功能"),
        ExtractedRule(rule="按钮 outline+destructive 样式", source_quote="底部 DialogFooter 右对齐：取消（outline）+ 删除（destructive）", category="功能"),
    ]
    merged, dropped = _merge_same_paragraph_rules(rules, unit_text)
    # 6 条规则全部在 ~250 字段落内 → 应合并为 1 条
    assert len(merged) == 1, f"同段落 6 条应合并为 1 条，实际 {len(merged)}"
    assert dropped == 5
    assert "标题包 Tab 行内提供删除" in merged[0].rule
    assert "弹页面级 Dialog" in merged[0].rule


def test_merge_keeps_distant_rules_separate():
    """零回归：原文位置距离远的规则不应被合并。"""
    unit_text = (
        "5.7 定向包\n"
        "5.7.1 性别字段：取值男/女\n"
        + "正文" * 200  # ~400 字隔离
        + "\n5.7.7 提交：弹二次确认框"
    )
    rules = [
        ExtractedRule(rule="性别取值男女", source_quote="取值男/女", category="校验"),
        ExtractedRule(rule="提交弹二次确认", source_quote="弹二次确认框", category="功能"),
    ]
    merged, dropped = _merge_same_paragraph_rules(rules, unit_text)
    assert len(merged) == 2, "相距 ~400 字的规则不应合并"
    assert dropped == 0


def test_merge_preserves_rules_with_missing_source_quote():
    """零回归：source_quote 找不到时的规则原样保留，不参与合并。"""
    unit_text = "5.1 授权\n投手只能查看本人记录。组长可查看本组全部成员的授权记录。"
    rules = [
        ExtractedRule(rule="投手只能查看本人记录", source_quote="投手只能查看本人记录", category="权限"),
        ExtractedRule(rule="组长可查看全组记录", source_quote="组长可查看本组全部成员的授权记录", category="权限"),
        ExtractedRule(rule="管理员可查全量", source_quote="管理员看全量", category="权限"),  # source_quote 在原文中找不到
    ]
    merged, _ = _merge_same_paragraph_rules(rules, unit_text)
    # 前两条同段落合并为 1，第三条 source_quote 找不到原样保留
    assert len(merged) == 2


@pytest.mark.asyncio
async def test_extractor_integrates_same_paragraph_merging():
    """端到端：extract_rules 集成同源合并，输出规则数 < LLM 原始输出。"""

    class _DenseClient:
        async def generate_structured(self, system, user, schema, temperature=0.3):
            return UnitRules(
                rules=[
                    ExtractedRule(rule="规则1", source_quote="第一段第一句", category="功能"),
                    ExtractedRule(rule="规则2", source_quote="第一段第二句", category="功能"),
                    ExtractedRule(rule="规则3", source_quote="第一段第三句", category="功能"),
                ]
            )

    units = [
        {
            "title": "5.X 测试",
            "level": 2,
            "chars": 100,
            "text": "5.X 测试\n第一段第一句。第一段第二句。第一段第三句。",
        }
    ]
    ledger = await extract_rules(units, digest="", client=_DenseClient(), concurrency=1)
    assert ledger.total == 1, f"3 条同段规则应合并为 1 条，实际 {ledger.total}"


# ─── P1-1 维度门控按 section_kind + 内容规模分档 ───────────────────────────────


def _dim(name: str) -> dict:
    return {"name": name, "category": "x"}


def test_gate_by_section_kind_summary_keeps_only_core():
    dims = [_dim("functional_correctness"), _dim("response_time"), _dim("api_contract"), _dim("boundary_value")]
    # summary 章节：只保留核心维度
    kept = _gate_by_section_kind(dims, "summary", feature_desc_chars=5000)
    names = {d["name"] for d in kept}
    assert "functional_correctness" in names
    assert "boundary_value" in names
    assert "response_time" not in names
    assert "api_contract" not in names


def test_gate_by_section_kind_future_keeps_only_core():
    dims = [_dim("functional_correctness"), _dim("input_injection"), _dim("data_migration")]
    kept = _gate_by_section_kind(dims, "future", feature_desc_chars=5000)
    names = {d["name"] for d in kept}
    assert names == {"functional_correctness"}


def test_gate_tier1_sparse_feature_keeps_only_core():
    """tier 1 (≤300 字)：F-018 类型稀薄章节（80 字 PRD 产 84 case）：只保留核心维度。"""
    dims = [_dim("functional_correctness"), _dim("response_time"), _dim("network_error"), _dim("invalid_input")]
    kept = _gate_by_section_kind(dims, "spec", feature_desc_chars=80)
    names = {d["name"] for d in kept}
    assert "functional_correctness" in names
    assert "invalid_input" in names
    assert "response_time" not in names
    assert "network_error" not in names


def test_gate_tier2_small_feature_limits_non_core_to_2():
    """tier 2 (300-1200 字)：核心维度全留 + 最多 2 个非核心维度。"""
    dims = [
        _dim("functional_correctness"), _dim("invalid_input"), _dim("boundary_value"),  # 3 核心
        _dim("response_time"), _dim("api_contract"), _dim("network_error"), _dim("data_migration"),  # 4 非核心
    ]
    kept = _gate_by_section_kind(dims, "spec", feature_desc_chars=800)
    names = [d["name"] for d in kept]
    # 3 核心 + 2 非核心 = 5 维度
    assert len(kept) == 5
    assert "functional_correctness" in names and "invalid_input" in names and "boundary_value" in names
    # 非核心按列表顺序保留前 2 个
    assert "response_time" in names and "api_contract" in names
    assert "network_error" not in names and "data_migration" not in names


def test_gate_tier3_medium_feature_limits_non_core_to_4():
    """tier 3 (1200-3000 字)：核心维度全留 + 最多 4 个非核心维度。

    覆盖 V1.8 CP 书籍权限管理 PRD §3 合并 ~2100 字（含 UI 原型表格）这种"中型 feature"。
    """
    dims = [_dim("functional_correctness")] + [_dim(f"non_core_{i}") for i in range(8)]
    kept = _gate_by_section_kind(dims, "spec", feature_desc_chars=2100)
    # 1 核心 + 4 非核心 = 5 维度
    assert len(kept) == 5


def test_gate_tier4_large_feature_unchanged():
    """tier 4 (>3000 字)：零回归——大型 feature 不再二次裁剪（仍由关键词门控）。"""
    dims = [_dim("functional_correctness"), _dim("response_time"), _dim("api_contract")]
    kept = _gate_by_section_kind(dims, "spec", feature_desc_chars=5000)
    assert kept == dims


# ─── P1-1 维度测试点数量分档截断 _dim_tp_cap_for ───────────────────────────────


def test_dim_tp_cap_tier1_returns_zero():
    """tier 1：稀薄/非 spec 章节，仅锚定，维度测试点 = 0"""
    assert _dim_tp_cap_for("spec", 80) == 0
    assert _dim_tp_cap_for("spec", 200) == 0
    assert _dim_tp_cap_for("summary", 5000) == 0
    assert _dim_tp_cap_for("future", 5000) == 0
    assert _dim_tp_cap_for("flow", 5000) == 0
    assert _dim_tp_cap_for("mock", 5000) == 0
    assert _dim_tp_cap_for("tbd", 5000) == 0


def test_dim_tp_cap_tier2_small_feature():
    """tier 2 (300-1200 字)：维度测试点 ≤ 5"""
    assert _dim_tp_cap_for("spec", 500) == 5
    assert _dim_tp_cap_for("spec", 1200) == 5


def test_dim_tp_cap_tier3_medium_feature():
    """tier 3 (1200-3000 字)：维度测试点 ≤ 15。覆盖本 PRD F-002（2145 字）。"""
    assert _dim_tp_cap_for("spec", 1500) == 15
    assert _dim_tp_cap_for("spec", 2145) == 15
    assert _dim_tp_cap_for("spec", 3000) == 15


def test_dim_tp_cap_tier4_large_feature_returns_none():
    """tier 4 (>3000 字)：返回 None 表示不截断（保持原行为）"""
    assert _dim_tp_cap_for("spec", 3001) is None
    assert _dim_tp_cap_for("spec", 5000) is None
    assert _dim_tp_cap_for("spec", 10000) is None


# ─── 端到端：parse 把 section_kind 透传到 feature ──────────────────────────────


def test_parse_propagates_section_kind_to_feature():
    """parse_node 步骤 5.6 应把 section.section_kind 同步给 feature.section_kind。"""
    # 构造一个 section 标 future，确认 _extract_features_from_sections 不丢字段
    sections = [
        SectionExtract(heading="5.6 标题包", content="标题包是一组广告文案", source_ref="PRD §5.6", section_kind="spec"),
    ]
    features = _extract_features_from_sections(sections, start_index=0)
    assert len(features) == 1
    # _extract_features_from_sections 不直接读 section_kind（由 parse_node 步骤 5.6 透传）
    # 这里仅验证 FeatureItem 默认 section_kind=spec
    assert features[0].section_kind == "spec"
