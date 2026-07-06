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
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np

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
    # 规则锚点码（如 ["R-001", ...]），仅在用例所属测试点带 rule_id 时有值；
    # 维度增强测试点的用例为空。safe_dedup 护栏据此判断是否可折叠（绝不删某规则
    # 最后一条非重复用例）。dedup_node 经 case.test_point_id → tp.rule_id 回填。
    rule_codes: list[str] = field(default_factory=list)


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
    cross_dim_threshold: float = 0.84,
    min_shared_bigrams: int = 4,
    safe_dedup_enabled: bool = False,
    embeddings: dict[str, list[float]] | None = None,
    semantic_threshold: float = 0.86,
    semantic_cross_tp_threshold: float = 0.90,
) -> dict[str, str]:
    """返回 {duplicate_case_id: canonical_case_id}。

    canonical 取每个近重复簇中最先出现（输入顺序）的用例；其余标为其重复。

    safe_dedup_enabled：开规则锚定护栏 —— 折叠会让某条规则失去其最后一条非重复
    用例时，跳过该折叠。关时退回旧行为（无护栏）。维度增强用例（无 rule_codes）
    不进入护栏检查，按旧行为折叠。

    embeddings：case_id → 向量。提供时在词面候选外**额外**生成语义候选（全局两两
    cosine）：同 feature_id 用 semantic_threshold、跨 feature_id 用更严的
    semantic_cross_tp_threshold，超阈值且非 _protected 的对过 _union（含 safe_dedup
    护栏，自动复用）。不提供（None）/某 case 缺向量 → 该 case 不参与语义候选，行为
    与改造前一致。向量外部算好传入，本函数保持纯同步可离线单测。
    """
    order = {c.case_id: i for i, c in enumerate(cases)}
    parent: dict[str, str] = {c.case_id: c.case_id for c in cases}
    rule_codes_of = {c.case_id: list(c.rule_codes or []) for c in cases}

    # 「当前 alive canonical 数」per 规则码：cases 中以自己为根（dup_map 出去时不会
    # 被列为 duplicate）的、覆盖该规则的用例数。每次成功的 union 会让一个 root 沉
    # 为 child（变成 duplicate），相应 live_cnt 递减。初值 = 总覆盖数（全 alive）。
    live_cnt: dict[str, int] = defaultdict(int)
    for c in cases:
        for r in rule_codes_of[c.case_id]:
            live_cnt[r] += 1

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        # 决定败者根（沉为 child → 成为 duplicate）
        loser = rb if order[ra] <= order[rb] else ra
        # 规则锚定护栏：若 loser 是某规则的最后一条 alive canonical，跳过本次折叠
        if safe_dedup_enabled:
            for r in rule_codes_of.get(loser, ()):
                if live_cnt.get(r, 0) <= 1:
                    return
        if order[ra] <= order[rb]:
            parent[rb] = ra
        else:
            parent[ra] = rb
        # 更新 live_cnt：loser 不再是 canonical（变成 duplicate）
        for r in rule_codes_of.get(loser, ()):
            if live_cnt.get(r, 0) > 0:
                live_cnt[r] -= 1

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
    dim_of = {c.case_id: (c.dimension or "").strip() for c in cases}
    feature_of = {c.case_id: c.feature_id or "" for c in cases}

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
        # 跨测试点/功能点的「同维度」近等价多为换皮重复(同一权限矩阵/校验在多处重复断言)，
        # 用更低阈值折叠(根因2b：兜底功能点被切散后残留的跨 feature 重复)；跨维度保持严
        # 阈值，避免不同维度的偶然相似被误并。不同边界值用例已被 _protected 排除。
        da, db = dim_of[a], dim_of[b]
        threshold = cross_dim_threshold if (da and da == db) else sim_threshold
        if ratio >= threshold:
            _union(a, b)

    # ── 3) 语义近重复（全局两两 cosine，抓词面抓不到的换措辞同义）──
    # embeddings 为 None → 整段跳过，行为与改造前逐字节一致。向量外部算好传入，
    # 本函数仍纯同步可离线单测。灌水大头是跨 test_point/跨模块的换措辞重复，故语义
    # 候选须全局（非仅组内）。numpy 矩阵化算 cosine，禁止纯 python 双循环（n²×D 太慢）。
    if embeddings:
        # 按输入顺序收集有向量的 case（缺向量者跳过，不参与语义候选）
        v_ids = [c.case_id for c in cases if c.case_id in embeddings]
        if len(v_ids) >= 2:
            mat = np.array([embeddings[cid] for cid in v_ids], dtype=np.float64)
            # L2 归一化后矩阵内积 = cosine；零向量行归一化后为 0，不会误连
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat_n = mat / norms
            sim = mat_n @ mat_n.T
            n = len(v_ids)
            for i in range(n):
                for j in range(i + 1, n):
                    s = float(sim[i, j])
                    if s < semantic_threshold:
                        continue
                    a, b = v_ids[i], v_ids[j]
                    if _find(a) == _find(b):
                        continue
                    if _protected(a, b):
                        continue
                    # 跨 feature_id 用更严阈值（仿词面"跨维严/同维松"控误折叠）。
                    # same_tp 必须基于当前对 (a,b) 自身判定，禁止引用循环外变量。
                    same_tp = bool(feature_of[a]) and feature_of[a] == feature_of[b]
                    thr = semantic_threshold if same_tp else semantic_cross_tp_threshold
                    if s >= thr:
                        _union(a, b)

    # ── 输出 ──
    dup_map: dict[str, str] = {}
    for c in cases:
        root = _find(c.case_id)
        if root != c.case_id:
            dup_map[c.case_id] = root
    return dup_map
