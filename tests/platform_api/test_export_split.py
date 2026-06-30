"""导出占位分流单测。"""

from __future__ import annotations

from types import SimpleNamespace

from src.platform_api.tasks.export_task import _split_cases


def _c(bucket):
    return SimpleNamespace(bucket=bucket, verdict=None, title="t")


def test_split_main_vs_clarification():
    cases = [_c("main"), _c("needs_spec"), _c("to_fix"), _c(None)]
    main, clar = _split_cases(cases)
    # needs_spec → 清单；main/to_fix/None → 主集
    assert len(clar) == 1
    assert clar[0].bucket == "needs_spec"
    assert len(main) == 3


def test_split_empty():
    main, clar = _split_cases([])
    assert main == []
    assert clar == []


def test_split_all_main():
    cases = [_c("main"), _c("to_fix"), _c(None)]
    main, clar = _split_cases(cases)
    assert len(main) == 3
    assert len(clar) == 0
