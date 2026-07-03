"""用例级优先级校准单测。"""

from __future__ import annotations

from src.testcase_generator.stages.write_cases.priority_calibration import (
    calibrate_case_priority,
    is_low_value_display_case,
)


def test_low_value_display_p0_is_demoted_to_p2():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="入口页Tab按钮文案展示",
        expected_results=["页面正常显示入口按钮与Tab文案"],
        step_expected_results=["按钮与Tab文案展示正确"],
        dimensions=["ui_interaction"],
    )

    assert priority == "P2"


def test_business_risk_display_wording_keeps_p0():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="接口校验未通过时任务不写入batch_tasks队列",
        expected_results=["任务不写入batch_tasks，页面显示提交失败"],
        step_expected_results=["提交失败并保留当前配置"],
        dimensions=["data_integrity", "recovery"],
    )

    assert priority == "P0"


def test_domain_nouns_do_not_keep_display_only_case_at_p0():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="账户授权入口列表展示账户名称、账户ID和授权状态",
        expected_results=["列表正常显示账户名称、账户ID，授权状态为已授权"],
        step_expected_results=["账户数据展示正确"],
        dimensions=["ui_interaction"],
    )

    assert priority == "P2"


def test_domain_flow_with_failure_outcome_keeps_p0():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="账户授权失败时批创提交被阻止且任务不写入",
        expected_results=["提交被阻止，不写入batch_tasks，提示授权失败"],
        step_expected_results=["任务保持未提交状态"],
        dimensions=["data_integrity", "state_transition"],
    )

    assert priority == "P0"


def test_algorithmic_assignment_case_keeps_p0_even_with_display_hint():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="K>M循环复用分配算法验证（综合多选标题包场景）",
        expected_results=[
            "多选标题包串联后K>M时循环复用分配正确",
            "右栏顶部显示黄色循环复用提示",
        ],
        step_expected_results=[
            "候选池有序为D1-1、D1-2、D2-1",
            "广告6=D1-1（6 mod 5=1）",
        ],
        dimensions=["functional_correctness"],
    )

    assert priority == "P0"


def test_structural_dimensions_keep_p0_even_with_display_words():
    priority = calibrate_case_priority(
        parent_priority="P0",
        title="投手仅可见本人任务列表",
        expected_results=["任务列表仅展示本人创建的任务"],
        step_expected_results=["他人任务不可见"],
        dimensions=["access_control"],
    )

    assert priority == "P0"


def test_non_p0_priority_is_not_changed():
    priority = calibrate_case_priority(
        parent_priority="P1",
        title="入口页Tab按钮文案展示",
        expected_results=["页面正常显示入口按钮与Tab文案"],
        step_expected_results=["按钮与Tab文案展示正确"],
        dimensions=["ui_interaction"],
    )

    assert priority == "P1"


def test_low_value_display_predicate_matches_audit_definition():
    assert is_low_value_display_case(
        title="创意组卡片展开/折叠操作",
        expected_results=["创意组卡片支持展开和折叠切换"],
        step_expected_results=["创意组卡片展开，显示组内素材详情"],
        dimensions=["ui_interaction"],
    )

    assert not is_low_value_display_case(
        title="worker按账户维度串行调用巨量接口",
        expected_results=["同一账户广告创建请求严格串行执行"],
        step_expected_results=["不触发巨量引擎单账户频控限制"],
        dimensions=["concurrency_state"],
    )
