"""跨功能点「全局/常驻章节」识别与收集 —— write_cases 与 verify 共用。

根因修复：PRD 里像「§5.0 全局说明 / §6 投放方式 / §7 监测链接 / §9 字段约束汇总 /
字数算法 / 错误码」这类章节定义的是**适用于所有功能点**的全局规则，但在文档里只挂在
某个章节号下。按 source_ref 匹配时，这些章节只会被分配给恰好引用它的那一个功能点
（如 §5.0 只给到 F-002），导致其它功能点在 write_cases/verify 时看不到这些规则，
进而把「分页/排序/筛选/默认时间降序」等**已被 §5.0 明文定义**的行为误判为
needs_spec（ungrounded），或在留白处反向编造断言。

本模块用标题关键字启发式识别全局章节，确保它们被注入每一个功能点的上下文。
关键字可扩展；后续可改为由 parse 阶段的 section_classifier 显式标记 global 性质。
"""

from __future__ import annotations

from dataclasses import dataclass

# 跨功能点常驻章节的标题关键字（命中即视为全局规则，注入所有功能点）。
# 既含通用 QA-PRD 术语（全局/通用/字段约束/错误码/校验规则/字数），
# 也含本 PRD 的横切章节（投放方式/监测链接）。
GLOBAL_HEADING_KEYWORDS: tuple[str, ...] = (
    "全局",
    "通用",
    "公共",
    "字段约束",
    "字段说明",
    "约束汇总",
    "字数",
    "错误码",
    "校验规则",
    "投放方式",
    "监测链接",
    "公式",
)


def is_global_section(heading: str | None, source_ref: str | None = None) -> bool:
    """标题命中全局关键字则视为跨功能点常驻章节。"""
    h = heading or ""
    return any(kw in h for kw in GLOBAL_HEADING_KEYWORDS)


@dataclass(frozen=True)
class GlobalSection:
    """归一化的全局章节（供两个阶段各自映射到自己的上下文结构）。"""

    source_title: str
    trust_level: int
    section_kind: str
    source_ref: str
    heading: str
    content: str


def collect_global_sections(parsed_context) -> list[GlobalSection]:
    """从 parsed_context 收集所有全局/常驻章节（仅取 PRD/技术文档，trust_level<=2）。

    去重键 = (source_ref, heading)，避免同一章节重复注入。
    """
    seen: set[tuple[str, str]] = set()
    out: list[GlobalSection] = []
    for source in parsed_context.sources:
        if source.trust_level > 2:  # 仅 PRD / 技术文档作为全局规则来源
            continue
        for section in source.sections:
            if not is_global_section(section.heading, section.source_ref):
                continue
            key = (section.source_ref or "", section.heading or "")
            if key in seen:
                continue
            seen.add(key)
            out.append(
                GlobalSection(
                    source_title=source.title,
                    trust_level=source.trust_level,
                    section_kind=getattr(section, "section_kind", "spec"),
                    source_ref=section.source_ref,
                    heading=section.heading,
                    content=section.content,
                )
            )
    return out
