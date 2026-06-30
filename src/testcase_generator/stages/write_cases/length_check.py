"""边界用例字数自校验：step 声称「N 字/字符」时校验 input_data 实际字符数，不符则告警。
不改写用例（避免误伤），仅返回告警供 confidence_note 标注。"""

from __future__ import annotations

import re

_CLAIM_RE = re.compile(r"(\d+)\s*个?\s*(?:字符|字)")


def _visible_len(s: str) -> int:
    """可见字符数（去空白）。中文/英文均按 1 计。"""
    return len(re.sub(r"\s", "", s or ""))


def check_step_lengths(steps: list[dict]) -> list[str]:
    warnings: list[str] = []
    for idx, s in enumerate(steps or [], 1):
        text = f"{s.get('action', '')} {s.get('expected_result', '')}"
        m = _CLAIM_RE.search(text)
        if not m:
            continue
        claimed = int(m.group(1))
        actual = _visible_len(s.get("input_data", ""))
        if actual > 0 and actual != claimed:
            warnings.append(f"步骤{idx}字数声明与输入不符：声称{claimed}实为{actual}")
    return warnings
