"""检索指标纯函数：recall@k / ndcg@k / mrr。relevant 为空时返回 None（负样本不计入这些均值）。"""
from __future__ import annotations

import math


def recall_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    hit = sum(1 for key in ranked_keys[:k] if key in relevant)
    return hit / len(relevant)


def ndcg_at_k(ranked_keys: list[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    dcg = sum(1.0 / math.log2(i + 2) for i, key in enumerate(ranked_keys[:k]) if key in relevant)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg if idcg else 0.0


def mrr(ranked_keys: list[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for i, key in enumerate(ranked_keys):
        if key in relevant:
            return 1.0 / (i + 1)
    return 0.0
