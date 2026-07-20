"""离线规则覆盖率体检 CLI（P0 基线 / 回归守卫，不接流水线）。

流程：
  1. 按 batch-id（支持前缀）查 TestBatch → 取 seed document_id；
  2. `load_seed_markdown`（与 rule_extract_node 同源！）取原始 markdown 全文；
  3. `splitter.build_units` → `extractor.extract_rules` 抽规则台账（或 `--ledger` 复用冻结台账）；
  4. 查该批次 test_cases；
  5. 按 module 分组，`rule_coverage.judge_rule_coverage` 逐模块判定 → 聚合规则总数/覆盖率/各模块漏测；
  6. 打印汇总；`--freeze` 落盘冻结台账，覆盖结果写 probe_<batch>.json。

用法（cwd=项目根）：
  PYTHONPATH=. .venv/bin/python -m src.testcase_generator.cli.rule_coverage_probe --batch-id dd03218e --freeze
  PYTHONPATH=. .venv/bin/python -m src.testcase_generator.cli.rule_coverage_probe --batch-id <id> \
    --ledger .qa_probe/rule_extract/rules_ledger_dd03218e.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Text, cast, select

OUT_DIR = Path(".qa_probe/rule_extract")


async def _resolve_batch(session, batch_id: str):
    from src.platform_api.models.testcase import TestBatch

    stmt = select(TestBatch).where(cast(TestBatch.id, Text).like(f"{batch_id}%"))
    res = await session.execute(stmt)
    batches = list(res.scalars().all())
    if not batches:
        raise SystemExit(f"未找到批次（前缀={batch_id}）")
    if len(batches) > 1:
        ids = ", ".join(str(b.id) for b in batches)
        raise SystemExit(f"批次前缀不唯一，匹配到多个: {ids}")
    return batches[0]


async def _fetch_cases(session, batch_uuid) -> list[dict]:
    from src.platform_api.models.testcase import TestCase

    stmt = select(TestCase).where(TestCase.batch_id == batch_uuid)
    res = await session.execute(stmt)
    cases = []
    for c in res.scalars().all():
        cases.append(
            {
                "title": c.title,
                "steps": c.steps,
                "expected_results": c.expected_results,
                "dimensions": c.dimensions,
            }
        )
    return cases


async def _build_ledger(document_id, client, ledger_path: str | None) -> dict:
    """抽取（或复用冻结）规则台账，返回 {rules:[{rule_code,module,rule,...}], total, failed_units}。"""
    if ledger_path:
        data = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
        print(f"复用冻结台账 {ledger_path}：{data['total']} 条规则", flush=True)
        return data

    from src.testcase_generator.stages.rule_extract.extractor import extract_rules
    from src.testcase_generator.stages.rule_extract.source_loader import load_seed_markdown
    from src.testcase_generator.stages.rule_extract.splitter import build_units

    md = await load_seed_markdown(document_id)
    units, digest, _clog = build_units(md)
    print(f"切分完成：{len(units)} 单元（全文 {len(md)} 字），开始抽取...", flush=True)
    ledger = await extract_rules(units, digest, client, concurrency=4)
    print(f"抽取完成：{ledger.total} 条规则（失败单元 {ledger.failed_units}）", flush=True)
    return {"total": ledger.total, "failed_units": ledger.failed_units, "rules": [r.model_dump() for r in ledger.rules]}


async def _judge_all(ledger: dict, cases: list[dict], client) -> dict:
    from src.testcase_generator.services.rule_coverage import judge_rule_coverage

    by_module: dict[str, list[dict]] = defaultdict(list)
    for r in ledger["rules"]:
        by_module[r.get("module", "未归类")].append(r)

    sem = asyncio.Semaphore(4)

    async def _one(module: str, rules: list[dict]) -> dict:
        async with sem:
            try:
                res = await judge_rule_coverage(rules, cases, client, topk=110)
                res["module"] = module
                print(
                    f"  [{module}] 规则{res['total']} 覆盖{res['covered']} 漏{res['missed']} "
                    f"漏测率={res['miss_rate']:.0%}",
                    flush=True,
                )
                return res
            except Exception as e:  # noqa: BLE001 — 单模块判定失败隔离，不拖垮整批基线
                print(f"  [{module}] 判定失败（已隔离）: {type(e).__name__}: {str(e)[:80]}", flush=True)
                return {
                    "module": module,
                    "total": len(rules),
                    "covered": 0,
                    "missed": 0,
                    "miss_rate": 0.0,
                    "error": str(e),
                    "judged": False,
                }

    module_results = await asyncio.gather(*[_one(m, rs) for m, rs in by_module.items()])
    ok = [r for r in module_results if not r.get("error")]
    failed = [r for r in module_results if r.get("error")]
    total = sum(r["total"] for r in module_results)
    judged_total = sum(r["total"] for r in ok)
    covered = sum(r["covered"] for r in ok)
    return {
        "total_rules": total,
        "judged_rules": judged_total,
        "covered": covered,
        "missed": judged_total - covered,
        "coverage": round(covered / judged_total, 3) if judged_total else 0.0,
        "failed_modules": len(failed),
        "by_module": module_results,
    }


async def _run(args: argparse.Namespace) -> None:
    from src.platform_api.core.model_runtime import model_runtime_scope
    from src.platform_api.services.task_model_runtime import load_active_model_bundle
    from src.testcase_generator.db import async_session_factory
    from src.testcase_generator.services.llm_client import get_llm_client

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_session_factory() as session:
        batch = await _resolve_batch(session, args.batch_id)
        cases = await _fetch_cases(session, batch.id)
        model_bundle = await load_active_model_bundle(session)
    print(f"批次 {str(batch.id)[:8]}：seed 文档 {batch.document_id}，用例 {len(cases)} 条", flush=True)

    with model_runtime_scope(model_bundle):
        client = get_llm_client()
        ledger = await _build_ledger(batch.document_id, client, args.ledger)

        print("开始规则级覆盖判定（按模块）...", flush=True)
        summary = await _judge_all(ledger, cases, client)

    short = str(batch.id)[:8]
    if args.freeze and not args.ledger:
        ledger_out = OUT_DIR / f"rules_ledger_{short}.json"
        ledger_out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已冻结台账 → {ledger_out}", flush=True)

    probe_out = OUT_DIR / f"probe_{short}.json"
    probe_out.write_text(
        json.dumps({"batch_id": str(batch.id), "case_count": len(cases), **summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n==================== 体检结果 ====================", flush=True)
    print(f"批次：{batch.id}", flush=True)
    print(f"用例数：{len(cases)}", flush=True)
    print(f"规则总数：{summary['total_rules']}（已判定 {summary['judged_rules']}）", flush=True)
    if summary["failed_modules"]:
        print(f"判定失败模块：{summary['failed_modules']} 个（其规则未计入覆盖率分母）", flush=True)
    print(f"覆盖：{summary['covered']}  漏：{summary['missed']}", flush=True)
    print(f"整体规则覆盖率（按已判定规则）：{summary['coverage']:.1%}", flush=True)
    print(f"明细 → {probe_out}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="离线规则覆盖率体检（P0 基线 / 回归守卫）")
    parser.add_argument("--batch-id", required=True, help="批次 ID（支持前缀，如 dd03218e）")
    parser.add_argument("--freeze", action="store_true", help="冻结规则台账到 rules_ledger_<batch>.json")
    parser.add_argument("--ledger", default=None, help="复用已冻结台账路径（跳过 LLM 重抽，只重算覆盖）")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
