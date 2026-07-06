"""边界用例字数自校验：step 声称「N 字/字符」时校验 input_data 实际字符数，不符则告警。
不改写用例（避免误伤），仅返回告警供 confidence_note 标注。"""

from __future__ import annotations

import math
import re
import unicodedata

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


# ── R7：字数边界确定性算法（任务 07-02）──────────────────────────────────────
# 半角字符（ASCII：英文字母/数字/半角标点/空格）按 0.5 个字宽计；全角字符
# （中日韩、全角符号）按 1 个字宽计。9 个半角字符 = 9 × 0.5 = 4.5 → 向上取整为 5。
# 用 East Asian Width 判定：W/F/A（宽/全角/模糊）按 1 计，Na/H/N（窄/半角/中性）按 0.5 计。
# 「模糊（A）」按 1 计是保守取整（含希腊/西里尔等可能宽也可能窄，从严计全角）。


def _char_width_units(ch: str) -> float:
    """单个字符的字宽单位：全角=1.0，半角=0.5。"""
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("W", "F", "A"):
        return 1.0
    return 0.5


def char_count_halfwidth_units(text: str) -> float:
    """按半角单位计字数：全角字符 1.0，半角字符 0.5。

    用于字数边界规则的确定性计算（不依赖 LLM 自由推理）。
    例：``char_count_halfwidth_units("abcdefghi") == 4.5``。
    """
    return sum(_char_width_units(ch) for ch in (text or ""))


def round_half_up(value: float) -> int:
    """标准四舍五入（半数向上取整），区别于 Python 默认的银行家舍入。

    例：``round_half_up(4.5) == 5``（Python 内置 ``round(4.5) == 4``）。
    """
    return int(math.floor(value + 0.5))
