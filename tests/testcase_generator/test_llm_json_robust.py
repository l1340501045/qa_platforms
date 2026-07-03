"""网关 JSON 健壮性：_loads_tolerant 容错 + _salvage_json 截断抢救。"""

import json

import pytest

from src.testcase_generator.services.llm_client import _loads_tolerant, _salvage_json


def test_loads_tolerant_plain():
    assert _loads_tolerant('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


def test_loads_tolerant_prefix_suffix_noise():
    # 前后有解释性文字 → 裁到首尾大括号
    assert _loads_tolerant('说明：\n{"a": 1}\n以上') == {"a": 1}


def test_loads_tolerant_raises_when_unrecoverable():
    with pytest.raises(json.JSONDecodeError):
        _loads_tolerant("完全不是 json")


def test_salvage_truncated_array_of_objects():
    # 网关在最后一个对象中途截断 → 救回已完整的前两个
    text = '{"test_cases": [{"id": "1", "t": "x"}, {"id": "2", "t": "y"}, {"id": "3", "t'
    out = _salvage_json(text)
    assert out is not None
    assert [c["id"] for c in out["test_cases"]] == ["1", "2"]


def test_salvage_trailing_comma_primitives():
    text = '{"items": ["a", "b", "c",'
    out = _salvage_json(text)
    assert out is not None
    assert out["items"] == ["a", "b", "c"]


def test_salvage_truncated_midstring():
    # 在字符串值中途截断 → 截到上一个完整字段边界
    text = '{"items": ["a", "b"], "note": "未写完的说明这里被截断'
    out = _salvage_json(text)
    assert out is not None
    assert out["items"] == ["a", "b"]


def test_salvage_returns_none_on_garbage():
    assert _salvage_json("完全不是 json，没有大括号") is None


def test_salvage_keeps_escaped_quotes():
    # 字符串内转义引号不应被误判为字符串结束
    text = '{"cases": [{"q": "他说\\"通过\\"了"}, {"q": "第二条"}, {"q": "断'
    out = _salvage_json(text)
    assert out is not None
    assert len(out["cases"]) == 2
    assert out["cases"][0]["q"] == '他说"通过"了'
