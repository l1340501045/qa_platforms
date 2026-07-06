"""断言质量规则单测。"""

from __future__ import annotations

from src.testcase_generator.services.assertion_quality import (
    has_vague_assertion_signal,
    is_pure_vague_assertion,
    is_pure_vague_assertion_case,
)


def test_pure_vague_assertion_matches_non_executable_phrases():
    assert is_pure_vague_assertion("页面正常显示，信息正确")
    assert is_pure_vague_assertion("符合预期")
    assert is_pure_vague_assertion("校验正确")
    assert is_pure_vague_assertion("保存后信息正确")


def test_pure_vague_assertion_ignores_concrete_observable_detail():
    assert not is_pure_vague_assertion("列表正常显示账户名称、账户ID，授权状态为已授权")
    assert not is_pure_vague_assertion("提交后写入 batch_tasks 记录")
    assert not is_pure_vague_assertion("提示文案为「账户不能为空」")


def test_pure_vague_case_requires_all_expected_results_to_be_vague():
    assert is_pure_vague_assertion_case(["页面正常显示"], ["信息正确"])
    assert not is_pure_vague_assertion_case(["页面正常显示"], ["状态为提交成功"])


def test_vague_signal_is_wider_than_pure_vague_guard():
    assert has_vague_assertion_signal("列表正常显示账户名称、账户ID")
    assert not is_pure_vague_assertion("列表正常显示账户名称、账户ID")
