"""溯源度量尺子：citation precision / alignment distribution / grounded assertion rate"""

from __future__ import annotations


def citation_precision(cases: list) -> float:
    """(verified+fuzzy+relocated) 步 / 有 source_quote 步。cases 为含 provenance.grounding 的用例列表。"""
    total_quoted = 0
    total_grounded = 0
    for case in cases:
        g = getattr(getattr(case, "provenance", None), "grounding", None)
        if not g:
            continue
        quoted = g.get("verified", 0) + g.get("fuzzy", 0) + g.get("relocated", 0) + g.get("unresolved", 0)
        grounded = g.get("verified", 0) + g.get("fuzzy", 0) + g.get("relocated", 0)
        total_quoted += quoted
        total_grounded += grounded
    return total_grounded / total_quoted if total_quoted > 0 else 0.0


def alignment_distribution(cases: list) -> dict[str, float]:
    """{verified, fuzzy, relocated, unresolved} 占比。"""
    totals = {"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 0}
    for case in cases:
        g = getattr(getattr(case, "provenance", None), "grounding", None)
        if not g:
            continue
        for k in totals:
            totals[k] += g.get(k, 0)
    s = sum(totals.values())
    if s == 0:
        return {k: 0.0 for k in totals}
    return {k: v / s for k, v in totals.items()}


def grounded_assertion_rate(cases: list) -> float:
    """含有效 quote 的确定断言用例 / 确定断言用例（排除 unresolved-only 的用例）。"""
    total_definite = 0
    total_grounded = 0
    for case in cases:
        g = getattr(getattr(case, "provenance", None), "grounding", None)
        if not g:
            continue
        has_any_quote = sum(g.values()) > 0
        if not has_any_quote:
            continue
        total_definite += 1
        if g.get("verified", 0) + g.get("fuzzy", 0) + g.get("relocated", 0) > 0:
            total_grounded += 1
    return total_grounded / total_definite if total_definite > 0 else 0.0
