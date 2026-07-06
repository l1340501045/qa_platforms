"""边界字数自校验单测。"""

from __future__ import annotations

from src.testcase_generator.stages.write_cases.length_check import check_step_lengths


def test_mismatch_warns():
    data = "一二三四五六七八九十一二三四五六"  # 16 字
    steps = [{"action": "输入20个字符", "input_data": data, "expected_result": ""}]
    w = check_step_lengths(steps)
    assert w and "20" in w[0] and "16" in w[0]


def test_match_no_warn():
    steps = [{"action": "输入5个字", "input_data": "一二三四五", "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_no_claim_no_warn():
    steps = [{"action": "点击保存", "input_data": "无", "expected_result": "成功"}]
    assert check_step_lengths(steps) == []


def test_expected_result_claim_matches_input():
    """expected_result 中的字数声明也参与校验；与 input 相符则不告警。"""
    steps = [{"action": "操作", "input_data": "abc", "expected_result": "显示3个字符"}]
    assert check_step_lengths(steps) == []


def test_empty_input_no_warn():
    steps = [{"action": "输入10个字符", "input_data": "", "expected_result": ""}]
    assert check_step_lengths(steps) == []


# ── 误匹配防护（🔴 修复点：序数/词汇不应被当作字数声明）──────────────────────


def test_ordinal_field_not_warned():
    """「第N个字段」是序数+词汇，非字数声明，不应误判告警。"""
    steps = [{"action": "输入第3个字段", "input_data": "用户名", "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_ordinal_char_position_not_warned():
    """「第N个字符位置」是序数定位，非字数声明，不应误判告警。"""
    steps = [{"action": "光标定位到第10个字符位置", "input_data": "abc", "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_count_of_files_not_warned():
    """「N个文件」不含字/字符，不应命中。"""
    steps = [{"action": "上传3个文件", "input_data": "a.png,b.png", "expected_result": ""}]
    assert check_step_lengths(steps) == []


# ── 多声明覆盖（finditer）──────────────────────────────────────────────────


def test_multiple_claims_match_any_ok():
    """同一步骤多个字数声明，实际值与任一相符即视为通过。"""
    data = "一二三四五六七八九十一二"  # 12 字
    steps = [{"action": "输入100字符或12个字", "input_data": data, "expected_result": ""}]
    assert check_step_lengths(steps) == []


def test_multiple_claims_none_match_warns():
    """多声明且实际值与全部不符 → 告警并列出所有声明。"""
    steps = [{"action": "输入100字符或12个字", "input_data": "一二三四五", "expected_result": ""}]  # 5 字
    w = check_step_lengths(steps)
    assert w and "100" in w[0] and "12" in w[0] and "5" in w[0]
