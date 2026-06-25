"""T027: provenance 标注 — 为每条用例标注溯源信息"""

from __future__ import annotations

import re

from src.testcase_generator.schemas.parsed_context import FeatureItem, ParsedContext
from src.testcase_generator.schemas.test_case import Provenance
from src.testcase_generator.schemas.test_point import TestPointSchema

# ── 溯源接地：归一化 + span 对齐（落点⑥）────────────────────────────────────────

_KEEP = re.compile(r"[^0-9a-z一-鿿]+")


def _normalize(s: str) -> str:
    """比对用归一化：全角→半角、小写、仅保留中文+字母数字（标点/空白一律去掉）。"""
    if not s:
        return ""
    s = "".join(chr(ord(c) - 0xFEE0) if "！" <= c <= "～" else c for c in s)
    return _KEEP.sub("", s.lower())


def _bigrams(norm: str) -> set[str]:
    return {norm[i : i + 2] for i in range(len(norm) - 1)} if len(norm) >= 2 else ({norm} if norm else set())


def _align(quote: str, section_content: str, *, threshold: float = 0.8) -> str:
    """'verified'（归一化子串）/ 'fuzzy'（quote bigram 被章节覆盖≥阈值）/ 'unresolved'。"""
    nq, nc = _normalize(quote), _normalize(section_content)
    if not nq:
        return "unresolved"
    if nq in nc:
        return "verified"
    bq, bc = _bigrams(nq), _bigrams(nc)
    if not bq:
        return "unresolved"
    coverage = len(bq & bc) / len(bq)
    return "fuzzy" if coverage >= threshold else "unresolved"


def _relocate(quote: str, expected: str, section_content: str | None) -> str | None:
    """章节内找与 quote/expected 最相似的句子作兜底（修复定位）。"""
    from difflib import SequenceMatcher

    if not section_content:
        return None
    target = _normalize(quote or expected)
    if not target:
        return None
    best, best_sent = 0.0, None
    for sent in re.split(r"[。；;\n]", section_content):
        s = sent.strip()
        if not s:
            continue
        r = SequenceMatcher(None, target, _normalize(s)).ratio()
        if r > best:
            best, best_sent = r, s
    return best_sent if best >= 0.6 else None


def derive_grounded_provenance(llm_case, parsed_context) -> Provenance:
    """从 step 级 source_quote/source_ref 派生用例级溯源 + 三查校验（绑定/对齐/修复）。"""
    index: dict[str, tuple[str, int]] = {}
    for src in parsed_context.sources:
        for sec in src.sections:
            index[_normalize(sec.source_ref)] = (sec.content, src.trust_level)

    counts = {"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 0}
    quotes: list[str] = []
    refs: list[str] = []
    trusts: list[int] = []

    for step in llm_case.steps:
        q = (getattr(step, "source_quote", None) or "").strip()
        r = (getattr(step, "source_ref", None) or "").strip()
        if not q:
            continue
        sec = index.get(_normalize(r)) if r else None
        status = _align(q, sec[0]) if sec else "unresolved"
        if status in ("verified", "fuzzy"):
            counts[status] += 1
            quotes.append(q)
            if r:
                refs.append(r)
            if sec:
                trusts.append(sec[1])
        else:
            fixed = _relocate(q, getattr(step, "expected_result", ""), sec[0] if sec else None)
            if fixed:
                counts["relocated"] += 1
                quotes.append(fixed)
                if r:
                    refs.append(r)
                if sec:
                    trusts.append(sec[1])
            else:
                counts["unresolved"] += 1

    derived_from = list(dict.fromkeys(refs))
    if quotes:
        excerpt = " / ".join(quotes)[:300]
    else:
        excerpt = f"[未能对齐原文：{counts['unresolved']} 处引文存疑，待人工核对]"
    trust_level = min(trusts) if trusts else (
        min((s.trust_level for s in parsed_context.sources), default=5)
    )
    return Provenance(
        derived_from=derived_from or ["unresolved"],
        source_section=derived_from[0] if derived_from else "unresolved",
        verbatim_excerpt=excerpt,
        trust_level=trust_level,
        grounding=counts,
    )


class ProvenanceTagger:
    """为每条用例标注溯源信息 — 审计的命根（硬约束#3）

    必须包含：
    - derived_from: 来源文档引用列表
    - source_section: 具体章节标识
    - verbatim_excerpt: 原文摘录
    - trust_level: 最低信源等级（多源取最低）
    """

    def tag_provenance(
        self,
        test_point: TestPointSchema,
        parsed_context: ParsedContext,
    ) -> Provenance:
        """标注每条用例的信息来源

        根据 test_point.derived_from 和 feature_id 在 parsed_context 中
        定位原始章节，提取溯源信息。
        """
        feature = self._find_feature(test_point.feature_id, parsed_context)
        source_refs = test_point.derived_from or (feature.source_refs if feature else [])

        # 提取 verbatim_excerpt：从匹配的 sections 中取第一段内容
        excerpt = ""
        source_section = ""
        trust_levels: list[int] = []

        for source in parsed_context.sources:
            for section in source.sections:
                if section.source_ref in source_refs or self._section_matches(section, test_point, feature):
                    if not excerpt:
                        excerpt = section.content[:200]
                        source_section = section.source_ref
                    trust_levels.append(source.trust_level)

        # 兜底：如果找不到精确匹配，使用 feature 级别信息
        if not excerpt and feature:
            excerpt = feature.description[:200]
            source_section = feature.source_refs[0] if feature.source_refs else "unknown"

        if not trust_levels:
            # 取所有信源中最高信任等级（数字最小）
            trust_levels = [s.trust_level for s in parsed_context.sources] or [5]

        # 硬约束#5: 不同级取高（数字小的优先级高）
        final_trust_level = min(trust_levels)

        return Provenance(
            derived_from=source_refs or ["unresolved"],
            source_section=source_section or "unresolved",
            verbatim_excerpt=excerpt or "[无法定位原文]",
            trust_level=final_trust_level,
        )

    def _find_feature(self, feature_id: str, parsed_context: ParsedContext) -> FeatureItem | None:
        """在 parsed_context.features 中查找匹配 feature"""
        for f in parsed_context.features:
            if f.id == feature_id:
                return f
            for sub in f.sub_features:
                if sub.id == feature_id:
                    return sub
        return None

    def _section_matches(self, section, test_point: TestPointSchema, feature: FeatureItem | None) -> bool:
        """检查 section 是否与当前测试点相关"""
        if feature and feature.name.lower() in section.heading.lower():
            return True
        if test_point.dimension in section.content.lower():
            return True
        return False
