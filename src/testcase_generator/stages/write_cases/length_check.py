"""边界用例字数自校验：step 声称「N 字/字符」时校验 input_data 实际字符数，不符则告警。
不改写用例（避免误伤），仅返回告警供 confidence_note 标注。"""

from __future__ import annotations

import re

# 字数声明：捕获「N 字/N个字/N 字符」等。
# - (?<![第\d])：前导不是「第」也不是数字 —— 排除「第3个字段」「第10个字符位置」等序数表述，
#   并防止 \d+ 从多位数中间起匹（如「第10」回溯成「0个字符」）。
# - (?!符|段)：后随不是「符」「段」—— 排除「字段」误命中，且避免「N字符」被截成「N字」。
_CLAIM_RE = re.compile(r"(?<![第\d])(\d+)\s*个?\s*(?:字符|字)(?!符|段)")


def _visible_len(s: str) -> int:
    """可见字符数（去空白）。中文/英文均按 1 计。"""
    return len(re.sub(r"\s", "", s or ""))


def check_step_lengths(steps: list[dict]) -> list[str]:
    """逐步校验「N 字/字符」声明与 input_data 实际可见字符数是否一致，返回告警列表。

    仅返回告警（不改写用例，避免误伤），供 confidence_note 标注：
    - 已排除「第N个字/字段」等序数与词汇误匹配；
    - input_data 为空（actual=0）时跳过（无可比对输入）；
    - 同一步骤含多个字数声明时，实际值与任一声明相符即视为通过。
    """
    warnings: list[str] = []
    for idx, s in enumerate(steps or [], 1):
        text = f"{s.get('action', '')} {s.get('expected_result', '')}"
        claimed_values = [int(m.group(1)) for m in _CLAIM_RE.finditer(text)]
        if not claimed_values:
            continue
        actual = _visible_len(s.get("input_data", ""))
        if actual > 0 and actual not in claimed_values:
            shown = "/".join(str(c) for c in dict.fromkeys(claimed_values))
            warnings.append(f"步骤{idx}字数声明与输入不符：声称{shown}实为{actual}")
    return warnings
