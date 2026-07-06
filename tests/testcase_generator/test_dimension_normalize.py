"""维度 normalize 单测。"""
from __future__ import annotations

from src.testcase_generator.stages.write_cases.dimension_normalizer import normalize_dimensions


def test_enum_passthrough():
    assert normalize_dimensions(["functional_correctness"]) == ["functional_correctness"]


def test_chinese_alias_mapped():
    assert normalize_dimensions(["正常流", "边界值"]) == ["functional_correctness", "boundary_value"]


def test_unknown_goes_other_and_dedup():
    out = normalize_dimensions(["正常流", "正常流", "火星维度"])
    assert out[0] == "functional_correctness"
    assert "other" in out
    assert out.count("functional_correctness") == 1  # 去重保序


def test_empty_list():
    assert normalize_dimensions([]) == []


def test_all_unknown():
    assert normalize_dimensions(["火星维度", "木星维度"]) == ["other"]


def test_case_sensitive_not_matched():
    """LLM 偶发大写不命中 enum → other。"""
    out = normalize_dimensions(["Functional_Correctness"])
    assert out == ["other"]
