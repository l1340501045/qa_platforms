"""近重复聚类 — 确定性文本相似（归一化签名 + bigram 倒排分块 + difflib）。

不依赖外部 embedding 服务，可复现、可离线验证。跨功能点的近重复（如权限模块在
多个功能点重复出现）也能抓到，因为聚类在全量用例上做、不按 feature 切。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

# 归一化：保留中日韩与字母，去数字/标点/空白（数字差异不构成实质不同）
_KEEP = re.compile(r"[\u4e00-\u9fffa-zA-Z]+")


@dataclass
class DedupCase:
    case_id: str
    feature_id: str
    title: str
    text: str = ""  # 可附加 expected_results 拼接，增强判别


def _normalize(s: str) -> str:
    return "".join(_KEEP.findall((s or "").lower()))


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def find_duplicates(
    cases: list[DedupCase],
    *,
    sim_threshold: float = 0.88,
    min_shared_bigrams: int = 4,
) -> dict[str, str]:
    """返回 {duplicate_case_id: canonical_case_id}。

    canonical 取每个近重复簇中最先出现（输入顺序）的用例；其余标为其重复。
    分块：按归一化标题的 bigram 倒排找候选对，仅对候选对算 difflib 比率，避免 O(n^2)。
    """
    norm = {c.case_id: _normalize(c.title + c.text) for c in cases}
    norm_title = {c.case_id: _normalize(c.title) for c in cases}
    order = {c.case_id: i for i, c in enumerate(cases)}

    # 1) bigram 倒排索引（基于归一化标题）
    inverted: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        for bg in _bigrams(norm_title[c.case_id]):
            inverted[bg].append(c.case_id)

    # 2) 候选对：共享 bigram 数 >= 阈值
    pair_shared: dict[tuple[str, str], int] = defaultdict(int)
    for ids in inverted.values():
        if len(ids) < 2 or len(ids) > 200:  # 跳过超热 bigram，控量
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                key = (a, b) if order[a] < order[b] else (b, a)
                pair_shared[key] += 1

    # 3) 候选对算相似度，超阈值则连边（union-find）
    parent: dict[str, str] = {c.case_id: c.case_id for c in cases}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        # canonical = 输入顺序更靠前者
        if order[ra] <= order[rb]:
            parent[rb] = ra
        else:
            parent[ra] = rb

    for (a, b), shared in pair_shared.items():
        if shared < min_shared_bigrams:
            continue
        ratio = SequenceMatcher(None, norm[a], norm[b]).ratio()
        if ratio >= sim_threshold:
            _union(a, b)

    # 4) 输出：非自身根的用例标为重复
    dup_map: dict[str, str] = {}
    for c in cases:
        root = _find(c.case_id)
        if root != c.case_id:
            dup_map[c.case_id] = root
    return dup_map
