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

import logging
import re
from dataclasses import dataclass

from src.knowledge_base.services.embedding.embedding_client import EmbeddingClient
from src.platform_api.core.settings import settings

logger = logging.getLogger(__name__)

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


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class CrossFeatureIndex:
    """全 PRD spec 章节索引；按测试点描述检索跨功能点参考章节。

    关键词路（词项重叠）始终可用；开启 settings.hybrid_cross_retrieval_enabled 时叠加
    向量路（候选 content embedding + cosine），RRF 融合，补召回语义相近但用词不同的章节。
    embedding 不可用时自动降级为纯关键词，绝不阻断生成。
    """

    def __init__(self, parsed_context) -> None:
        self._candidates: list[_Candidate] = []
        for source in parsed_context.sources:
            if source.trust_level > 2:
                continue
            for section in source.sections:
                kind = getattr(section, "section_kind", "spec")
                if kind not in ("spec", "summary"):
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
        self._cand_vectors: list[list[float]] | None = None

    @classmethod
    async def build(cls, parsed_context) -> "CrossFeatureIndex":
        """工厂：建关键词候选；开启 hybrid 时再异步算候选向量（失败自动降级）。"""
        self = cls(parsed_context)
        if settings.hybrid_cross_retrieval_enabled and self._candidates:
            await self._ensure_embeddings()
        return self

    async def _ensure_embeddings(self) -> None:
        try:
            texts = [(c.heading or "") + "\n" + (c.content or "") for c in self._candidates]
            vectors = await EmbeddingClient().embed_batch(texts)
            if len(vectors) == len(self._candidates):
                self._cand_vectors = vectors
            else:
                logger.warning(
                    "hybrid cross-retrieval: 候选向量数(%d)≠候选数(%d)，降级纯关键词",
                    len(vectors), len(self._candidates),
                )
                self._cand_vectors = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("hybrid cross-retrieval: 候选 embedding 失败，降级纯关键词: %s", exc)
            self._cand_vectors = None

    def _keyword_ranked(
        self, query_text: str, exclude_keys: set[tuple[str, str]], min_score: int
    ) -> list[_Candidate]:
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
        return [cand for _score, cand in scored]

    def _vector_ranked(
        self, q_vec: list[float], exclude_keys: set[tuple[str, str]], pool: int
    ) -> list[_Candidate]:
        scored: list[tuple[float, _Candidate]] = []
        for cand, vec in zip(self._candidates, self._cand_vectors or []):
            if cand.key in exclude_keys:
                continue
            scored.append((_cosine(q_vec, vec), cand))
        scored.sort(key=lambda t: (-t[0], t[1].source_ref))
        return [cand for _s, cand in scored[:pool]]

    def _to_sections(self, cands: list[_Candidate]) -> list[GlobalSection]:
        return [
            GlobalSection(
                source_title=c.source_title,
                trust_level=c.trust_level,
                section_kind=c.section_kind,
                source_ref=c.source_ref,
                heading=c.heading,
                content=c.content,
            )
            for c in cands
        ]

    async def query(
        self,
        query_text: str,
        exclude_keys: set[tuple[str, str]],
        *,
        top_k: int = 3,
        min_score: int = _CROSS_MIN_SCORE,
    ) -> list[GlobalSection]:
        """关键词召回；hybrid 开启且向量就绪时叠加向量召回 + RRF 融合，返回 top_k。"""
        kw_ranked = self._keyword_ranked(query_text, exclude_keys, min_score)

        if not (settings.hybrid_cross_retrieval_enabled and self._cand_vectors):
            return self._to_sections(kw_ranked[:top_k])

        try:
            q_vec = await EmbeddingClient().embed_single(query_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hybrid cross-retrieval: query embedding 失败，降级纯关键词: %s", exc)
            return self._to_sections(kw_ranked[:top_k])

        if not q_vec:
            return self._to_sections(kw_ranked[:top_k])

        vec_ranked = self._vector_ranked(q_vec, exclude_keys, pool=max(top_k * 4, 12))

        k = settings.hybrid_cross_rrf_k
        scores: dict[tuple[str, str], float] = {}
        cand_by_key: dict[tuple[str, str], _Candidate] = {}
        for rank, cand in enumerate(kw_ranked):
            scores[cand.key] = scores.get(cand.key, 0.0) + 1.0 / (k + rank + 1)
            cand_by_key[cand.key] = cand
        for rank, cand in enumerate(vec_ranked):
            scores[cand.key] = scores.get(cand.key, 0.0) + 1.0 / (k + rank + 1)
            cand_by_key[cand.key] = cand

        fused = sorted(scores, key=lambda key: (-scores[key], cand_by_key[key].source_ref))
        return self._to_sections([cand_by_key[key] for key in fused[:top_k]])


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
