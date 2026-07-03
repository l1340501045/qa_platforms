"""离线评估生成侧收敛（拆条上限 + 存在性合并）效果。

读 .audit/<batch>/modules/<模块>/branches/**/cases.jsonl，兼容旧版 modules/*.cases.jsonl，
跑 merge_existence_cases + cap_cases_per_testpoint，
统计合并/裁剪条数、总量前后、每测试点条数分布，并报告 cap coverage debt（被裁掉的
维度/边界形态/来源章节）。零 LLM 成本。
"""

from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.audit_case_reader import iter_case_records, resolve_batch_path
from src.testcase_generator.schemas.test_case import GeneratedTestCase, Provenance, TestStep
from src.testcase_generator.stages.write_cases.convergence import (
    analyze_cap_coverage_debt,
    apply_convergence,
    cap_cases_per_testpoint,
    merge_existence_cases,
)


def _to_generated_case(record: dict) -> GeneratedTestCase | None:
    case_id = str(record.get("id") or "")
    title = str(record.get("title") or "")
    tp_id = str(record.get("test_point_id") or "")
    if not case_id or not title or not tp_id:
        return None

    steps = []
    for s in record.get("steps") or []:
        steps.append(
            TestStep(
                step_number=s.get("step_number", len(steps) + 1),
                action=s.get("action", ""),
                input_data=s.get("input_data", ""),
                expected_result=s.get("expected_result", ""),
                source_quote=s.get("source_quote") or None,
                source_ref=s.get("source_ref") or None,
            )
        )

    prov_payload = record.get("provenance") or {}
    provenance = Provenance(
        derived_from=prov_payload.get("derived_from") or [],
        source_section=prov_payload.get("source_section") or "",
        verbatim_excerpt=prov_payload.get("verbatim_excerpt") or "",
        trust_level=prov_payload.get("trust_level", 3),
    )

    return GeneratedTestCase(
        id=case_id,
        test_point_id=tp_id,
        title=title,
        preconditions=record.get("preconditions") or [],
        steps=steps,
        expected_results=record.get("expected_results") or [],
        priority=record.get("priority", "P2"),
        dimensions=record.get("dimensions") or [],
        provenance=provenance,
        trust_level=record.get("trust_level", 3),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="离线评估生成侧收敛效果")
    parser.add_argument("batch", help="batch id 或 .audit/<batch> 路径")
    parser.add_argument("--cap", type=int, default=3, help="每测试点用例数上限，默认 3")
    parser.add_argument("--no-merge", action="store_true", help="跳过存在性合并，只评估拆条上限")
    parser.add_argument("--no-cap", action="store_true", help="跳过拆条上限，只评估存在性合并")
    args = parser.parse_args()

    batch_path = resolve_batch_path(args.batch)
    if not batch_path.exists():
        raise SystemExit(f"batch 不存在：{batch_path}")

    cases: list[GeneratedTestCase] = []
    for _, _, record in iter_case_records(batch_path):
        gc = _to_generated_case(record)
        if gc is not None:
            cases.append(gc)

    before_by_tp = Counter(c.test_point_id for c in cases)
    before_total = len(cases)

    # 构造一个只含所需字段的假 settings 驱动 apply_convergence
    from types import SimpleNamespace

    settings = SimpleNamespace(
        existence_merge_enabled=not args.no_merge,
        split_cap_enabled=not args.no_cap,
        cases_per_tp_cap=args.cap,
    )
    converged = apply_convergence(cases, settings)

    after_by_tp = Counter(c.test_point_id for c in converged)
    after_total = len(converged)

    # ── cap coverage debt 分析 + culled 统计：精确针对 cap 这一步，不被 merge 干扰 ──
    # 复现 cap 路径：先 merge 得 merged（与 apply_convergence 同序），深拷贝作裁剪前快照，
    # 再 cap，按 TP 用「裁剪前全集」vs「裁剪后 kept」算 debt。
    #
    # culled 必须从 merged（被 cap 原地置 duplicate_of）推导，而非原始 cases——存在性合并
    # 产出的 model_copy 代表被 cap 裁掉时，原始 cases 不会被标记，从 cases 推导会漏统计。
    debt_by_tp: dict[str, object] = {}
    culled: list[GeneratedTestCase] = []
    if not args.no_cap:
        merged = merge_existence_cases(cases) if not args.no_merge else list(cases)
        # merge 已对 cases 原地改过，merged 即代表 cap 前状态；深拷贝冻结裁剪前快照
        pre_cap = copy.deepcopy(merged)
        # 重置 deepcopy 副本的 duplicate_of，确保 debt 比对基于"未裁"状态
        for c in pre_cap:
            c.duplicate_of = None
        kept_after_cap = cap_cases_per_testpoint(merged, n=args.cap)

        # culled = cap 在 merged 上原地置过 duplicate_of 的对象（含被裁的 merge 代表）
        culled = [c for c in merged if c.duplicate_of is not None]

        pre_by_tp: dict[str, list[GeneratedTestCase]] = defaultdict(list)
        for c in pre_cap:
            pre_by_tp[c.test_point_id].append(c)
        kept_by_tp: dict[str, list[GeneratedTestCase]] = defaultdict(list)
        for c in kept_after_cap:
            kept_by_tp[c.test_point_id].append(c)

        for tp_id, pre_cases in pre_by_tp.items():
            if len(pre_cases) <= args.cap:
                continue  # 未触发 cap，无 debt
            debt = analyze_cap_coverage_debt(pre_cases, kept_by_tp.get(tp_id, []))
            if debt.has_debt:
                debt_by_tp[tp_id] = debt

    # 每 tp 条数分布（前/后）
    tp_ids = sorted(before_by_tp.keys(), key=lambda t: -before_by_tp[t])
    over_cap_before = sum(1 for n in before_by_tp.values() if n > args.cap)

    print(f"batch: {batch_path.name}")
    print(f"cases: {before_total}")
    print(f"existence_merge: {'on' if not args.no_merge else 'off'}")
    print(f"split_cap: {'on' if not args.no_cap else 'off'} (n={args.cap})")
    print(f"total: {before_total} -> {after_total} (减 {before_total - after_total})")
    print(f"culled_by_cap: {len(culled)}")
    print(f"tps_over_cap_before: {over_cap_before}")
    print(f"tps_over_cap_after: {sum(1 for n in after_by_tp.values() if n > args.cap)}")
    print(f"max_per_tp_before: {max(before_by_tp.values()) if before_by_tp else 0}")
    print(f"max_per_tp_after: {max(after_by_tp.values()) if after_by_tp else 0}")

    # 抽样：条数最多的前 5 个 tp 的前后对比
    print("\ntop 5 tps by before-count:")
    for tp_id in tp_ids[:5]:
        debt_flag = " [COVERAGE DEBT]" if tp_id in debt_by_tp else ""
        print(f"  {tp_id[:12]}…: {before_by_tp[tp_id]} -> {after_by_tp.get(tp_id, 0)}{debt_flag}")

    # 抽样：被裁用例（区分 coverage overflow vs 疑似重复裁剪）
    if culled:
        debt_tp_set = set(debt_by_tp.keys())
        overflow = [c for c in culled if c.test_point_id in debt_tp_set]
        redundant = [c for c in culled if c.test_point_id not in debt_tp_set]
        print(f"\ncap_breakdown: coverage_overflow={len(overflow)} redundant_fold={len(redundant)}")
        print(f"sampled overflow-culled ({min(5, len(overflow))}/{len(overflow)}):")
        for c in overflow[:5]:
            print(f"  - {c.id} [{c.test_point_id[:8]}…] {c.title[:40]} dims={c.dimensions} -> dup_of {c.duplicate_of}")

    # ── coverage debt 汇总：被裁掉的维度/边界形态/来源章节 ──
    print(f"\ndebt_tp_count: {len(debt_by_tp)}")
    all_dropped_dims: list[str] = []
    all_dropped_boundary: list[str] = []
    all_dropped_source: list[str] = []
    for debt in debt_by_tp.values():
        all_dropped_dims.extend(debt.dropped_dimensions)
        all_dropped_boundary.extend(debt.dropped_boundary_atoms)
        all_dropped_source.extend(debt.dropped_source_sections)
    print(f"dropped_dimensions: {sorted(set(all_dropped_dims))}")
    print(f"dropped_boundary_atoms: {sorted(set(all_dropped_boundary))}")
    print(f"dropped_source_sections: {sorted(set(all_dropped_source))}")

    # 每个 debt TP 的明细：dropped 覆盖 + 样例 case id
    if debt_by_tp:
        print("\ndebt details (per tp):")
        for tp_id, debt in debt_by_tp.items():
            sample_dropped = debt.dropped_ids[:3]
            print(
                f"  {tp_id[:12]}…: total={debt.total} kept={len(debt.kept_ids)} "
                f"dropped_dims={debt.dropped_dimensions} "
                f"dropped_boundary={debt.dropped_boundary_atoms} "
                f"dropped_source={debt.dropped_source_sections} "
                f"sample_dropped_ids={sample_dropped}"
            )
    else:
        print("\ndebt details: 无 coverage debt（所有 cap 裁剪均为纯冗余折叠，未丢独立覆盖）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
