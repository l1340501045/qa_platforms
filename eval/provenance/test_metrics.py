"""溯源度量尺子单元测试"""

from metrics import (
    alignment_distribution,
    citation_precision,
    grounded_assertion_rate,
)


class _Prov:
    def __init__(self, grounding):
        self.grounding = grounding


class _Case:
    def __init__(self, grounding):
        self.provenance = _Prov(grounding)


def test_citation_precision_all_verified():
    cases = [_Case({"verified": 3, "fuzzy": 0, "relocated": 0, "unresolved": 0})]
    assert citation_precision(cases) == 1.0


def test_citation_precision_mixed():
    cases = [_Case({"verified": 2, "fuzzy": 1, "relocated": 0, "unresolved": 1})]
    assert abs(citation_precision(cases) - 0.75) < 1e-9


def test_citation_precision_all_unresolved():
    cases = [_Case({"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 3})]
    assert citation_precision(cases) == 0.0


def test_alignment_distribution():
    cases = [_Case({"verified": 4, "fuzzy": 2, "relocated": 2, "unresolved": 2})]
    dist = alignment_distribution(cases)
    assert abs(dist["verified"] - 0.4) < 1e-9
    assert abs(dist["unresolved"] - 0.2) < 1e-9


def test_grounded_assertion_rate():
    cases = [
        _Case({"verified": 2, "fuzzy": 0, "relocated": 0, "unresolved": 0}),
        _Case({"verified": 0, "fuzzy": 0, "relocated": 0, "unresolved": 2}),
    ]
    assert abs(grounded_assertion_rate(cases) - 0.5) < 1e-9


if __name__ == "__main__":
    test_citation_precision_all_verified()
    test_citation_precision_mixed()
    test_citation_precision_all_unresolved()
    test_alignment_distribution()
    test_grounded_assertion_rate()
    print("all passed")
