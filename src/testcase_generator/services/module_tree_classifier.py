"""测试资产业务模块树分类器。

这里派生的是测试资产组织坐标；``provenance.source_section`` 仍然是需求证据坐标。
分类器保持纯函数，供审查导出和平台用例树复用。
"""

from __future__ import annotations

import re
from typing import Any

MODULE_RULES: list[dict] = [
    {
        "module": "标题包",
        "aliases": ("标题包", "标题库", "标题管理", "标题分配", "标题槽位", "拆包"),
        "section_prefixes": ("5.6",),
    },
    {
        "module": "账户授权",
        "aliases": ("账户授权", "账户选择", "广告主账户", "媒体账户", "头条账户", "投放人"),
        "section_prefixes": ("5.1",),
    },
    {
        "module": "漫剧库",
        "aliases": ("漫剧库", "漫剧选择", "漫剧资产"),
        "section_prefixes": ("5.2",),
    },
    {
        "module": "投放链接",
        "aliases": ("投放链接", "链接来源", "推广链接"),
        "section_prefixes": ("5.3",),
    },
    {
        "module": "商品库",
        "aliases": ("商品库", "商品选择", "商品资产"),
        "section_prefixes": ("5.4",),
    },
    {
        "module": "素材中心",
        "aliases": ("素材中心", "素材库", "创意素材", "素材上传", "媒体评估", "media_evaluation_tags", "素材"),
        "section_prefixes": ("5.5",),
    },
    {
        "module": "定向包",
        "aliases": ("定向包", "定向选择", "地区定向", "人群包"),
        "section_prefixes": ("5.7",),
    },
    {
        "module": "批量创建广告",
        "aliases": ("批创", "批量创建", "批量创建广告", "广告明细", "投放策略", "提交审核"),
        "section_prefixes": ("5.8",),
    },
    {
        "module": "任务中心",
        "aliases": ("任务中心", "任务列表", "执行状态", "任务状态", "状态任务", "查看原因"),
        "section_prefixes": ("5.9",),
    },
    {
        "module": "监测链接",
        "aliases": ("监测链接", "宏参数"),
        "section_prefixes": ("7",),
    },
    {
        "module": "提交底层与防超限",
        "aliases": ("防超限", "提交底层", "事件资产", "优化目标"),
        "section_prefixes": ("8",),
    },
    {
        "module": "全局规则与字段约束",
        "aliases": ("全局规则", "字段约束", "分页规则", "筛选项", "表头排序", "数据权限", "权限规则"),
        "section_prefixes": ("5.0", "9", "10"),
    },
]


TITLE_PACKAGE_BRANCH_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("自动拆包", "拆包"), ["自动拆包"]),
    (("标题分配", "槽位", "循环分配", "候选池", "批创", "联动"), ["批创联动", "标题分配"]),
    (("字数", "字符", "emoji", "名称长度", "字段与字数"), ["新建编辑", "字数算法"]),
    (("删除", "二次确认"), ["标题管理", "删除"]),
    (("入口", "页面预览", "列表", "搜索", "筛选", "表头"), ["入口与页面预览"]),
    (("新建", "编辑", "保存", "重名"), ["新建编辑"]),
]

GENERIC_BRANCH_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("入口", "页面预览", "列表"), ["入口与页面预览"]),
    (("筛选", "排序", "分页"), ["列表筛选与分页"]),
    (("权限", "可见", "组长", "管理员", "投手"), ["权限"]),
    (("删除", "解绑", "取消"), ["删除与解绑"]),
    (("提交", "保存", "创建", "编辑", "新建"), ["新建编辑"]),
]

MODULE_BRANCH_RULES: dict[str, list[tuple[tuple[str, ...], list[str]]]] = {
    "账户授权": [
        (("投放人",), ["投放人管理"]),
    ],
    "素材中心": [
        (("媒体评估", "media_evaluation_tags"), ["媒体评估与过滤"]),
    ],
    "任务中心": [
        (("任务状态", "状态任务", "操作列", "已取消", "复用"), ["任务状态与操作"]),
    ],
}

