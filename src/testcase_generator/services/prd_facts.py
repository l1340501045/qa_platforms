"""PRD 事实支撑小工具。

先承载跨 PRD 通用的“证据是否足以支撑唯一事实断言”判断，避免把事实判断散落在
verify guard 的领域正则里。当前只覆盖不完整枚举/外部目录场景，后续可继续扩展长度、
状态名、角色权限、边界值等 facts。
"""

from __future__ import annotations

import re

_EXTERNAL_DIR_SIGNALS: tuple[str, ...] = (
    "见外部目录",
    "见巨量",
    "参考外部目录",
    "参考第三方目录",
    "外部目录",
    "事件目录",
)
_ETC_RE = re.compile(r"等(?=[。，、；;。．.\n]|$)")
_QUOTED_VALUE_RE = re.compile(r"[`「『\"']([^`」』\"']{2,40})[`」』\"']")
_UNIQUE_FACT_ASSERTION_RE = re.compile(
    r"(?:映射(?:到|为)|显示为|展示为|对应|状态(?:显示|展示)?为|取值为|值为)\s*"
    r"(?P<value>[`「『\"'][^`」』\"']{2,40}[`」』\"']|[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fffA-Za-z0-9_ -]{2,20})"
)
_CLOSED_ENUM_RE = re.compile(
    r"(?:状态|状态值|取值|枚举|可选值)\s*(?:包括|包含|为|有|支持|可为)\s*[:：]?\s*(?P<values>[^。；;\n]{2,120})"
)
_ENUM_SPLIT_RE = re.compile(r"\s*(?:、|,|，|/|或|和)\s*")
_UNIT_PATTERN = (
    r"(?:个|条)?\s*(?:字符|字|账户|账号|标题|广告任务|广告|地区字符串|区县|地区|素材|创意组|组|宏参数|参数)"
    r"|个|条"
)
_UPPER_BOUND_RE = re.compile(
    r"(?P<prefix>最多|至多|不超过|不得超过|不能超过|上限(?:为|是)?|最大(?:为|是)?|单次最多)"
    r"[^。；;\n]{0,30}?"
    r"(?P<limit>\d+)\s*(?P<unit>" + _UNIT_PATTERN + r")"
)
_COUNT_UNIT_RE = re.compile(r"(?P<count>\d+)\s*(?P<unit>" + _UNIT_PATTERN + r")")
_ACCEPT_OVER_LIMIT_RE = re.compile(
    r"未(?:超出|超过|超限|拦截)|不(?:超出|超过|超限|拦截)|"
    r"可(?:通过|保存|提交|创建|选择|添加|上传|绑定)|"
    r"(?:通过|保存|提交|创建|选择|添加|上传|绑定)成功|"
    r"仍(?:允许|可)|校验通过"
)


def has_incomplete_fact_source(text: str) -> bool:
    """PRD 证据是否表达“不完整枚举/外部目录”。"""
    return any(signal in (text or "") for signal in _EXTERNAL_DIR_SIGNALS) or bool(_ETC_RE.search(text or ""))


def _clean_fact_value(raw: str) -> str:
    value = (raw or "").strip().strip("`「『\"'」』")
    # 常见句尾/连接词截断，避免中文无空格文本过度吞噬。
    value = re.split(r"[，,。；;\s]", value, maxsplit=1)[0]
    return value.strip()


def _canonical_unit(unit: str) -> str:
    compact = re.sub(r"\s+", "", unit or "")
    compact = re.sub(
        r"^[个条](?=字符|字|账户|账号|标题|广告任务|广告|地区字符串|区县|地区|素材|创意组|组|宏参数|参数)",
        "",
        compact,
    )
    if compact in {"个", "条"}:
        return ""
    if compact in {"账号"}:
        return "账户"
    if compact in {"广告"}:
        return "广告任务"
    if compact in {"区县", "地区字符串", "地区"}:
        return "地区"
    if compact in {"素材"}:
        return "素材"
    if compact in {"创意组", "组"}:
        return "组"
    if compact in {"参数", "宏参数"}:
        return "参数"
    return compact


