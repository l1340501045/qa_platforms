"""Task 0.3 — 规则↔用例覆盖判定服务测试（fake client）。

验证：覆盖率/漏测率计算正确、rule_code 透传、关键词召回 top-K 截断生效、
无相关候选用例时确定性判全未覆盖（不打 LLM）、判定调用使用 temperature=0（红线可复现）。
"""

from __future__ import annotations

import json

import pytest

from src.testcase_generator.services.rule_coverage import (
    ModuleCoverage,
    RuleVerdict,
    judge_rule_coverage,
)


class _FakeJudge:
    def __init__(self, covered_indices):
        self.covered = set(covered_indices)
        self.calls = 0
        self.last_user: dict | None = None
        self.last_temperature: float | None = None

    async def generate_structured(self, system_prompt, user_content, output_schema, temperature=0.3):
        self.calls += 1
        self.last_user = json.loads(user_content)
        self.last_temperature = temperature
        verdicts = [
            RuleVerdict(
                rule_index=i,
                covered=(i in self.covered),
                covering_case_title=("用例X" if i in self.covered else ""),
                note=("" if i in self.covered else "缺少对该规则的断言"),
            )
            for i, _ in enumerate(self.last_user["rules"])
        ]
        return ModuleCoverage(verdicts=verdicts)


@pytest.mark.asyncio
async def test_coverage_and_codes_and_temperature_zero():
    rules = [
        {"rule_code": "R-001", "rule": "投放链接必须唯一", "category": "校验"},
        {"rule_code": "R-002", "rule": "高级别权限包含低级别权限", "category": "权限"},
    ]
    cases = [
        {"title": "投放链接唯一性校验", "steps": ["导入重复链接"], "expected_results": ["提示重复"]},
        {"title": "权限继承校验", "steps": ["高级别访问"], "expected_results": ["可见低级别"]},
    ]
    judge = _FakeJudge(covered_indices=[0])  # 只覆盖 R-001
    res = await judge_rule_coverage(rules, cases, judge, topk=110)

    assert res["total"] == 2
    assert res["covered"] == 1
    assert res["missed"] == 1
    assert res["miss_rate"] == 0.5
    assert judge.last_temperature == 0.0  # 红线可复现：必须 temperature=0
    # rule_code 透传 + 未覆盖项带 note
    by_code = {d["rule_code"]: d for d in res["detail"]}
    assert by_code["R-001"]["covered"] is True
    assert by_code["R-002"]["covered"] is False
    assert by_code["R-002"]["note"]


@pytest.mark.asyncio
async def test_topk_truncation():
    rules = [{"rule_code": "R-001", "rule": "投放链接必须唯一", "category": "校验"}]
    cases = [
        {"title": f"投放链接唯一性校验用例{i}", "steps": ["导入"], "expected_results": ["唯一"]}
        for i in range(5)
    ]
    judge = _FakeJudge(covered_indices=[0])
    await judge_rule_coverage(rules, cases, judge, topk=2)
    # 关键词召回后截断到 top-2
    assert len(judge.last_user["candidate_cases"]) == 2


@pytest.mark.asyncio
async def test_no_candidate_all_uncovered_without_llm():
    rules = [{"rule_code": "R-001", "rule": "投放链接必须唯一", "category": "校验"}]
    cases = [{"title": "完全无关的登录用例", "steps": ["登录"], "expected_results": ["成功"]}]
    judge = _FakeJudge(covered_indices=[])
    res = await judge_rule_coverage(rules, cases, judge, topk=110)

    assert res["total"] == 1
    assert res["covered"] == 0
    assert res["miss_rate"] == 1.0
    assert judge.calls == 0  # 无候选 → 不打 LLM，确定性判全未覆盖


@pytest.mark.asyncio
async def test_empty_rules():
    res = await judge_rule_coverage([], [{"title": "x"}], _FakeJudge([]), topk=110)
    assert res == {"total": 0, "covered": 0, "missed": 0, "miss_rate": 0.0, "detail": []}
