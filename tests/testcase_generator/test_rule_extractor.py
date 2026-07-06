"""Task 0.2 — 规则抽取器测试（fake LLM client，不打真网关）。

验证：每单元抽取 → 汇总统一编号 R-001.. → 回填 module → 失败单元隔离不抛、计入 failed_units。
"""

from __future__ import annotations

import pytest

from src.testcase_generator.schemas.rule import ExtractedRule, UnitRules
from src.testcase_generator.stages.rule_extract.extractor import extract_rules


class _FakeClient:
    """按模块标题返回固定规则；标题含 "BOOM" 的单元抛错，用于验证失败隔离。"""

    def __init__(self):
        self.calls = 0

    async def generate_structured(self, system_prompt, user_content, output_schema, temperature=0.3):
        self.calls += 1
        if "BOOM" in user_content:
            raise ValueError("模拟网关返回非法 JSON")
        # 每单元产 2 条规则
        return UnitRules(
            rules=[
                ExtractedRule(rule="规则A", source_quote="原文A", category="校验"),
                ExtractedRule(rule="规则B", source_quote="原文B", category="权限"),
            ]
        )


@pytest.mark.asyncio
async def test_assembles_numbered_ledger_with_module():
    units = [
        {"title": "5.1 授权", "level": 2, "chars": 100, "text": "5.1 授权全文"},
        {"title": "5.8 批量创建", "level": 2, "chars": 100, "text": "5.8 全文"},
    ]
    ledger = await extract_rules(units, digest="全局摘要", client=_FakeClient(), concurrency=2)

    assert ledger.total == 4
    assert ledger.failed_units == 0
    # 统一编号 R-001..R-004，无重复
    codes = [r.rule_code for r in ledger.rules]
    assert codes == ["R-001", "R-002", "R-003", "R-004"]
    # 回填来源模块
    modules = {r.module for r in ledger.rules}
    assert modules == {"5.1 授权", "5.8 批量创建"}


@pytest.mark.asyncio
async def test_failed_unit_isolated_not_raised():
    units = [
        {"title": "5.1 授权", "level": 2, "chars": 100, "text": "正常全文"},
        {"title": "BOOM 模块", "level": 2, "chars": 100, "text": "BOOM 触发异常"},
    ]
    ledger = await extract_rules(units, digest="", client=_FakeClient(), concurrency=2)

    # 失败单元被隔离：不抛、计入 failed_units，正常单元规则照常入账
    assert ledger.failed_units == 1
    assert ledger.total == 2
    assert all(r.module == "5.1 授权" for r in ledger.rules)


@pytest.mark.asyncio
async def test_empty_units_yield_empty_ledger():
    ledger = await extract_rules([], digest="", client=_FakeClient(), concurrency=2)
    assert ledger.total == 0
    assert ledger.rules == []