def extract_unique_fact_values(assertion: str) -> list[str]:
    """从用例断言中提取“唯一具体事实值”。

    例如“状态显示为「部分失败」”“优化目标映射到 active_pay”。
    """
    values: list[str] = []
    seen: set[str] = set()
    for match in _UNIQUE_FACT_ASSERTION_RE.finditer(assertion or ""):
        raw = match.group("value")
        quoted = _QUOTED_VALUE_RE.fullmatch(raw.strip())
        value = _clean_fact_value(quoted.group(1) if quoted else raw)
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def extract_closed_enum_values(evidence: str) -> list[str]:
    """从 PRD 证据中提取完整枚举值。

    只有证据未出现“等/外部目录”且至少解析出 2 个取值时才返回。这样避免把非完整枚举
    当成闭集，导致合法未知值被误判为错误。
    """
    if has_incomplete_fact_source(evidence):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for match in _CLOSED_ENUM_RE.finditer(evidence or ""):
        raw_values = match.group("values")
        for raw in _ENUM_SPLIT_RE.split(raw_values):
            value = _clean_fact_value(raw)
            if value and value not in seen:
                values.append(value)
                seen.add(value)
    return values if len(values) >= 2 else []


def unsupported_unique_fact_assertion(assertion: str, evidence: str) -> str | None:
    """不完整 PRD 证据下的唯一事实断言是否缺少支撑。

    若 PRD 只写“状态包括 A、B 等”或“见外部目录”，而用例断言唯一状态/映射为 C，
    且 C 没有直接出现在证据中，则返回不可支撑原因。已在证据中列出的值仍放行。
    """
    if not has_incomplete_fact_source(evidence):
        return None
    for value in extract_unique_fact_values(assertion):
        if value not in (evidence or ""):
            return f"唯一事实{value}"
    return None


def unsupported_closed_enum_assertion(assertion: str, evidence: str) -> str | None:
    """完整枚举证据下的唯一事实断言是否越界。

    例如 PRD 写“状态包括待提交、执行中、提交完成-有失败”，用例断言“状态显示为
    「部分失败」”，则这是用例事实错误；若证据只写“状态包括待提交、执行中等”，则不在
    本函数处理范围内，应走 needs_spec 而不是 hard conflict。
    """
    enum_values = extract_closed_enum_values(evidence)
    if not enum_values:
        return None
    enum_set = set(enum_values)
    for value in extract_unique_fact_values(assertion):
        if value not in enum_set:
            return f"唯一事实{value}不在完整枚举[{','.join(enum_values)}]中"
    return None


def extract_numeric_upper_bounds(evidence: str) -> list[tuple[int, str, str]]:
    """从 PRD 证据中提取数字上限事实，返回 ``(limit, canonical_unit, raw_atom)``。"""
    bounds: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    for match in _UPPER_BOUND_RE.finditer(evidence or ""):
        limit = int(match.group("limit"))
        unit = _canonical_unit(match.group("unit"))
        key = (limit, unit)
        if key not in seen:
            bounds.append((limit, unit, match.group(0)))
            seen.add(key)
    return bounds


def unsupported_upper_bound_assertion(assertion: str, evidence: str) -> str | None:
    """PRD 明确数量上限时，超过上限仍通过/成功的断言是否错误。

    只处理“断言结果是允许/通过/成功”的越界样本；如果用例断言超过上限会被阻止，
    本函数不处理，避免误杀合法边界异常用例。
    """
    if not _ACCEPT_OVER_LIMIT_RE.search(assertion or ""):
        return None
    bounds = extract_numeric_upper_bounds(evidence)
    if not bounds:
        return None
    for count_match in _COUNT_UNIT_RE.finditer(assertion or ""):
        count = int(count_match.group("count"))
        assertion_unit = _canonical_unit(count_match.group("unit"))
        for limit, limit_unit, raw_bound in bounds:
            if assertion_unit and limit_unit and assertion_unit != limit_unit:
                continue
            if count > limit:
                unit_label = assertion_unit or limit_unit or count_match.group("unit")
                return f"数量上限冲突：证据{raw_bound}，断言{count}{unit_label}仍可通过/成功"
    return None
