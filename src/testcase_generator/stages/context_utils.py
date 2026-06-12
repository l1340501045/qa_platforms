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

import re
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


# ── 跨功能点规格检索（治"假阴性空壳"根因 A2）─────────────────────────────────
#
# 深层子节在 parse 阶段被折进各自父功能段（feature↔section 近似 1:1）。当 F-023 的
# 某测试点行为其实定义在 §5.9.3（折进 F-024 段）时，F-023 的上下文里看不到该规格，
# 模型遂误判"PRD 未定义"→ 产出无 oracle 空壳（5b 复审 W11/W14/W17）。
# 本检索按测试点描述与全 PRD spec 章节的确定性词项重叠打分，为每个功能点补注 top-K
# 跨功能点 spec 章节，把"被折到别处的规格"找回来。纯词项重叠、可复现、可离线验证。

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{2,}")
_CROSS_MIN_SCORE = 6  # 命中的判别性词项数下限（低于此视为噪声，不注入）


def _salient_terms(text: str) -> set[str]:
    """抽取判别性词项：CJK 3-gram + 长度≥3 的 ascii 词，降低常见 2-gram 噪声。"""
    terms: set[str] = set()
    s = (text or "").lower()
    for run in _CJK.findall(s):
        if len(run) >= 3:
            for i in range(len(run) - 2):
                terms.add(run[i : i + 3])
        elif len(run) == 2:
            terms.add(run)
    for w in _ASCII_WORD.findall(s):
        terms.add(w)
    return terms


@dataclass(frozen=True)
class _Candidate:
    key: tuple[str, str]
    source_title: str
    trust_level: int
    section_kind: str
    source_ref: str
    heading: str
    content: str
    terms: frozenset[str]


class CrossFeatureIndex:
    """全 PRD spec 章节的词项索引；按测试点描述检索跨功能点参考章节。"""

    def __init__(self, parsed_context) -> None:
        self._candidates: list[_Candidate] = []
        for source in parsed_context.sources:
            if source.trust_level > 2:  # 仅 PRD / 技术文档作为规格来源
                continue
            for section in source.sections:
                kind = getattr(section, "section_kind", "spec")
                if kind not in ("spec", "summary"):  # 只检索可作 oracle 依据的章节
                    continue
                key = (section.source_ref or "", section.heading or "")
                terms = _salient_terms((section.heading or "") + "\n" + (section.content or ""))
                if not terms:
                    continue
                self._candidates.append(
                    _Candidate(
                        key=key,
                        source_title=source.title,
                        trust_level=source.trust_level,
                        section_kind=kind,
                        source_ref=section.source_ref,
                        heading=section.heading,
                        content=section.content,
                        terms=frozenset(terms),
                    )
                )

    def query(
        self,
        query_text: str,
        exclude_keys: set[tuple[str, str]],
        *,
        top_k: int = 3,
        min_score: int = _CROSS_MIN_SCORE,
    ) -> list[GlobalSection]:
        """返回与 query_text 词项重叠最高、且不在 exclude_keys 中的 top_k 跨功能点章节。"""
        q = _salient_terms(query_text)
        if not q:
            return []
        scored: list[tuple[int, _Candidate]] = []
        for cand in self._candidates:
            if cand.key in exclude_keys:
                continue
            score = len(q & cand.terms)
            if score >= min_score:
                scored.append((score, cand))
        scored.sort(key=lambda t: (-t[0], t[1].source_ref))
        out: list[GlobalSection] = []
        for _score, cand in scored[:top_k]:
            out.append(
                GlobalSection(
                    source_title=cand.source_title,
                    trust_level=cand.trust_level,
                    section_kind=cand.section_kind,
                    source_ref=cand.source_ref,
                    heading=cand.heading,
                    content=cand.content,
                )
            )
        return out


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
