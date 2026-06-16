"""规则抽取器 —— 每个模块单元喂全文，逐条抽「明示业务规则」，汇成规则台账。

固化自离线探针 `.qa_probe/rule_extract/extract_rules.py`：
  - 并发抽取（信号量限流），单元失败隔离（不抛、计入 failed_units）；
  - 汇总时统一编号 R-001.. 并回填来源模块标题。
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.testcase_generator.schemas.rule import RuleItem, RuleLedger, UnitRules

logger = logging.getLogger(__name__)


_SYS = """角色：你是资深测试分析师。下面给你某 PRD 的【一个模块的完整原文】和一份全局摘要。
任务：逐条抽取该模块中【明示的、必须成立的业务规则 / 验收标准】——即开发必须实现、测试必须验证的确定性陈述。

规则要求：
- 只抽 PRD 明确写出的规则；不要臆测、不要补 PRD 没说的内容。
- 原子化：一条规则只讲一件事（"高级别包含低级别"和"分配后立即生效"是两条）。
- 可验证：能据此写出测试用例（有明确的输入/条件/预期）。
- 涵盖：字段校验规则、约束（唯一性/必填/格式/取值范围）、状态流转、权限可见性、联动行为、默认值、边界与上限。
- 忽略：纯背景叙述、UI 美化描述、截图说明、变更记录、未来规划（V2/二期）。
- 每条给出 source_quote（原文短引用）与 category（功能/校验/权限/状态/边界/数据/联动）。

严格按指定 JSON Schema 输出。"""


async def _extract_one(client, sem: asyncio.Semaphore, unit: dict, digest: str) -> dict:
    """抽取单个模块单元；失败隔离（返回 ok=False，不抛）。"""
    user = json.dumps(
        {
            "module_title": unit["title"],
            "global_digest": digest,
            "module_full_text": unit["text"],
        },
        ensure_ascii=False,
    )
    async with sem:
        try:
            out: UnitRules = await client.generate_structured(_SYS, user, UnitRules, temperature=0.2)
            return {"title": unit["title"], "ok": True, "rules": out.rules}
        except Exception as e:  # noqa: BLE001 — 单元失败隔离：不让一个坏单元拖垮整批
            logger.warning("规则抽取单元失败（已隔离）: %s — %s: %s", unit.get("title"), type(e).__name__, e)
            return {"title": unit["title"], "ok": False, "error": str(e), "rules": []}


async def extract_rules(units: list[dict], digest: str, client, concurrency: int = 4) -> RuleLedger:
    """并发抽取所有单元，汇成统一编号的规则台账。

    Args:
        units: `splitter.build_units` 产出的模块单元列表。
        digest: 全局摘要，各单元共享。
        client: 具备 `generate_structured(system, user, schema, temperature)` 的 LLM 客户端。
        concurrency: 并发上限。
    """
    if not units:
        return RuleLedger(rules=[], total=0, failed_units=0)

    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*[_extract_one(client, sem, u, digest) for u in units])

    rules: list[RuleItem] = []
    failed = 0
    for res in results:
        if not res["ok"]:
            failed += 1
            continue
        for r in res["rules"]:
            rules.append(
                RuleItem(
                    rule_code=f"R-{len(rules) + 1:03d}",
                    module=res["title"],
                    rule=r.rule,
                    source_quote=r.source_quote,
                    category=r.category,
                )
            )

    return RuleLedger(rules=rules, total=len(rules), failed_units=failed)
