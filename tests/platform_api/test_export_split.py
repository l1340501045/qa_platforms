"""导出分流单测：三桶分流（main/needs_spec/to_fix）+ 需求澄清/待修正清单生成。"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from src.platform_api.tasks.export_task import (
    TAPD_HEADERS,
    TAPD_INSTRUCTIONS,
    _generate_csv_fallback,
    _generate_excel,
    _generate_markdown,
    _split_cases,
    _tapd_directory,
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
        provenance={"source_section": "系统管理/登录>异常流程"},
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


# ── markdown 生成：TAPD 模板字段表格 ───────────────────────────────────────


def test_markdown_uses_tapd_template_columns_and_mapping():
    main = [_full_case("main", priority="P1")]
    clar = [
        _full_case("needs_spec", verdict="undefined", verification={"rationale": "PRD未定义", "prd_evidence": "§5.1"})
    ]
    fix = [_full_case("to_fix", verdict="conflict", verification={"rationale": "与PRD相反", "prd_evidence": "§5.2"})]
    md = _generate_markdown(main, clar, fix)
    assert md.splitlines()[0] == "| " + " | ".join(TAPD_HEADERS) + " |"
    assert "| 系统管理-登录-异常流程 | 标题 |  | 已登录 | 1. 点击（输入：x） | 1. ok |  |  | 中 |  |  |" in md
    assert "需求澄清清单（待 PM 确认，未计入可执行用例）" in md
    assert "待修正用例（与 PRD 冲突，需测试/AI 修正，未计入可执行用例）" in md
    assert "PRD未定义" in md
    assert "与PRD相反" in md


def test_markdown_escapes_pipe_in_title():
    """标题含竖线不应破坏 markdown 表格结构。"""
    md = _generate_markdown([_full_case("main", title="A|B 字段")], None, None)
    assert "A\\|B 字段" in md


def test_markdown_preserves_multistep_line_breaks():
    md = _generate_markdown(
        [
            _full_case(
                "main",
                steps=[
                    {"action": "第一步", "input_data": "a", "expected_result": "结果一"},
                    {"action": "第二步", "input_data": "b", "expected_result": "结果二"},
                ],
            )
        ],
        None,
        None,
    )
    assert "1. 第一步（输入：a）<br>2. 第二步（输入：b）" in md
    assert "1. 结果一<br>2. 结果二" in md


def test_markdown_handles_none_verification():
    """旧数据 verification=None 不影响 TAPD Markdown 主表导出。"""
    md = _generate_markdown([_full_case("main", verification=None)], None, None)
    assert "用例目录" in md and "标题" in md


def test_tapd_directory_uses_case_tree_full_path():
    """用例目录应复用资产模块树坐标，而不是直接导出 PRD 章节来源文本。"""
    case = _full_case(
        "main",
        title="TP-988 页面元素核对（prd:漫剧批创初版功能PRD §5.8.11.1 通配符替换规则）",
        provenance={
            "source_section": "prd:漫剧批创初版功能PRD §5.8.11.1 通配符替换规则",
            "derived_from": ["prd:漫剧批创初版功能PRD §5.8.11.1 通配符替换规则"],
        },
        _export_system_name="漫剧批创系统",
        _export_document_title="漫剧批创初版功能PRD",
    )

    assert _tapd_directory(case) == "漫剧批创系统-漫剧批创初版功能PRD-批量创建广告-命名通配符-通配符替换规则"


# ── excel 生成：TAPD 导入模板（需 openpyxl，缺失则跳过）──────────────────────


def test_excel_uses_tapd_template_columns_and_mapping():
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    main = [_full_case("main", priority="P0")]
    clar = [_full_case("needs_spec", verdict="undefined", verification={"rationale": "r", "prd_evidence": "e"})]
    fix = [_full_case("to_fix", verdict="conflict", verification={"rationale": "r2", "prd_evidence": "e2"})]
    wb = load_workbook(BytesIO(_generate_excel(main, clar, fix)))
    assert wb.sheetnames == ["Sheet1"]
    ws = wb["Sheet1"]
    assert [ws.cell(row=1, column=i).value for i in range(1, 12)] == TAPD_HEADERS
    assert [ws.cell(row=2, column=i).value for i in range(1, 12)] == TAPD_INSTRUCTIONS
    assert [ws.cell(row=3, column=i).value for i in range(1, 12)] == [
        "系统管理-登录-异常流程",
        "标题",
        None,
        "已登录",
        "1. 点击（输入：x）",
        "1. ok",
        None,
        None,
        "高",
        None,
        None,
    ]


def test_excel_maps_priority_levels():
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    cases = [
        _full_case("main", priority="P0"),
        _full_case("main", priority="P1"),
        _full_case("main", priority="P2"),
        _full_case("main", priority="P3"),
    ]
    wb = load_workbook(BytesIO(_generate_excel(cases, None, None)))
    ws = wb["Sheet1"]
    assert [ws.cell(row=i, column=9).value for i in range(3, 7)] == ["高", "中", "低", "低"]


def test_excel_no_review_sheets_when_empty():
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    wb = load_workbook(BytesIO(_generate_excel([_full_case("main")], None, None)))
    assert wb.sheetnames == ["Sheet1"]


def test_excel_strips_illegal_control_chars():
    """标题/字段含非法控制字符时应被清洗，不应让 openpyxl 抛 IllegalCharacterError。"""
    load_workbook = pytest.importorskip("openpyxl").load_workbook

    main = [_full_case("main", title="标题\x00\x07X")]
    wb = load_workbook(BytesIO(_generate_excel(main, None, None)))
    ws = wb["Sheet1"]
    # 第 3 行第 2 列 = 用例名称（第 1 行表头，第 2 行说明），控制字符已被剔除
    assert ws.cell(row=3, column=2).value == "标题X"


# ── CSV 降级：保持 TAPD 模板列顺序 ───────────────────────────────────────


def test_csv_fallback_uses_tapd_columns_only():
    main = [_full_case("main")]
    clar = [_full_case("needs_spec", title="待澄清用例", verification={"rationale": "r", "prd_evidence": "e"})]
    fix = [_full_case("to_fix", title="待修正用例X", verification={"rationale": "r2", "prd_evidence": "e2"})]
    text = _generate_csv_fallback(main, clar, fix).decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0].startswith(
        "用例目录,用例名称,需求ID,前置条件,用例步骤,预期结果,用例类型,用例状态,用例等级,创建人,自测人"
    )
    assert "系统管理-登录-异常流程,标题,," in text
    assert "待澄清用例" not in text
    assert "待修正用例X" not in text


def test_csv_fallback_main_only():
    text = _generate_csv_fallback([_full_case("main")], None, None).decode("utf-8-sig")
    assert "用例目录,用例名称,需求ID" in text
    assert "需求澄清清单" not in text and "待修正用例" not in text
