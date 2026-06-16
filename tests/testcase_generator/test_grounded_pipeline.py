"""阶段1+2 新机制的纯逻辑单测（不依赖 LLM）：
- review_router 覆盖回填回环（含上限）
- dedup 近重复聚类
- verify verdict→bucket 确定性映射
"""

from __future__ import annotations

from src.testcase_generator.pipeline.edges import MAX_RECONCILE, review_router
from src.testcase_generator.schemas.parsed_context import (
    ParsedContext,
    SectionExtract,
    SourceItem,
)
from src.testcase_generator.stages.context_utils import CrossFeatureIndex
from src.testcase_generator.stages.dedup.clustering import DedupCase, find_duplicates
from src.testcase_generator.stages.verify.verifier import _VERDICT_BUCKET, _normalize_verdict


class _Audit:
    def __init__(self, uncovered):
        self.uncovered_test_point_ids = uncovered


def test_review_router_loops_to_backfill_when_uncovered():
    state = {"audit_report": _Audit(["TP-009"]), "reconcile_iterations": 0}
    assert review_router(state) == "backfill"


def test_review_router_stops_at_reconcile_cap():
    state = {"audit_report": _Audit(["TP-009"]), "reconcile_iterations": MAX_RECONCILE}
    assert review_router(state) == "verify"


def test_review_router_to_verify_when_fully_covered():
    state = {"audit_report": _Audit([]), "reconcile_iterations": 0}
    assert review_router(state) == "verify"


def test_verdict_bucket_mapping_is_deterministic():
    assert _VERDICT_BUCKET["grounded"] == "main"
    assert _VERDICT_BUCKET["conflict"] == "to_fix"
    assert _VERDICT_BUCKET["ungrounded"] == "needs_spec"
    assert _VERDICT_BUCKET["undefined"] == "needs_spec"


def test_unknown_verdict_normalized_strictly():
    # 无法识别的 verdict 从严归 ungrounded（不放进主集）
    assert _normalize_verdict("garbage") == "ungrounded"
    assert _normalize_verdict("GROUNDED") == "grounded"


def test_dedup_flags_parametric_near_duplicates():
    cases = [
        DedupCase("c1", "F-002", "切换每页显示条数为10条，验证列表数据条数正确"),
        DedupCase("c2", "F-002", "切换每页显示条数为50条，验证列表数据条数正确"),
        DedupCase("c3", "F-002", "切换每页显示条数为100条，验证列表数据条数正确"),
        DedupCase("c4", "F-003", "点击解绑按钮弹出二次确认对话框并成功解绑账户"),
    ]
    dup_map = find_duplicates(cases)
    # c2/c3 是 c1 的近重复（仅数字不同），c4 不应被并入
    assert dup_map.get("c2") == "c1"
    assert dup_map.get("c3") == "c1"
    assert "c4" not in dup_map


def test_dedup_empty_input():
    assert find_duplicates([]) == {}


def test_dedup_folds_placeholder_when_assertion_exists():
    # 同一测试点：有确定断言时，"需求待确认"占位用例应被折叠为断言的重复
    cases = [
        DedupCase("a1", "TP-1", "管理员可查看全量标题数据", text="可看到全部投手数据"),
        DedupCase("p1", "TP-1", "【需求待确认】管理员全量写操作权限范围",
                  text="PRD 未定义该行为，待 PM 澄清后再补确定断言", is_placeholder=True),
    ]
    dup_map = find_duplicates(cases)
    assert dup_map.get("p1") == "a1"
    assert "a1" not in dup_map


def test_dedup_keeps_single_placeholder_when_all_placeholder():
    # 全是占位 → 仅留其一
    cases = [
        DedupCase("p1", "TP-2", "【需求待确认】Token 过期返回 401", is_placeholder=True),
        DedupCase("p2", "TP-2", "【需求待确认】Token 过期提示重新登录", is_placeholder=True),
    ]
    dup_map = find_duplicates(cases)
    assert dup_map.get("p2") == "p1"


def test_dedup_protects_boundary_values():
    # 边界语义 + 数字不同 → 不同边界值的有效用例，绝不可误并
    cases = [
        DedupCase("b1", "TP-3", "导入恰好1000行数据时校验通过", text="提示导入成功"),
        DedupCase("b2", "TP-3", "导入恰好999行数据时校验通过", text="提示导入成功"),
        DedupCase("b3", "TP-3", "导入超出1001行数据时被拦截", text="提示超出上限"),
    ]
    dup_map = find_duplicates(cases)
    assert "b1" not in dup_map and "b2" not in dup_map and "b3" not in dup_map


def test_dedup_folds_same_tp_same_dim_reskin():
    # 同测试点+同维度、仅角色名不同的换皮断言（相似度落在 0.80~0.88，全局阈值抓不到）→ 折叠
    cases = [
        DedupCase("r1", "TP-9", "投手仅能查看本人创建的标题包", text="他人数据不可见",
                  dimension="权限与可见性"),
        DedupCase("r2", "TP-9", "运营仅能查看本人创建的标题包", text="他人数据不可见",
                  dimension="权限与可见性"),
    ]
    dup_map = find_duplicates(cases)
    assert dup_map.get("r2") == "r1"