BATCH_CREATE_EMBEDDED_MODULES: list[tuple[str, str]] = [
    ("5.8.1", "漫剧库"),
    ("5.8.2", "账户授权"),
    ("5.8.5", "素材中心"),
    ("5.8.6", "标题包"),
    ("5.8.7", "商品库"),
]

NAMED_SOURCE_MODULES: list[tuple[str, str]] = [
    ("六类投放方式字段对照", "批量创建广告"),
    ("七、监测链接说明", "监测链接"),
]

CROSS_CUTTING_SOURCE_TAGS: list[tuple[str, str]] = [
    ("9", "field_constraint"),
    ("10", "permission"),
    ("5.0", "global_rule"),
]

FIELD_CONSTRAINT_MODULE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("账户选择", "账户选择-快搜", "快搜", "账户ID"), "账户授权"),
    (("标题包选择", "标题包", "每组条数", "每条字数", "单包上限"), "标题包"),
    (("定向包", "年龄"), "定向包"),
    (
        ("批创规模", "项目数", "广告数", "项目预算", "项目出价", "ROI", "命名", "广告名", "项目 / 广告名"),
        "批量创建广告",
    ),
    (("创意外显", "创意", "单组视频数", "创意组上限"), "素材中心"),
    (("Excel 上传", "Excel", "导入"), "投放链接"),
]

PERMISSION_MODULE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("任务", "重试"), "任务中心"),
    (("标题包", "标题库", "标题"), "标题包"),
    (("定向包", "定向"), "定向包"),
    (("账户授权", "授权记录", "账户"), "账户授权"),
    (("商品库", "商品"), "商品库"),
    (("素材库", "素材"), "素材中心"),
]

SOURCE_BRANCH_OVERRIDES: list[tuple[str, list[str]]] = [
    ("5.8.11.1", ["命名通配符", "通配符替换规则"]),
    ("5.8.11", ["命名通配符"]),
    ("5.8.6", ["批创联动", "标题分配"]),
    ("5.5.3.4", ["媒体评估与过滤", "低效拒审过滤"]),
    ("8.3", ["事件资产映射"]),
    ("7.1.1", ["本期预置监测链接"]),
]

NAMED_SOURCE_BRANCHES: list[tuple[str, list[str]]] = [
    ("六类投放方式字段对照", ["投放方式字段联动"]),
    ("七、监测链接说明", ["监测链接说明"]),
]


