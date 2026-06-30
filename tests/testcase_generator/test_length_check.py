"""边界字数自校验单测。"""

from __future__ import annotations

from src.testcase_generator.stages.write_cases.length_check import check_step_lengths


def test_mismatch_warns():
    steps = [{"action": "输入20个字符", "input_data": "一二三四五六七八九十一二三四五六", "expected_result": ""}]  # 16 字
    w = check_step_lengths(steps)
    assert w and "20" in w[0]


def test_match_no_warn():
    steps = [{"action": "输入5个字", "input_data": "一二三四五", "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_no_claim_no_warn():
    steps = [{"action": "点击保存", "input_data": "无", "expected_result": "成功"}]
    assert check_step_lengths(steps) == []


def test_mismatch_in_expected_result():
    steps = [{"action": "操作", "input_data": "abc", "expected_result": "显示3个字符"}]
    assert check_step_lengths(steps) == []


def test_empty_input_no_warn():
    steps = [{"action": "输入10个字符", "input_data": "", "expected_result": ""}]
    assert check_step_lengths(steps) == []
