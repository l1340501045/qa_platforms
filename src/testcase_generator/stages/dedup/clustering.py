"""近重复聚类 — 结构化折叠 + 确定性文本相似（归一化签名 + bigram 倒排分块 + difflib）。

两类去重，互补：
1) 结构化折叠（按 test_point 分组）：
   - 同一测试点下「需求待确认占位用例」与「确定断言用例」并存 → 占位是冗余，标为断言版的重复；
   - 同一测试点下多条占位用例 → 仅留其一。
   词面相似抓不到这种孪生（标题差异大），但它正是"虚胖"的主要来源。
2) 词面近重复（全量、跨功能点）：归一化标题/正文 bigram 倒排找候选对，difflib 比率超阈值连边。
   - 纯枚举等价选项（如"切换每页10/50/100条"）**仍折叠**——边际价值低的虚胖。
   - **边界值保护**：候选对数字集不同 **且** 含边界语义关键词（恰好/上限/超出/最大/为空…）时
     **不合并**——避免把"1000行" vs "999行"、"恰好等于每页"等不同边界值的有效用例误标重复（修审计 W05）。

不依赖外部 embedding，可复现、可离线验证。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

# 归一化：保留中日韩与字母，去数字/标点/空白（数字差异交由 _numset 单独保护）
_KEEP = re.compile(r"[\u4e00-\u9fffa-zA-Z]+")
_NUM = re.compile(r"\d+(?:\.\d+)?")
# 边界语义关键词：出现时若数字不同则保护（不折叠），避免误删不同边界值用例
_BOUNDARY_KW = re.compile(
    r"恰好|刚好|边界|临界|上限|下限|超出|超过|不超过|至多|至少|最大|最小|超长|超量|"
    r"为空|空态|空值|溢出|越界|等于|第一|首条|末条|最后|最末|起始|结尾"
)


@dataclass
class DedupCase:
    case_id: str
    feature_id: str  # 此处复用为 test_point_id（节点传入），结构化折叠按它分组
    title: str
    text: str = ""  # 附加 expected_results 拼接，增强判别
    is_placeholder: bool = False  # 是否「需求待确认」占位用例
    dimension: str = ""  # 覆盖维度（同测试点+同维度的近等价断言更激进折叠）


def _normalize(s: str) -> str:
    return "".join(_KEEP.findall((s or "").lower()))


def _numset(s: str) -> frozenset[str]:
    """提取文本中的数字（含小数），作为边界/枚举变体的判别。"""
    return frozenset(_NUM.findall(s or ""))


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def find_duplicates(
    cases: list[DedupCase],
    *,
    sim_threshold: float = 0.88,
    intra_dim_threshold: float = 0.80,
    min_shared_bigrams: int = 4,
) -> dict[str, str]:
    """返回 {duplicate_case_id: canonical_case_id}。

    canonical 取每个近重复簇中最先出现（输入顺序）的用例；其余标为其重复。
    """
    order = {c.case_id: i for i, c in enumerate(cases)}
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
        if order[ra] <= order[rb]:
            parent[rb] = ra
        else:
            parent[ra] = rb

    # ── 1) 结构化折叠：按 test_point 分组处理占位 vs 断言 ──
    by_tp: dict[str, list[DedupCase]] = defaultdict(list)
    for c in cases:
        if c.feature_id:
            by_tp[c.feature_id].append(c)
    for tp_id, group in by_tp.items():
        if len(group) < 2:
            continue
        assertions = [c for c in group if not c.is_placeholder]
        placeholders = [c for c in group if c.is_placeholder]
        if assertions and placeholders:
            # 有确定断言时，占位用例冗余 → 全部并入首个断言
            canonical = min(assertions, key=lambda c: order[c.case_id])
            for ph in placeholders:
                _union(canonical.case_id, ph.case_id)
        elif len(placeholders) >= 2:
            # 全是占位 → 仅留其一
            canonical = min(placeholders, key=lambda c: order[c.case_id])
            for ph in placeholders:
                if ph.case_id != canonical.case_id:
                    _union(canonical.case_id, ph.case_id)

    # 文本签名（两个词面 pass 共用）
    norm = {c.case_id: _normalize(c.title + c.text) for c in cases}
    norm_title = {c.case_id: _normalize(c.title) for c in cases}
    nums = {c.case_id: _numset(c.title + c.text) for c in cases}
    raw = {c.case_id: (c.title or "") + (c.text or "") for c in cases}

    def _protected(a: str, b: str) -> bool:
        """边界值保护：数字集不同且任一方含边界语义关键词 → 不同边界值的有效用例，不合并。"""
        return nums[a] != nums[b] and bool(_BOUNDARY_KW.search(raw[a]) or _BOUNDARY_KW.search(raw[b]))

    # ── 1.5) 同测试点 + 同维度 的近等价断言折叠（更激进，治"冗余虚胖"主因）──
    # 同一测试点下、同一覆盖维度的多条**确定断言**用例，若措辞高度相似（阈值更低 0.80），
    # 多为换皮重复（权限矩阵换名、同一校验换措辞），折叠保留其一；占位用例与边界值用例除外。
    by_tp_dim: dict[tuple[str, str], list[DedupCase]] = defaultdict(list)
    for c in cases:
        if c.feature_id and not c.is_placeholder:
            by_tp_dim[(c.feature_id, (c.dimension or "").strip())].append(c)
    for group in by_tp_dim.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i].case_id, group[j].case_id
                if _find(a) == _find(b) or _protected(a, b):
                    continue
                if SequenceMatcher(None, norm[a], norm[b]).ratio() >= intra_dim_threshold:
                    _union(a, b)

    # ── 2) 词面近重复（带数字差异保护）──
    inverted: dict[str, list[str]] = defaultdict(list)
    for c in cases:
        for bg in _bigrams(norm_title[c.case_id]):
            inverted[bg].append(c.case_id)

    pair_shared: dict[tuple[str, str], int] = defaultdict(int)
    for ids in inverted.values():
        if len(ids) < 2 or len(ids) > 200:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                key = (a, b) if order[a] < order[b] else (b, a)
                pair_shared[key] += 1

    for (a, b), shared in pair_shared.items():
        if shared < min_shared_bigrams:
            continue
        # 边界值保护：数字集不同 且 任一方含边界语义关键词 → 不同边界值的有效用例，保留两者
        if _protected(a, b):
            continue
        ratio = SequenceMatcher(None, norm[a], norm[b]).ratio()
        if ratio >= sim_threshold:
            _union(a, b)

    # ── 输出 ──
    dup_map: dict[str, str] = {}
    for c in cases:
        root = _find(c.case_id)
        if root != c.case_id:
            dup_map[c.case_id] = root
    return dup_map