def source_refs_of(record: dict) -> list[str]:
    """抽取需求证据坐标，保序去重。"""
    prov = record.get("provenance") or {}
    refs: list[str] = []
    raw_derived = prov.get("derived_from") or []
    if isinstance(raw_derived, str):
        raw_derived = [raw_derived]
    for ref in list(raw_derived) + [prov.get("source_section")]:
        ref = str(ref or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _alias_module_for_text(text: str) -> tuple[str | None, str | None]:
    for rule in MODULE_RULES:
        module = str(rule["module"])
        for alias in rule["aliases"]:
            if alias in text:
                return module, str(alias)
    return None, None


def _classification_text(record: dict) -> str:
    prov = record.get("provenance") or {}
    refs = source_refs_of(record)
    section_markers = [f"§{num}" for ref in refs for num in _section_numbers(ref)]
    parts = [
        str(record.get("title") or ""),
        str(prov.get("verbatim_excerpt") or ""),
        " ".join(_heading_from_source_ref(ref) for ref in refs),
        " ".join(section_markers),
    ]
    return " ".join(parts)


def _branch_classification_text(record: dict, source_refs: list[str]) -> str:
    """模块内分支只使用业务语义文本，避免 PRD 文件名污染分支判断。"""
    prov = record.get("provenance") or {}
    parts = [
        str(record.get("title") or ""),
        str(prov.get("verbatim_excerpt") or ""),
        " ".join(_heading_from_source_ref(ref) for ref in source_refs),
    ]
    return " ".join(parts)


def _section_numbers(text: str) -> list[str]:
    nums: list[str] = []
    for m in re.finditer(r"§\**\s*([0-9]+(?:\.[0-9]+)*)", text or ""):
        nums.append(m.group(1).rstrip("."))
    return nums


def _matches_section_prefix(section_num: str, prefix: str) -> bool:
    if section_num == prefix:
        return True
    return section_num.startswith(f"{prefix}.")


def _rule_reason(module: str, kind: str, token: str) -> str:
    return f"{kind}:{token} -> {module}"


def _cross_cutting_tags_for_refs(refs: list[str]) -> list[str]:
    tags: list[str] = []
    for ref in refs:
        nums = _section_numbers(ref)
        for prefix, tag in CROSS_CUTTING_SOURCE_TAGS:
            if any(_matches_section_prefix(num, prefix) for num in nums) and tag not in tags:
                tags.append(tag)
    return tags


def _module_from_cross_cutting_ref(source_ref: str, text: str) -> tuple[str | None, str | None]:
    nums = _section_numbers(source_ref)
    if any(_matches_section_prefix(num, "9") for num in nums):
        for tokens, module in FIELD_CONSTRAINT_MODULE_RULES:
            if _contains_any(text, tokens):
                return module, _rule_reason(module, "field_constraint", "/".join(tokens))
        return "全局规则与字段约束", _rule_reason("全局规则与字段约束", "section", "9")

    if any(_matches_section_prefix(num, "10") for num in nums):
        for tokens, module in PERMISSION_MODULE_RULES:
            if _contains_any(text, tokens):
                return module, _rule_reason(module, "permission", "/".join(tokens))
        return "全局规则与字段约束", _rule_reason("全局规则与字段约束", "section", "10")

    if any(_matches_section_prefix(num, "5.0") for num in nums):
        module, alias = _alias_module_for_text(text)
        if module and module != "全局规则与字段约束":
            return module, _rule_reason(module, "global_rule_alias", alias or "")
        return "全局规则与字段约束", _rule_reason("全局规则与字段约束", "section", "5.0")

    return None, None


def _business_module_for_source_refs(refs: list[str], text: str) -> tuple[str | None, str, str]:
    """按需求证据坐标优先确定业务模块。"""
    for source_ref in refs:
        if not source_ref or source_ref == "unresolved":
            continue

        for token, module in NAMED_SOURCE_MODULES:
            if token in source_ref:
                return module, "rule", _rule_reason(module, "source", token)

        module, reason = _module_from_cross_cutting_ref(source_ref, text)
        if module:
            return module, "rule", reason or _rule_reason(module, "source", source_ref)

        nums = _section_numbers(source_ref)
        for prefix, module in BATCH_CREATE_EMBEDDED_MODULES:
            if any(_matches_section_prefix(num, prefix) for num in nums):
                return module, "rule", _rule_reason(module, "source", prefix)

        for rule in MODULE_RULES:
            module = str(rule["module"])
            if module == "全局规则与字段约束":
                continue
            for prefix in rule["section_prefixes"]:
                if any(_matches_section_prefix(num, prefix) for num in nums):
                    return module, "rule", _rule_reason(module, "source", prefix)

    return None, "unresolved", "no source module rule matched"


def _business_module_for_text(text: str) -> tuple[str | None, str, str]:
    """无稳定 source_ref 时的兜底业务模块分类。"""
    module, alias = _alias_module_for_text(text)
    if module:
        return module, "rule", _rule_reason(module, "alias", alias or "")

    nums = _section_numbers(text)
    for rule in MODULE_RULES:
        module = str(rule["module"])
        for prefix in rule["section_prefixes"]:
            if any(_matches_section_prefix(num, prefix) for num in nums):
                return module, "rule", _rule_reason(module, "section", prefix)

    return None, "unresolved", "no module rule matched"


def _heading_from_source_ref(source_ref: str) -> str:
    text = source_ref.split("§", 1)[-1] if "§" in source_ref else source_ref
    text = re.sub(r"^\**\s*[0-9]+(?:\.[0-9]+)*\s*", "", text)
    text = re.sub(r"^\**\s*[一二三四五六七八九十]+[、.．]\s*", "", text)
    text = text.replace("*", "").strip(" ：:-")
    if "§" not in source_ref and " " in text:
        text = text.split(" ", 1)[-1].strip()
    return text or "通用规则"


def _branch_from_rules(text: str, rules: list[tuple[tuple[str, ...], list[str]]]) -> list[str] | None:
    for keywords, path in rules:
        if any(keyword in text for keyword in keywords):
            return path
    return None


def _canonical_branch_from_source_ref(source_ref: str) -> list[str] | None:
    for token, path in NAMED_SOURCE_BRANCHES:
        if token in source_ref:
            return path

    nums = _section_numbers(source_ref)
    for prefix, path in SOURCE_BRANCH_OVERRIDES:
        if any(_matches_section_prefix(num, prefix) for num in nums):
            return path

    heading = _heading_from_source_ref(source_ref)
    if not heading or heading == "unresolved":
        return None
    heading = heading.strip()
    if re.fullmatch(r"\d+[）).．]?", heading):
        return None
    heading = re.sub(r"^[→/\-—]\s*", "", heading).strip()
    heading = heading.replace(" / ", "/").replace("/", "")
    heading = heading.replace(" → ", " ").strip()
    heading = re.sub(r"各模块字段约束（.*?）", "字段约束", heading)
    return [heading] if heading else None


def _branch_from_source_refs(source_refs: list[str]) -> list[str] | None:
    for source_ref in source_refs:
        if not source_ref or source_ref == "unresolved":
            continue
        path = _canonical_branch_from_source_ref(source_ref)
        if path:
            return path
    return None


def _branch_path_for_module(
    module: str,
    text: str,
    source_refs: list[str],
    cross_cutting_tags: list[str],
) -> list[str]:
    if "field_constraint" in cross_cutting_tags:
        return ["字段约束"]
    if "permission" in cross_cutting_tags:
        return ["权限"]

    if module == "标题包":
        path = _branch_from_rules(text, TITLE_PACKAGE_BRANCH_RULES)
        if path:
            return path
        path = _branch_from_source_refs(source_refs)
        return path or ["通用规则"]

    path = _branch_from_source_refs(source_refs)
    if path:
        return path

    module_rules = MODULE_BRANCH_RULES.get(module)
    if module_rules:
        path = _branch_from_rules(text, module_rules)
        if path:
            return path

    path = _branch_from_rules(text, GENERIC_BRANCH_RULES)
    if path:
        return path
    return ["通用规则"]


def classify_case_for_audit(record: dict[str, Any]) -> dict[str, Any]:
    """为审查/用例树派生业务模块树坐标，不写回原 case/provenance。"""
    refs = source_refs_of(record)
    text = _classification_text(record)
    branch_text = _branch_classification_text(record, refs)
    cross_cutting_tags = _cross_cutting_tags_for_refs(refs)
    module, confidence, reason = _business_module_for_source_refs(refs, text)
    if module is None:
        module, confidence, reason = _business_module_for_text(text)
    if module is None:
        return {
            "business_module": "_review_required",
            "branch_path": ["unresolved_module"],
            "source_refs": refs,
            "classification_confidence": confidence,
            "classification_reason": reason,
            "cross_cutting_tags": cross_cutting_tags,
        }
    return {
        "business_module": module,
        "branch_path": _branch_path_for_module(module, branch_text, refs, cross_cutting_tags),
        "source_refs": refs,
        "classification_confidence": confidence,
        "classification_reason": reason,
        "cross_cutting_tags": cross_cutting_tags,
    }


def classify_case_tree_coordinates(record: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    """返回旧平台实际展示的树坐标，并保留分类器原始证据。"""
    provenance = record.get("provenance") or {}
    classification = classify_case_for_audit(
        {
            "title": record.get("title") or "",
            "provenance": provenance,
        }
    )
    module_name = classification.get("business_module") or "_review_required"
    branch_path = classification.get("branch_path") or ["通用规则"]

    source_section = str(provenance.get("source_section") or "").strip()
    if module_name == "_review_required":
        if source_section and source_section != "unresolved":
            return (
                source_section,
                [source_section],
                {
                    **classification,
                    "classification_confidence": "legacy_source_section_fallback",
                },
            )
        if not source_section:
            return (
                "未分类",
                ["未分类"],
                {
                    **classification,
                    "classification_confidence": "legacy_uncategorized_fallback",
                },
            )
        return "待分类", ["未匹配模块"], classification

    return str(module_name), [str(part) for part in branch_path], classification
