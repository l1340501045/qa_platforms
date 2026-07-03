"""PRD facts helper 单测。"""

from __future__ import annotations

from src.testcase_generator.services.prd_facts import (
    extract_closed_enum_values,
    extract_numeric_upper_bounds,
    extract_unique_fact_values,
    has_incomplete_fact_source,
    unsupported_closed_enum_assertion,
    unsupported_unique_fact_assertion,
    unsupported_upper_bound_assertion,
)


def test_incomplete_fact_source_detects_etc_and_external_directory():
    assert has_incomplete_fact_source("状态包括待处理、处理中等")
    assert has_incomplete_fact_source("优化目标见巨量事件目录")
    assert not has_incomplete_fact_source("状态包括待处理、处理中、部分失败")


def test_extract_unique_fact_values_supports_chinese_and_identifier_values():
    values = extract_unique_fact_values("状态显示为「部分失败」，优化目标映射到 active_pay")

    assert values == ["部分失败", "active_pay"]


def test_unsupported_unique_fact_assertion_requires_direct_value_evidence():
    reason = unsupported_unique_fact_assertion(
        "状态显示为「部分失败」",
        "状态包括待提交、执行中等",
    )

    assert reason == "唯一事实部分失败"


def test_unsupported_unique_fact_assertion_allows_values_explicitly_listed_before_etc():
    reason = unsupported_unique_fact_assertion(
        "状态显示为「执行中」",
        "状态包括待提交、执行中等",
    )

    assert reason is None


def test_extract_closed_enum_values_requires_complete_enum_source():
    assert extract_closed_enum_values("状态包括待提交、执行中、提交完成-有失败") == [
        "待提交",
        "执行中",
        "提交完成-有失败",
    ]
    assert extract_closed_enum_values("状态包括待提交、执行中等") == []


def test_unsupported_closed_enum_assertion_rejects_value_outside_complete_enum():
    reason = unsupported_closed_enum_assertion(
        "状态显示为「部分失败」",
        "状态包括待提交、执行中、提交完成-有失败",
    )

    assert reason == "唯一事实部分失败不在完整枚举[待提交,执行中,提交完成-有失败]中"


def test_unsupported_closed_enum_assertion_allows_listed_value():
    reason = unsupported_closed_enum_assertion(
        "状态显示为「执行中」",
        "状态包括待提交、执行中、提交完成-有失败",
    )

    assert reason is None


def test_extract_numeric_upper_bounds_from_prd_evidence():
    assert extract_numeric_upper_bounds("地理位置最多选择1000个区县，单次最多提交200条地区字符串") == [
        (1000, "地区", "最多选择1000个区县"),
        (200, "地区", "单次最多提交200条地区字符串"),
    ]


def test_extract_numeric_upper_bounds_prefers_long_semantic_units():
    assert extract_numeric_upper_bounds("模板最多100字符，单次最多10广告任务，最多5宏参数") == [
        (100, "字符", "最多100字符"),
        (10, "广告任务", "单次最多10广告任务"),
        (5, "参数", "最多5宏参数"),
    ]


def test_unsupported_upper_bound_assertion_rejects_over_limit_success():
    reason = unsupported_upper_bound_assertion(
        "选择1001个区县后仍可提交成功",
        "地理位置最多选择1000个区县",
    )

    assert reason == "数量上限冲突：证据最多选择1000个区县，断言1001地区仍可通过/成功"


def test_unsupported_upper_bound_assertion_allows_exact_limit_success():
    reason = unsupported_upper_bound_assertion(
        "选择1000个区县后可提交成功",
        "地理位置最多选择1000个区县",
    )

    assert reason is None


def test_unsupported_upper_bound_assertion_ignores_over_limit_rejection_case():
    reason = unsupported_upper_bound_assertion(
        "选择1001个区县后被阻止提交并提示超出上限",
        "地理位置最多选择1000个区县",
    )

    assert reason is None
