"""导出分流单测：三桶分流（main/needs_spec/to_fix）+ 需求澄清/待修正清单生成。"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from src.platform_api.tasks.export_task import (
    _generate_csv_fallback,
    _generate_excel,
    _generate_markdown,
    _split_cases,
)


def _c(bucket, *, verdict=None, title="t", verification=None):
    """轻量 mock（仅供分流测试，无需完整字段）。"""
    return SimpleNamespace(bucket=bucket, verdict=verdict, title=title, verification=verification)


def _full_case(bucket, **kw):
    """字段齐全的 mock 用例（供 markdown/excel/csv 生成测试）。"""
    base = dict(
        title="标题",
        priority="P1",
        trust_level=3,
        preconditions=["已登录"],
        steps=[{"action": "点击", "input_data": "x", "expected_result": "ok"}],
        expected_results=["成功"],
        dimensions=["functional_correctness"],
        bucket=bucket,
        verdict=None,
        verification=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── 三桶分流 ──────────────────────────────────────────────────────────────


def test_split_three_buckets():
    cases = [_c("main"), _c("needs_spec"), _c("to_fix"), _c(None)]
    main, clar, to_fix = _split_cases(cases)
    # grounded/unverified(main) 与旧数据(None) → 主集；needs_spec/to_fix 各自分出
    assert [x.bucket for x in main] == ["main", None]
    assert [x.bucket for x in clar] == ["needs_spec"]
    assert [x.bucket for x in to_fix] == ["to_fix"]


def test_split_empty():
    main, clar, to_fix = _split_cases([])
    assert main == [] and clar == [] and to_fix == []


def test_split_all_main_when_no_verify():
    """旧批次 bucket 全 None → 全归主集（向后兼容，行为不变）。"""
    main, clar, to_fix = _split_cases([_c(None), _c(None)])
    assert len(main) == 2 and clar == [] and to_fix == []


# ── markdown 生成：两段 + 表格转义 ──────────────────────────────────────────


def test_markdown_has_clarification_and_fix_sections():
    main = [_full_case("main")]
    clar = [
        _full_case("needs_spec", verdict="undefined", verification={"rationale": "PRD未定义", "prd_evidence": "§5.1"})
    ]
    fix = [
        _full_case("to_fix", verdict="conflict", verification={"rationale": "与PRD相反", "prd_evidence": "§5.2"})
    ]
    md = _generate_markdown(main, clar, fix)
    assert "需求澄清清单" in md
    assert "待修正用例" in md
    assert "PRD未定义" in md and "与PRD相反" in md


def test_markdown_escapes_pipe_in_title():
    """标题/理由含竖线不应破坏 markdown 表格结构。"""
    clar = [_full_case("needs_spec", title="A|B 字段", verification={})]
    md = _generate_markdown([], clar, None)
    assert "A\\|B 字段" in md


def test_markdown_main_only_no_sections():
    md = _generate_markdown([_full_case("main")], None, None)
    assert "需求澄清清单" not in md and "待修正用例" not in md


def test_markdown_handles_none_verification():
    """旧数据 verification=None 时清单仍可生成，理由/依据为空。"""
    clar = [_full_case("needs_spec", verdict="undefined", verification=None)]
    md = _generate_markdown([], clar, None)
    assert "需求澄清清单" in md


# ── excel 生成：多 sheet（需 openpyxl，缺失则跳过）──────────────────────────


def test_excel_creates_review_sheets():
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    main = [_full_case("main")]
    clar = [_full_case("needs_spec", verdict="undefined", verification={"rationale": "r", "prd_evidence": "e"})]
    fix = [_full_case("to_fix", verdict="conflict", verification={"rationale": "r2", "prd_evidence": "e2"})]
    wb = load_workbook(BytesIO(_generate_excel(main, clar, fix)))
    assert "测试用例" in wb.sheetnames
    assert "需求澄清清单" in wb.sheetnames
    assert "待修正用例" in wb.sheetnames


def test_excel_no_review_sheets_when_empty():
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    wb = load_workbook(BytesIO(_generate_excel([_full_case("main")], None, None)))
    assert wb.sheetnames == ["测试用例"]


def test_excel_strips_illegal_control_chars():
    """标题/字段含非法控制字符时应被清洗，不应让 openpyxl 抛 IllegalCharacterError。"""
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    main = [_full_case("main", title="标题\x00\x07X")]
    wb = load_workbook(BytesIO(_generate_excel(main, None, None)))
    ws = wb["测试用例"]
    # 第 2 行第 2 列 = 标题（第 1 行为表头），控制字符已被剔除
    assert ws.cell(row=2, column=2).value == "标题X"


# ── CSV 降级：openpyxl 缺失时仍需带上澄清/待修正区块（当前环境实际路径）───────


def test_csv_fallback_includes_review_blocks():
    main = [_full_case("main")]
    clar = [_full_case("needs_spec", title="待澄清用例", verification={"rationale": "r", "prd_evidence": "e"})]
    fix = [_full_case("to_fix", title="待修正用例X", verification={"rationale": "r2", "prd_evidence": "e2"})]
    text = _generate_csv_fallback(main, clar, fix).decode("utf-8-sig")
    assert "需求澄清清单" in text and "待澄清用例" in text
    assert "待修正用例" in text and "待修正用例X" in text


def test_csv_fallback_main_only():
    text = _generate_csv_fallback([_full_case("main")], None, None).decode("utf-8-sig")
    assert "需求澄清清单" not in text and "待修正用例" not in text