def test_dedup_intra_dim_respects_boundary_protection():
    # 同测试点+同维度，但数字不同且含边界语义 → 仍受边界保护，不折叠
    cases = [
        DedupCase("x1", "TP-9", "输入恰好30字标题校验通过", text="保存成功",
                  dimension="边界值"),
        DedupCase("x2", "TP-9", "输入恰好29字标题校验通过", text="保存成功",
                  dimension="边界值"),
    ]
    dup_map = find_duplicates(cases)
    assert "x1" not in dup_map and "x2" not in dup_map


def test_dedup_folds_cross_tp_same_dim_near_equivalent():
    # 根因2b：不同测试点、同维度、语义近等价(功能点被切散后残留的换皮重复)→ 折叠。
    # 显式阈值：跨维度严到 0.99 几乎不并，同维度放宽 → 验证走的是「同维度低阈值」路径。
    cases = [
        DedupCase("u1", "TP-101", "非超管用户仅能查看本人负责的CP商选书数据",
                  text="他人CP商数据不可见", dimension="permission_denied"),
        DedupCase("u2", "TP-207", "非超管用户只能查看本人负责的CP商的选书数据",
                  text="他人CP商数据不展示", dimension="permission_denied"),
    ]
    dup_map = find_duplicates(cases, sim_threshold=0.99, cross_dim_threshold=0.70, min_shared_bigrams=2)
    assert dup_map.get("u2") == "u1"


def test_dedup_cross_tp_diff_dim_not_folded():
    # 跨测试点 + 不同维度：同样的措辞也走严阈值，不折叠(避免误并不同维度用例)
    cases = [
        DedupCase("v1", "TP-101", "非超管用户仅能查看本人负责的CP商选书数据",
                  text="他人CP商数据不可见", dimension="permission_denied"),
        DedupCase("v2", "TP-207", "非超管用户只能查看本人负责的CP商的选书数据",
                  text="他人CP商数据不展示", dimension="access_control"),
    ]
    dup_map = find_duplicates(cases, sim_threshold=0.99, cross_dim_threshold=0.70, min_shared_bigrams=2)
    assert "v2" not in dup_map


def test_dedup_cross_tp_same_dim_respects_boundary():
    # 跨测试点 + 同维度，但数字不同且含边界语义 → 受边界保护，不折叠
    cases = [
        DedupCase("w1", "TP-101", "上传恰好10MB文件时成功", text="提示上传成功", dimension="boundary_value"),
        DedupCase("w2", "TP-207", "上传恰好11MB文件时成功", text="提示上传成功", dimension="boundary_value"),
    ]
    dup_map = find_duplicates(cases, sim_threshold=0.99, cross_dim_threshold=0.50, min_shared_bigrams=2)
    assert "w1" not in dup_map and "w2" not in dup_map


def _ctx_with_sections(*sections):
    import uuid
    return ParsedContext(
        sources=[
            SourceItem(
                doc_id=uuid.uuid4(),
                doc_type="prd",
                trust_level=1,
                title="PRD",
                sections=[
                    SectionExtract(heading=h, content=c, source_ref=ref, section_kind="spec")
                    for (h, c, ref) in sections
                ],
            )
        ]
    )


def test_cross_feature_index_retrieves_spec_defined_elsewhere():
    # F-024 段定义了"任务状态机：草稿/提交/审核/驳回"；F-023 的测试点引用它 → 应被检索到
    ctx = _ctx_with_sections(
        ("F-023 批量提交", "用户在批量提交页发起提交动作", "PRD §5.8"),
        ("F-024 任务状态机", "任务状态机定义：草稿可提交，提交后进入审核，审核驳回回到草稿，终态为已发布",
         "PRD §5.9.3"),
    )
    index = CrossFeatureIndex(ctx)
    query = "状态机 校验批量提交后任务状态机草稿提交审核驳回的状态流转是否正确"
    hits = index.query(query, exclude_keys={("PRD §5.8", "F-023 批量提交")}, top_k=3)
    assert any(h.source_ref == "PRD §5.9.3" for h in hits)


def test_cross_feature_index_excludes_own_and_low_score():
    ctx = _ctx_with_sections(
        ("F-001 登录", "登录页输入账号密码点击登录", "PRD §1"),
        ("F-002 完全无关", "本章描述结算账单导出报表的字段格式", "PRD §2"),
    )
    index = CrossFeatureIndex(ctx)
    hits = index.query("登录页输入账号密码点击登录", exclude_keys={("PRD §1", "F-001 登录")}, top_k=3)
    # 自身已排除；无关章节词项重叠低于阈值 → 不召回
    assert hits == []
