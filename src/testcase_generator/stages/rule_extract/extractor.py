"""规则抽取器 —— 每个模块单元喂全文，逐条抽「明示业务规则」，汇成规则台账。

固化自离线探针 `.qa_probe/rule_extract/extract_rules.py`：
  - 并发抽取（信号量限流），单元失败隔离（不抛、计入 failed_units）；
  - 汇总时统一编号 R-001.. 并回填来源模块标题；
  - **同源段落合并**（P0-1 修复）：单元内 source_quote 在原文中字符距离 ≤ 阈值
    的连续规则视为同一段落多次切片，强制合并为一条规则——治灌水第一根因。
"""

from __future__ import annotations

import asyncio
import json
import logging

from src.testcase_generator.schemas.rule import ExtractedRule, RuleItem, RuleLedger, UnitRules

logger = logging.getLogger(__name__)


# 同源段落合并阈值：两条规则的 source_quote 在 unit 原文中的最近 char 距离 ≤ 此值时
# 视为同一段落的多次切片，强制合并为一条规则。
# 200 字 ≈ 1-2 个段落或一个 list/table 块的范围；F-008 §5.6.6 删除二次确认（10 拆 1）、
# F-009 §5.7 过滤时间字段联动（6 拆 1）等典型同源拆分均能命中。
_SAME_PARAGRAPH_DIST = 200


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


def _quote_offset_in_text(quote: str, text: str) -> int:
    """source_quote 在原文中的首次出现位置；找不到返回 -1。

    模糊匹配优先：完整片段命中失败时退回前 30 个非空白字符的子串匹配，吸收 PRD 原文与
    LLM 输出之间的全/半角、空白、标点轻微差异。"""
    if not quote or not text:
        return -1
    pos = text.find(quote)
    if pos >= 0:
        return pos
    # 模糊：取 quote 的前 30 个非空白字符做子串匹配
    short = "".join(ch for ch in quote if not ch.isspace())[:30]
    if not short:
        return -1
    return text.find(short)


def _merge_same_paragraph_rules(
    rules: list[ExtractedRule], unit_text: str
) -> tuple[list[ExtractedRule], int]:
    """同 unit 内相邻规则若 source_quote 在原文位置距离 ≤ _SAME_PARAGRAPH_DIST 则合并。

    Returns:
        (merged_rules, dropped_count)
    """
    if len(rules) <= 1 or not unit_text:
        return list(rules), 0

    # 计算每条规则 source_quote 在 unit_text 中的位置；找不到的位置标 -1
    indexed = []
    for r in rules:
        pos = _quote_offset_in_text(r.source_quote, unit_text)
        indexed.append((pos, r))

    # 按 pos 升序（找不到的 -1 留尾），同段落聚类
    located = [(p, r) for p, r in indexed if p >= 0]
    not_located = [r for p, r in indexed if p < 0]
    located.sort(key=lambda x: x[0])

    if not located:
        return list(rules), 0

    merged: list[ExtractedRule] = []
    cur_pos, cur_rule = located[0]
    cur_quotes = [cur_rule.source_quote] if cur_rule.source_quote else []
    cur_rules_text = [cur_rule.rule]
    cur_category = cur_rule.category
    dropped = 0

    for pos, r in located[1:]:
        if pos - cur_pos <= _SAME_PARAGRAPH_DIST:
            # 同段落：合并（拼 rule 文本，保留首条 source_quote/category）
            if r.rule and r.rule not in cur_rules_text:
                cur_rules_text.append(r.rule)
            if r.source_quote and r.source_quote not in cur_quotes:
                cur_quotes.append(r.source_quote)
            dropped += 1
            cur_pos = pos  # 滑动 anchor，让长段落多条仍可串起来
            continue
        # 不同段落：flush 当前
        merged.append(
            ExtractedRule(
                rule="；".join(cur_rules_text),
                source_quote=cur_quotes[0] if cur_quotes else "",
                category=cur_category,
            )
        )
        cur_pos = pos
        cur_rule = r
        cur_quotes = [r.source_quote] if r.source_quote else []
        cur_rules_text = [r.rule]
        cur_category = r.category

    merged.append(
        ExtractedRule(
            rule="；".join(cur_rules_text),
            source_quote=cur_quotes[0] if cur_quotes else "",
            category=cur_category,
        )
    )
    # source_quote 找不到的规则原样保留（不参与合并）
    merged.extend(not_located)
    return merged, dropped


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
        except Exception as e:  # noqa: BLE001 — 单元失败隔离：不让一个坏单元拖垮整批
            logger.warning("规则抽取单元失败（已隔离）: %s — %s: %s", unit.get("title"), type(e).__name__, e)
            return {"title": unit["title"], "ok": False, "error": str(e), "rules": []}

    # P0-1 同源段落合并：unit 内 source_quote 在原文位置 ≤ 200 char 视同一段落
    merged_rules, dropped = _merge_same_paragraph_rules(out.rules, unit.get("text", ""))
    if dropped:
        logger.info(
            "rule_extract 同源合并: %s — %d→%d (合并 %d 条同段落规则)",
            unit.get("title"),
            len(out.rules),
            len(merged_rules),
            dropped,
        )
    return {"title": unit["title"], "ok": True, "rules": merged_rules}


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
