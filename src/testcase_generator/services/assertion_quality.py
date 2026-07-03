"""用例断言质量规则。

这些规则只判断“预期结果是否足够可执行/可观察”，不替代 PRD 事实核验。
"""

from __future__ import annotations

import re

VAGUE_ASSERTION_RE = re.compile(r"正常|正确|符合要求|符合预期|成功显示|正常显示|校验正确|展示正确|信息正确")

_PURE_VAGUE_PHRASES = (
    "正常",
    "正确",
    "符合要求",
    "符合预期",
    "成功显示",
    "正常显示",
    "校验正确",
    "展示正确",
    "信息正确",
)
_PURE_VAGUE_PREFIX_RE = re.compile(
    r"^(?:(?:页面|系统|信息|数据|字段|列表|表格|结果|内容|校验|展示|显示|保存|提交|操作)(?:后)?)?"
)
_PUNCT_RE = re.compile(r"[\s，,。.;；:：!！]+")
_CONCRETE_OBSERVABLE_RE = re.compile(
    r"\d|[A-Za-z_][A-Za-z0-9_]*|[「『\"'`].{1,}[」』\"'`]|"
    r"状态为|显示为|值为|等于|包含|不包含|写入|生成|创建|删除|阻止|拦截|不可提交|"
    r"置灰|禁用|清空|保留|同步|回写|任务|记录|payload|接口|表"
)


def has_vague_assertion_signal(text: str) -> bool:
    """是否含宽口径模糊断言信号，用于审计诊断。"""
    return bool(VAGUE_ASSERTION_RE.search(text or ""))


def is_pure_vague_assertion(text: str) -> bool:
    """是否为几乎没有可执行信息的纯模糊预期。

    含具体数值、字段名、引号文案、状态/写入/任务/接口等可观察细节时不命中。
    """
    normalized = _PUNCT_RE.sub("", text or "")
    if not normalized:
        return False
    if _CONCRETE_OBSERVABLE_RE.search(normalized):
        return False
    remainder = _PURE_VAGUE_PREFIX_RE.sub("", normalized, count=1)
    return bool(remainder) and all(phrase in _PURE_VAGUE_PHRASES for phrase in _split_vague_phrases(remainder))


def is_pure_vague_assertion_case(
    expected_results: list[str] | tuple[str, ...],
    step_expected_results: list[str] | tuple[str, ...],
) -> bool:
    """整条用例是否只有纯模糊预期。

    只要任一预期含具体可观察细节，就不把整条 case 判为纯模糊。
    """
    assertions = [str(item or "") for item in expected_results] + [str(item or "") for item in step_expected_results]
    assertions = [item for item in assertions if item.strip()]
    return bool(assertions) and all(is_pure_vague_assertion(item) for item in assertions)


def _split_vague_phrases(text: str) -> list[str]:
    """按已知模糊短语贪心切分，无法完整切分则返回原文。"""
    parts: list[str] = []
    remaining = text
    phrases = sorted(_PURE_VAGUE_PHRASES, key=len, reverse=True)
    while remaining:
        matched = next((phrase for phrase in phrases if remaining.startswith(phrase)), None)
        if not matched:
            return [text]
        parts.append(matched)
        remaining = remaining[len(matched) :]
    return parts
