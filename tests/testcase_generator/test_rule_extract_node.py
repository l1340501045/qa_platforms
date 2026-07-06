"""Task 1.2 — rule_extract_node 测试。

验证：
  (a) 开关开时产出 state["rules"]，每条带 rule_code/module；
  (b) C1 不变式：节点喂给 build_units 的是 load_seed_markdown 的【原文】，
      其规则单元（module 集合）与对同一原文直接跑 build_units 的单元标题一致——
      证明运行期节点与离线探针卡同一套规则集；
  (c) 开关关时直通：state["rules"]==[]，不读文档、不调 LLM。
"""

from __future__ import annotations

import pytest

from src.platform_api.core.settings import settings
from src.testcase_generator.schemas.rule import ExtractedRule, UnitRules
from src.testcase_generator.stages.rule_extract import node as rule_node
from src.testcase_generator.stages.rule_extract.splitter import build_units

RAW_MD = """# 一、文档元信息
作者：x
## 1.2 变更日志
| 时间 | 版本 |
# 五、功能详述
## 5.1 账户授权
投手只能查看本人触发的授权记录，不能看他人记录。组长可查看本组全部成员的授权记录。管理员可查看全量授权记录。授权变更后立即生效，无需刷新页面。授权记录按时间倒序展示，支持按投手与时间范围筛选，分页每页二十条。
## 5.8 批量创建
切换漫剧时清空已选链接与素材，并给出二次确认提示。提交先弹确认框，立即提交或定时提交二选一。定时提交仅限自然日，不可选择过去时间点。单次批量创建上限一千条，超限时整批拒绝并提示。
"""


class _OneRulePerUnitClient:
    """每个单元产 1 条规则，规则文本里嵌入模块标题（从 user_content 解析），便于断言同源。"""

    def __init__(self):
        self.calls = 0

    async def generate_structured(self, system_prompt, user_content, output_schema, temperature=0.3):
        self.calls += 1
        import json

        title = json.loads(user_content)["module_title"]
        return UnitRules(rules=[ExtractedRule(rule=f"规则 of {title}", source_quote="q", category="功能")])


@pytest.mark.asyncio
async def test_enabled_produces_rules_same_source_as_probe(monkeypatch):
    monkeypatch.setattr(settings, "rule_extract_enabled", True)
    client = _OneRulePerUnitClient()

    async def _fake_load(document_id):
        assert document_id == "doc-123"
        return RAW_MD

    monkeypatch.setattr(rule_node, "load_seed_markdown", _fake_load)
    monkeypatch.setattr(rule_node, "get_llm_client", lambda: client)

    out = await rule_node.rule_extract_node({"document_id": "doc-123"})
    rules = out["rules"]

    assert rules, "开关开时应产出规则"
    assert all(r["rule_code"] and r["module"] for r in rules)
    # 统一编号连续
    assert [r["rule_code"] for r in rules][:2] == ["R-001", "R-002"]

    # C1 不变式：节点的 module 集合 == 对同一原文直接跑 build_units 的单元标题集合
    expected_units, _, _ = build_units(RAW_MD)
    assert {r["module"] for r in rules} == {u["title"] for u in expected_units}


@pytest.mark.asyncio
async def test_disabled_passthrough_no_llm_no_doc(monkeypatch):
    monkeypatch.setattr(settings, "rule_extract_enabled", False)

    called = {"load": False, "client": False}

    async def _fake_load(document_id):
        called["load"] = True
        return RAW_MD

    def _fake_client():
        called["client"] = True
        raise AssertionError("开关关时不应调 LLM")

    monkeypatch.setattr(rule_node, "load_seed_markdown", _fake_load)
    monkeypatch.setattr(rule_node, "get_llm_client", _fake_client)

    out = await rule_node.rule_extract_node({"document_id": "doc-123"})
    assert out["rules"] == []
    assert called == {"load": False, "client": False}
