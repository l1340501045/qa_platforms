"""批次用例审查导出工具。

把指定 batch 的 PRD(含图片 AI 描述) + 用例 + 测试点，按业务模块树落盘，
同时保留 source_section 反查视图。业务模块是审查资产组织坐标；
``provenance.source_section`` 是需求证据坐标，不再作为主模块边界。

用法：
  uv run python scripts/audit_export.py <batch_id>             # 仅打印概览统计（不写盘）
  uv run python scripts/audit_export.py <batch_id> --dump      # 落盘到 .audit/<batch_id>/
  uv run python scripts/audit_export.py <batch_id> --calibrate # 生成模块树校准包
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.platform_api.core.database import get_session_factory  # noqa: E402
from src.platform_api.models.knowledge import Document  # noqa: E402
from src.platform_api.models.testcase import TestBatch, TestCase, TestPoint  # noqa: E402
from src.testcase_generator.services import module_tree_classifier  # noqa: E402
from src.testcase_generator.services.assertion_quality import (  # noqa: E402
    has_vague_assertion_signal,
    is_pure_vague_assertion_case,
)
from src.testcase_generator.services.critical_flows import (  # noqa: E402
    CRITICAL_FLOW_PATTERNS,
    source_ref_matches_token,
)
from src.testcase_generator.stages.write_cases.priority_calibration import (  # noqa: E402
    has_business_risk_signal,
    has_display_or_existence_signal,
    has_structural_signal,
    is_low_value_display_case,
)

ROOT = Path(__file__).resolve().parent.parent
AUDIT_SCHEMA_VERSION = 5
CALIBRATION_SCHEMA_VERSION = 1
CALIBRATION_BASE_SAMPLE = 10
CALIBRATION_LARGE_MODULE_SAMPLE = 20
CALIBRATION_LARGE_MODULE_THRESHOLD = 200
CALIBRATION_GATE_TARGETS = {
    "module_accuracy": 0.95,
    "branch_accuracy": 0.85,
    "dirty_branch_name_count": 0,
}
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _case_to_dict(c: TestCase) -> dict:
    """完整导出单个用例（审查所需全字段）"""
    return {
        "id": str(c.id),
        "title": c.title,
        "priority": c.priority,
        "trust_level": c.trust_level,
        "review_status": c.review_status,
        "verdict": c.verdict,
        "bucket": c.bucket,
        "preconditions": c.preconditions,
        "steps": c.steps,
        "expected_results": c.expected_results,
        "dimensions": c.dimensions,
        "provenance": c.provenance,
        "verification": c.verification,
        "confidence_note": c.confidence_note,
        "test_point_id": str(c.test_point_id) if c.test_point_id else None,
        "duplicate_of": str(c.duplicate_of) if c.duplicate_of else None,
        "is_duplicate": c.duplicate_of is not None,
    }


def _point_to_dict(p: TestPoint) -> dict:
    return {
        "id": str(p.id),
        "feature_id": p.feature_id,
        "dimension": p.dimension,
        "description": p.description,
        "priority": p.priority,
        "derived_from": p.derived_from,
    }


def _source_section_of_record(record: dict) -> str:
    prov = record.get("provenance") or {}
    return prov.get("source_section") or "unresolved"


def _source_section_of_case(c: TestCase) -> str:
    prov = c.provenance or {}
    return prov.get("source_section") or "unresolved"


def source_refs_of(record: dict) -> list[str]:
    """抽取需求证据坐标，保序去重。

    ``derived_from`` 常包含多章节引用，``source_section`` 是主引用。业务模块树不再
    直接使用 source_section 做模块边界，但审查包必须保留这些证据坐标供反查。
    """
    return module_tree_classifier.source_refs_of(record)


def classify_case_for_audit(record: dict) -> dict:
    """为审查导出派生业务模块树坐标，不写回原 case/provenance。"""
    return module_tree_classifier.classify_case_for_audit(record)


def _with_audit_classification(record: dict) -> dict:
    enriched = dict(record)
    enriched["audit_classification"] = classify_case_for_audit(enriched)
    return enriched


def _safe_name(name: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name).strip("_")
    return s[:maxlen] or "未分类"


def _parse_prd_sections(content: str) -> list[dict]:
    """解析 PRD markdown 标题树，每个标题切出「到下一个 ≤ 同级标题」之间的正文块。"""
    lines = (content or "").split("\n")
    heads = []  # (line_idx, level, title)
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    sections = []
    for hi, (idx, level, title) in enumerate(heads):
        end = len(lines)
        for idx2, level2, _t in heads[hi + 1 :]:
            if level2 <= level:
                end = idx2
                break
        body = "\n".join(lines[idx:end]).strip()
        sections.append({"level": level, "title": title, "body": body})
    return sections


def _norm_title(s: str) -> str:
    return re.sub(r"[*\s]+", "", s or "")


def _match_section(source_section: str, sections: list[dict]) -> str | None:
    """把用例的 source_section 文本映射到 PRD 章节原文块。"""
    if not source_section or source_section == "unresolved":
        return None
    key = source_section.split("§", 1)[-1].strip()
    key_n = _norm_title(key)
    if not key_n:
        return None
    # 1) 标题完全相等
    for sec in sections:
        if _norm_title(sec["title"]) == key_n:
            return sec["body"]
    # 2) 互为前缀（标题或 key 一方含另一方）
    for sec in sections:
        t = _norm_title(sec["title"])
        if t and (t.startswith(key_n) or key_n.startswith(t)):
            return sec["body"]
    # 3) 章节编号前缀（如 5.8 / 9.2）
    num = re.match(r"^([\d.]+)", key_n)
    if num:
        pref = num.group(1)
        for sec in sections:
            if _norm_title(sec["title"]).startswith(pref):
                return sec["body"]
    return None


async def load(batch_id: UUID):
    factory = get_session_factory()
    async with factory() as s:
        batch = await s.get(TestBatch, batch_id)
        if batch is None:
            raise SystemExit(f"批次不存在: {batch_id}")
        doc = await s.get(Document, batch.document_id)
        cases = list((await s.execute(select(TestCase).where(TestCase.batch_id == batch_id))).scalars().all())
        points = list((await s.execute(select(TestPoint).where(TestPoint.batch_id == batch_id))).scalars().all())
        return batch, doc, cases, points


def _dim_values(dimensions) -> list[str]:
    """dimensions 字段可能是 list[str] / dict / list[dict]，统一抽成字符串标签"""
    out: list[str] = []
    if isinstance(dimensions, list):
        for d in dimensions:
            if isinstance(d, str):
                out.append(d)
            elif isinstance(d, dict):
                out.append(str(d.get("name") or d.get("dimension") or d.get("type") or d))
    elif isinstance(dimensions, dict):
        out.extend(str(k) for k in dimensions.keys())
    return out


def overview(batch, doc, cases, points) -> None:
    active = [c for c in cases if c.review_status != "deleted"]
    dups = [c for c in active if c.duplicate_of is not None]
    print("=" * 70)
    print(f"批次: {batch.id}  状态={batch.status}  total_cases={batch.total_cases}")
    print("generation_config:", json.dumps(batch.generation_config, ensure_ascii=False, sort_keys=True))
    print(f"文档: {doc.title}  id={doc.id}")
    print(f"PRD content 字符数: {len(doc.content or '')}")
    caps = doc.image_captions or {}
    n_caps = len(caps) if isinstance(caps, (dict, list)) else 0
    print(f"image_captions 条数: {n_caps}")
    print("-" * 70)
    print(f"用例总数(含deleted): {len(cases)}   有效(非deleted): {len(active)}   其中近重复: {len(dups)}")
    print(f"测试点总数: {len(points)}")
    print("-" * 70)
    print("verdict 分布:", dict(Counter(c.verdict for c in active)))
    print("bucket  分布:", dict(Counter(c.bucket for c in active)))
    print("priority分布:", dict(Counter(c.priority for c in active)))
    print("review  分布:", dict(Counter(c.review_status for c in active)))
    print("trust   分布:", dict(Counter(c.trust_level for c in active)))
    dim_counter: Counter = Counter()
    for c in active:
        for d in _dim_values(c.dimensions):
            dim_counter[d] += 1
    print("用例维度分布(top20):", dim_counter.most_common(20))
    print("测试点维度分布:", dict(Counter(p.dimension for p in points)))
    print("-" * 70)
    prov_keys: Counter = Counter()
    for c in active:
        for k in (c.provenance or {}).keys():
            prov_keys[k] += 1
    print("provenance keys:", dict(prov_keys))
    print("-" * 70)
    source_counter: Counter = Counter(_source_section_of_case(c) for c in active)
    case_records = [_case_to_dict(c) for c in active]
    source_ref_counter: Counter = Counter(ref for record in case_records for ref in source_refs_of(record))
    business_counter: Counter = Counter(classify_case_for_audit(record)["business_module"] for record in case_records)
    business_module_count = len([name for name in business_counter if name != "_review_required"])
    print(f"业务模块总数(不含_review_required): {business_module_count}")
    print("各业务模块用例数(降序):")
    for name, cnt in business_counter.most_common():
        print(f"  {cnt:>4}  {name}")
    print(f"主 source_section 总数: {len(source_counter)}")
    print(f"source_ref 反查坐标总数: {len(source_ref_counter)}")
    print("-" * 70)
    if active:
        print("样本用例(完整结构):")
        print(json.dumps(_case_to_dict(active[0]), ensure_ascii=False, indent=2)[:2500])
    if points:
        print("-" * 70)
        print("样本测试点(完整结构):")
        print(json.dumps(_point_to_dict(points[0]), ensure_ascii=False, indent=2)[:1200])


def _excerpt(c: TestCase, n: int = 70) -> str:
    prov = c.provenance or {}
    s = (prov.get("verbatim_excerpt") or "").replace("\n", " ").replace("|", "/")
    return (s[:n] + "…") if len(s) > n else s


def _brief_row(line_no: int, c: TestCase) -> str:
    dims = "/".join(_dim_values(c.dimensions)) or "-"
    dup = "✓" if c.duplicate_of is not None else ""
    n_steps = len(c.steps) if isinstance(c.steps, list) else "?"
    title = (c.title or "").replace("\n", " ").replace("|", "/")
    return (
        f"| {line_no} | {c.priority} | {c.verdict or '-'} | {c.bucket or '-'} | {dup} | "
        f"{n_steps} | {dims} | {title} | {_excerpt(c)} |"
    )


def _excerpt_record(record: dict, n: int = 70) -> str:
    prov = record.get("provenance") or {}
    s = (prov.get("verbatim_excerpt") or "").replace("\n", " ").replace("|", "/")
    return (s[:n] + "…") if len(s) > n else s


def _brief_row_record(line_no: int, record: dict) -> str:
    dims = "/".join(_dim_values(record.get("dimensions"))) or "-"
    dup = "✓" if record.get("duplicate_of") else ""
    steps = record.get("steps")
    n_steps = len(steps) if isinstance(steps, list) else "?"
    title = str(record.get("title") or "").replace("\n", " ").replace("|", "/")
    return (
        f"| {line_no} | {record.get('priority') or '-'} | {record.get('verdict') or '-'} | "
        f"{record.get('bucket') or '-'} | {dup} | {n_steps} | {dims} | {title} | {_excerpt_record(record)} |"
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _source_sections_for_records(records: list[dict]) -> list[str]:
    out: list[str] = []
    for record in records:
        for ref in source_refs_of(record):
            if ref not in out:
                out.append(ref)
    return out


def _matched_prd_blocks(source_refs: list[str], sections: list[dict]) -> str:
    blocks: list[str] = []
    seen: set[str] = set()
    for ref in source_refs:
        body = _match_section(ref, sections)
        if body and body not in seen:
            seen.add(body)
            blocks.append(f"### {ref}\n\n{body}")
    return "\n\n---\n\n".join(blocks)


def _brief_for_records(
    *,
    title: str,
    records: list[dict],
    points_by_id: dict[str, dict],
    sections: list[dict],
) -> str:
    tp_ids: list[str] = []
    seen_tp: set[str] = set()
    for record in records:
        tid = record.get("test_point_id")
        if tid and tid in points_by_id and tid not in seen_tp:
            seen_tp.add(tid)
            tp_ids.append(tid)
    mod_points = [points_by_id[tid] for tid in tp_ids]
    feat_ids = sorted({p["feature_id"] for p in mod_points})
    source_refs = _source_sections_for_records(records)
    prd_blocks = _matched_prd_blocks(source_refs, sections)
    tp_lines = (
        "\n".join(f"- [{p['feature_id']}][{p['dimension']}][{p['priority']}] {p['description']}" for p in mod_points)
        or "（无关联测试点）"
    )
    rows = "\n".join(_brief_row_record(n, record) for n, record in enumerate(records, start=1))
    return f"""# 审查包：{title}

## 1. 统计画像
- 用例数：{len(records)}（近重复 {sum(1 for record in records if record.get("duplicate_of"))}）
- verdict 分布：{dict(Counter(record.get("verdict") for record in records))}
- bucket 分布：{dict(Counter(record.get("bucket") for record in records))}
- priority 分布：{dict(Counter(record.get("priority") for record in records))}
- 关联测试点：{len(mod_points)}（feature: {feat_ids}）
- 需求证据坐标：{len(source_refs)} 个 source_ref
- PRD 章节匹配：{"是" if prd_blocks else "否（重点判断是否幻觉/凭空生成或映射规则缺失）"}

## 2. PRD 章节原文（含图片 AI 描述；这是审查的事实基准）
{prd_blocks or "（未匹配到 PRD 章节原文）"}

## 3. 关联测试点（{len(mod_points)} 条）
{tp_lines}

## 4. 用例一览（共 {len(records)} 条；「行」= cases.jsonl 的行号，精读用 Read 读对应行）
| 行 | P | verdict | bucket | 重复 | 步数 | 维度 | 标题 | PRD引用(截断) |
|----|---|---------|--------|------|------|------|------|--------------|
{rows}
"""


def build_audit_tree(records: list[dict]) -> dict:
    """按审查分类构建业务模块树与 source-section 反查索引。"""
    modules: dict[str, dict] = {}
    source_sections: dict[str, list[dict]] = defaultdict(list)
    unresolved: list[dict] = []

    for raw in records:
        record = _with_audit_classification(raw)
        cls = record["audit_classification"]
        source_refs = cls["source_refs"] or [_source_section_of_record(record)]
        for source_ref in source_refs:
            source_sections[source_ref].append(record)
        if cls["business_module"] == "_review_required":
            unresolved.append(record)
            continue
        mod = modules.setdefault(
            cls["business_module"],
            {
                "module_name": cls["business_module"],
                "case_records": [],
                "branches": defaultdict(list),
                "source_sections": set(),
            },
        )
        mod["case_records"].append(record)
        mod["branches"][tuple(cls["branch_path"])].append(record)
        mod["source_sections"].update(cls["source_refs"])

    return {
        "modules": modules,
        "source_sections": source_sections,
        "unresolved": unresolved,
    }


def _record_sort_key(record: dict) -> tuple[int, str, str]:
    return (
        PRIORITY_RANK.get(str(record.get("priority") or ""), 99),
        str(record.get("title") or ""),
        str(record.get("id") or ""),
    )


def _branch_quality_flags(branch_path: tuple[str, ...] | list[str]) -> list[str]:
    flags: list[str] = []
    parts = [str(part or "").strip() for part in branch_path]
    if not parts or any(not part for part in parts):
        flags.append("empty_branch")
    if "通用规则" in parts:
        flags.append("generic_branch")
    if "unresolved" in parts:
        flags.append("unresolved_branch_inside_module")
    if any(re.fullmatch(r"\d+[）).．]?", part) for part in parts):
        flags.append("heading_fragment")
    if any(part.startswith(("→", "-", "—", "/")) for part in parts):
        flags.append("heading_artifact")
    return flags


def _calibration_sample_target(case_count: int) -> int:
    if case_count >= CALIBRATION_LARGE_MODULE_THRESHOLD:
        return CALIBRATION_LARGE_MODULE_SAMPLE
    return CALIBRATION_BASE_SAMPLE


def _round_robin_branch_sample(
    branch_records: list[tuple[tuple[str, ...], list[dict]]],
    target: int,
) -> list[tuple[tuple[str, ...], dict]]:
    ordered_groups = [
        (branch_path, sorted(records, key=_record_sort_key)) for branch_path, records in branch_records if records
    ]
    ordered_groups.sort(
        key=lambda item: (
            0 if _branch_quality_flags(item[0]) else 1,
            -len(item[1]),
            item[0],
        )
    )

    selected: list[tuple[tuple[str, ...], dict]] = []
    selected_ids: set[str] = set()
    depth = 0
    while len(selected) < target:
        progressed = False
        for branch_path, records in ordered_groups:
            if depth >= len(records):
                continue
            record = records[depth]
            record_id = str(record.get("id") or "")
            if record_id in selected_ids:
                continue
            selected.append((branch_path, record))
            selected_ids.add(record_id)
            progressed = True
            if len(selected) >= target:
                break
        if not progressed:
            break
        depth += 1
    return selected


def _calibration_review_template() -> dict:
    return {
        "module_correct": None,
        "corrected_module": "",
        "branch_correct": None,
        "corrected_branch_path": [],
        "should_be_review_required": None,
        "review_notes": "",
    }


def _sample_payload(
    *,
    sample_id: str,
    module_name: str,
    branch_path: tuple[str, ...],
    record: dict,
) -> dict:
    cls = record.get("audit_classification") or {}
    source_refs = cls.get("source_refs") or source_refs_of(record)
    prov = record.get("provenance") or {}
    return {
        "sample_id": sample_id,
        "case_id": record.get("id"),
        "title": record.get("title"),
        "priority": record.get("priority"),
        "verdict": record.get("verdict"),
        "bucket": record.get("bucket"),
        "dimensions": _dim_values(record.get("dimensions")),
        "business_module": module_name,
        "branch_path": list(branch_path),
        "classification_reason": cls.get("classification_reason"),
        "classification_confidence": cls.get("classification_confidence"),
        "cross_cutting_tags": cls.get("cross_cutting_tags") or [],
        "quality_flags": _branch_quality_flags(branch_path),
        "source_refs": source_refs,
        "verbatim_excerpt": prov.get("verbatim_excerpt") or "",
        "review": _calibration_review_template(),
        "case": record,
    }


def build_calibration_review(
    tree: dict,
) -> dict:
    """构建模块树校准包数据，不写盘。

    校准包是 taxonomy 产品化前的验证层：按模块和分支分层抽样，暴露可疑
    branch，并给人工 review 预留结构化标注字段。
    """
    samples: list[dict] = []
    modules: list[dict] = []
    sample_seq = 1

    module_items = sorted(
        tree["modules"].items(),
        key=lambda kv: len(kv[1]["case_records"]),
        reverse=True,
    )
    for module_name, module_data in module_items:
        target = _calibration_sample_target(len(module_data["case_records"]))
        branch_items = sorted(module_data["branches"].items(), key=lambda kv: (-len(kv[1]), kv[0]))
        selected = _round_robin_branch_sample(branch_items, target)

        module_samples: list[str] = []
        branch_meta: list[dict] = []
        selected_by_branch = Counter(tuple(branch_path) for branch_path, _record in selected)
        for branch_path, records in branch_items:
            flags = _branch_quality_flags(branch_path)
            branch_meta.append(
                {
                    "branch_path": list(branch_path),
                    "case_count": len(records),
                    "sample_count": selected_by_branch[tuple(branch_path)],
                    "quality_flags": flags,
                    "examples": [record.get("title") for record in sorted(records, key=_record_sort_key)[:3]],
                }
            )

        for branch_path, record in selected:
            sample_id = f"CAL-{sample_seq:04d}"
            sample_seq += 1
            samples.append(
                _sample_payload(
                    sample_id=sample_id,
                    module_name=module_name,
                    branch_path=branch_path,
                    record=record,
                )
            )
            module_samples.append(sample_id)

        modules.append(
            {
                "module_name": module_name,
                "case_count": len(module_data["case_records"]),
                "branch_count": len(branch_items),
                "sample_target": target,
                "sample_count": len(module_samples),
                "sample_ids": module_samples,
                "quality_flag_count": sum(1 for branch in branch_meta if branch["quality_flags"]),
                "branches": branch_meta,
            }
        )

    unresolved_records = sorted(tree["unresolved"], key=_record_sort_key)
    unresolved_target = min(CALIBRATION_BASE_SAMPLE, len(unresolved_records))
    unresolved_samples: list[str] = []
    for record in unresolved_records[:unresolved_target]:
        sample_id = f"CAL-{sample_seq:04d}"
        sample_seq += 1
        samples.append(
            _sample_payload(
                sample_id=sample_id,
                module_name="_review_required",
                branch_path=("unresolved_module",),
                record=record,
            )
        )
        unresolved_samples.append(sample_id)

    dirty_branch_count = sum(
        1
        for module in modules
        for branch in module["branches"]
        if any(flag not in {"generic_branch"} for flag in branch["quality_flags"])
    )
    generic_branch_count = sum(
        1 for module in modules for branch in module["branches"] if "generic_branch" in branch["quality_flags"]
    )
    return {
        "calibration_schema_version": CALIBRATION_SCHEMA_VERSION,
        "gate_targets": CALIBRATION_GATE_TARGETS,
        "module_count": len(modules),
        "sample_count": len(samples),
        "unresolved_count": len(unresolved_records),
        "unresolved_sample_count": len(unresolved_samples),
        "dirty_branch_name_count": dirty_branch_count,
        "generic_branch_count": generic_branch_count,
        "modules": modules,
        "unresolved_sample_ids": unresolved_samples,
        "samples": samples,
    }


def _taxonomy_candidate(tree: dict, calibration: dict) -> dict:
    rule_by_module = {rule["module"]: rule for rule in module_tree_classifier.MODULE_RULES}
    modules: list[dict] = []
    for module in calibration["modules"]:
        rule = rule_by_module.get(module["module_name"], {})
        modules.append(
            {
                "module_name": module["module_name"],
                "aliases": list(rule.get("aliases", [])),
                "section_prefixes": list(rule.get("section_prefixes", [])),
                "case_count": module["case_count"],
                "branch_count": module["branch_count"],
                "quality_flag_count": module["quality_flag_count"],
                "branches": module["branches"],
            }
        )
    return {
        "taxonomy_schema_version": 1,
        "source": "src.testcase_generator.services.module_tree_classifier deterministic rules",
        "review_status": "candidate_needs_calibration",
        "modules": modules,
        "unresolved": {
            "case_count": len(tree["unresolved"]),
            "sample_ids": calibration["unresolved_sample_ids"],
        },
    }


def _calibration_markdown_for_samples(title: str, samples: list[dict]) -> str:
    table_header = (
        "| sample_id | P | verdict | 当前模块 | 当前分支 | 标记 | 用例标题 | 主证据坐标 | "
        "module_correct | corrected_module | branch_correct | corrected_branch_path | review_notes |"
    )
    row_template = (
        "| {sample_id} | {priority} | {verdict} | {module} | {branch} | {flags} | {case_title} | {source} | | | | | |"
    )
    rows = "\n".join(
        row_template.format(
            sample_id=sample["sample_id"],
            priority=sample.get("priority") or "-",
            verdict=sample.get("verdict") or "-",
            module=sample["business_module"],
            branch=" / ".join(sample["branch_path"]),
            flags=", ".join(sample["quality_flags"]) or "-",
            case_title=str(sample.get("title") or "").replace("|", "/"),
            source=str((sample.get("source_refs") or ["-"])[0]).replace("|", "/"),
        )
        for sample in samples
    )
    return f"""# 模块树校准样本：{title}

请逐行填写最后 5 列。`module_correct` / `branch_correct` 填 `Y` 或 `N`；
不确定时在 `review_notes` 写原因，不要强行判对。

{table_header}
|---|---|---|---|---|---|---|---|---|---|---|---|---|
{rows}
"""


def _calibration_readme(calibration: dict) -> str:
    targets = calibration["gate_targets"]
    return f"""# 模块树校准审查包

本目录用于验证候选业务模块树，不是最终产品化数据。校准通过前，不应把
`business_module` / `branch_path` 写入 DB，也不应接 API/UI。

## 文件说明

- `calibration_samples.jsonl`：结构化样本，含完整 case 和人工标注空位。
- `samples/*.md`：按模块拆分的人读审查表。
- `taxonomy_candidate.json`：当前规则候选、观测分支、质量标记和样例。
- `prd.md` / `image_captions.json`：审查事实基准。

## 验收门槛

- 顶层模块准确率目标：{targets["module_accuracy"]:.0%}
- branch 准确率目标：{targets["branch_accuracy"]:.0%}
- 脏 branch 名目标：{targets["dirty_branch_name_count"]}

## 当前画像

- 业务模块数：{calibration["module_count"]}
- 抽样数：{calibration["sample_count"]}
- unresolved 用例数：{calibration["unresolved_count"]}
- 脏 branch 名数量：{calibration["dirty_branch_name_count"]}
- 通用 branch 数量：{calibration["generic_branch_count"]}

## 审查方法

1. 先看 `taxonomy_candidate.json`，确认顶层模块和 branch 命名是否符合产品心智。
2. 再逐个打开 `samples/*.md`，按样本标注顶层模块和 branch 是否正确。
3. 把错误样本归因到规则：别名过宽、章节兜底错误、branch 规则缺失、PRD 证据不足。
4. 未达门槛时，只修规则并重新生成校准包；不要持久化 taxonomy。
"""


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _clear_generated_dirs(out_dir: Path) -> None:
    for name in ("modules", "by_source_section", "_review_required"):
        path = out_dir / name
        if path.exists():
            shutil.rmtree(path)


def _clear_calibration_outputs(out_dir: Path) -> None:
    for name in ("samples",):
        path = out_dir / name
        if path.exists():
            shutil.rmtree(path)
    for name in (
        "README.md",
        "index.json",
        "taxonomy_candidate.json",
        "calibration_samples.jsonl",
        "prd.md",
        "image_captions.json",
    ):
        path = out_dir / name
        if path.exists():
            path.unlink()


def _write_source_section_exports(
    *,
    tree: dict,
    out_dir: Path,
    points_by_id: dict[str, dict],
    sections: list[dict],
) -> list[dict]:
    source_dir = out_dir / "by_source_section"
    source_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    groups = sorted(tree["source_sections"].items(), key=lambda kv: len(kv[1]), reverse=True)
    for i, (source_section, records) in enumerate(groups, start=1):
        slug = f"{i:02d}__{_safe_name(source_section)}"
        jsonl_path = source_dir / f"{slug}.cases.jsonl"
        brief_path = source_dir / f"{slug}.brief.md"
        _write_jsonl(jsonl_path, records)
        brief_path.write_text(
            _brief_for_records(
                title=f"source_section 反查：{source_section}",
                records=records,
                points_by_id=points_by_id,
                sections=sections,
            ),
            encoding="utf-8",
        )
        modules = sorted({r["audit_classification"]["business_module"] for r in records})
        index.append(
            {
                "source_section": source_section,
                "slug": slug,
                "brief": _rel(brief_path, out_dir),
                "jsonl": _rel(jsonl_path, out_dir),
                "case_count": len(records),
                "business_modules": modules,
                "verdict_dist": dict(Counter(record.get("verdict") for record in records)),
            }
        )
    return index


def _write_calibration_exports(
    *,
    tree: dict,
    out_dir: Path,
    doc_content: str,
    image_captions,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_calibration_outputs(out_dir)

    calibration = build_calibration_review(tree)
    taxonomy = _taxonomy_candidate(tree, calibration)
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "README.md").write_text(_calibration_readme(calibration), encoding="utf-8")
    (out_dir / "prd.md").write_text(doc_content or "", encoding="utf-8")
    (out_dir / "image_captions.json").write_text(
        json.dumps(image_captions or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "taxonomy_candidate.json").write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_jsonl(out_dir / "calibration_samples.jsonl", calibration["samples"])

    samples_by_module: dict[str, list[dict]] = defaultdict(list)
    for sample in calibration["samples"]:
        samples_by_module[sample["business_module"]].append(sample)
    for i, (module_name, samples) in enumerate(
        sorted(samples_by_module.items(), key=lambda kv: (-len(kv[1]), kv[0])),
        start=1,
    ):
        path = samples_dir / f"{i:02d}__{_safe_name(module_name)}.md"
        path.write_text(
            _calibration_markdown_for_samples(module_name, samples),
            encoding="utf-8",
        )

    index_payload = dict(calibration)
    index_payload.pop("samples", None)
    index_payload["taxonomy"] = "taxonomy_candidate.json"
    index_payload["samples_jsonl"] = "calibration_samples.jsonl"
    index_payload["sample_markdown_dir"] = "samples"
    (out_dir / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_payload


def _write_unresolved_exports(
    *,
    tree: dict,
    out_dir: Path,
    points_by_id: dict[str, dict],
    sections: list[dict],
) -> dict:
    records = tree["unresolved"]
    review_dir = out_dir / "_review_required" / "unresolved_module"
    review_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = review_dir / "cases.jsonl"
    brief_path = review_dir / "brief.md"
    _write_jsonl(jsonl_path, records)
    brief_path.write_text(
        _brief_for_records(
            title="_review_required/unresolved_module",
            records=records,
            points_by_id=points_by_id,
            sections=sections,
        ),
        encoding="utf-8",
    )
    reasons = Counter(
        (record.get("audit_classification") or {}).get("classification_reason", "unknown") for record in records
    )
    non_duplicate_records = _non_duplicate_records(records)
    return {
        "case_count": len(records),
        "non_duplicate_case_count": len(non_duplicate_records),
        "brief": _rel(brief_path, out_dir),
        "jsonl": _rel(jsonl_path, out_dir),
        "reasons": dict(reasons),
        "bucket_dist": _dist(records, "bucket"),
        "non_duplicate_bucket_dist": _dist(non_duplicate_records, "bucket"),
        "priority_dist": _dist(records, "priority"),
        "non_duplicate_priority_dist": _dist(non_duplicate_records, "priority"),
        "verdict_dist": _dist(records, "verdict"),
        "non_duplicate_verdict_dist": _dist(non_duplicate_records, "verdict"),
    }


def _write_business_module_exports(
    *,
    tree: dict,
    out_dir: Path,
    points_by_id: dict[str, dict],
    sections: list[dict],
) -> list[dict]:
    modules_dir = out_dir / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    module_index: list[dict] = []
    module_items = sorted(
        tree["modules"].items(),
        key=lambda kv: len(kv[1]["case_records"]),
        reverse=True,
    )
    for i, (module_name, module_data) in enumerate(module_items, start=1):
        module_slug = f"{i:02d}__{_safe_name(module_name)}"
        module_dir = modules_dir / module_slug
        branches_dir = module_dir / "branches"
        branches_dir.mkdir(parents=True, exist_ok=True)

        branch_index: list[dict] = []
        branch_items = sorted(
            module_data["branches"].items(),
            key=lambda kv: (len(kv[0]), -len(kv[1]), kv[0]),
        )
        for branch_path, records in branch_items:
            branch_dir = branches_dir
            for part in branch_path:
                branch_dir = branch_dir / _safe_name(part)
            branch_dir.mkdir(parents=True, exist_ok=True)
            jsonl_path = branch_dir / "cases.jsonl"
            brief_path = branch_dir / "brief.md"
            _write_jsonl(jsonl_path, records)
            brief_path.write_text(
                _brief_for_records(
                    title=f"{module_name} / {' / '.join(branch_path)}",
                    records=records,
                    points_by_id=points_by_id,
                    sections=sections,
                ),
                encoding="utf-8",
            )
            branch_index.append(
                {
                    "branch_path": list(branch_path),
                    "brief": _rel(brief_path, out_dir),
                    "jsonl": _rel(jsonl_path, out_dir),
                    "case_count": len(records),
                    "source_sections": _source_sections_for_records(records),
                    "verdict_dist": dict(Counter(record.get("verdict") for record in records)),
                }
            )

        module_meta = {
            "module_name": module_name,
            "slug": module_slug,
            "dir": _rel(module_dir, out_dir),
            "case_count": len(module_data["case_records"]),
            "branch_count": len(branch_index),
            "source_sections": sorted(module_data["source_sections"]),
            "duplicate_count": sum(1 for record in module_data["case_records"] if record.get("duplicate_of")),
            "verdict_dist": dict(Counter(record.get("verdict") for record in module_data["case_records"])),
            "branches": branch_index,
        }
        (module_dir / "module.json").write_text(
            json.dumps(module_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        module_index.append(module_meta)
    return module_index


def _non_duplicate_records(records: list[dict]) -> list[dict]:
    return [record for record in records if not record.get("duplicate_of")]


def _dist(records: list[dict], field: str) -> dict:
    return dict(Counter(record.get(field) for record in records))


def _one_step_count(records: list[dict]) -> int:
    return sum(1 for record in records if len(record.get("steps") or []) == 1)


def _max_cases_per_test_point(records: list[dict]) -> int:
    counts = Counter(record.get("test_point_id") for record in records if record.get("test_point_id"))
    return max(counts.values(), default=0)


def _record_text(record: dict) -> str:
    parts: list[str] = [
        str(record.get("title") or ""),
        " ".join(str(item or "") for item in record.get("preconditions") or []),
        " ".join(str(item or "") for item in record.get("expected_results") or []),
    ]
    for step in record.get("steps") or []:
        if isinstance(step, dict):
            parts.extend(
                [
                    str(step.get("action") or ""),
                    str(step.get("input_data") or ""),
                    str(step.get("expected_result") or ""),
                ]
            )
    prov = record.get("provenance") or {}
    parts.append(str(prov.get("verbatim_excerpt") or ""))
    parts.extend(source_refs_of(record))
    return " ".join(parts)


def _business_module_of_record(record: dict) -> str:
    cls = record.get("audit_classification") or classify_case_for_audit(record)
    return str(cls.get("business_module") or "_unknown")


def _record_has_structural_signal(record: dict, text: str) -> bool:
    return has_structural_signal(_dim_values(record.get("dimensions")), text)


def _record_sample(record: dict) -> dict:
    cls = record.get("audit_classification") or classify_case_for_audit(record)
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "priority": record.get("priority"),
        "bucket": record.get("bucket"),
        "verdict": record.get("verdict"),
        "review_issue_type": _review_issue_type_of_record(record),
        "business_module": cls.get("business_module"),
        "branch_path": cls.get("branch_path") or [],
    }


def _sample_records(records: list[dict], limit: int = 10) -> list[dict]:
    return [_record_sample(record) for record in sorted(records, key=_record_sort_key)[:limit]]


def _review_issue_type_of_record(record: dict) -> str | None:
    direct_value = record.get("review_issue_type")
    if direct_value:
        return str(direct_value)

    verification = record.get("verification") or {}
    if isinstance(verification, dict):
        value = verification.get("review_issue_type")
        if value:
            return str(value)
    return None


def _review_issue_type_dist(records: list[dict]) -> dict[str, int]:
    return dict(Counter(issue for record in records if (issue := _review_issue_type_of_record(record))))


def _critical_flow_coverage(records: list[dict]) -> dict:
    coverage: dict[str, dict] = {}
    for flow_name, tokens in CRITICAL_FLOW_PATTERNS.items():
        matched = [
            record
            for record in records
            if any(
                source_ref_matches_token(source_ref, token) for source_ref in source_refs_of(record) for token in tokens
            )
        ]
        p0_records = [record for record in matched if record.get("priority") == "P0"]
        main_grounded_records = [
            record for record in matched if record.get("bucket") == "main" and record.get("verdict") == "grounded"
        ]
        coverage[flow_name] = {
            "case_count": len(matched),
            "p0_count": len(p0_records),
            "main_grounded_count": len(main_grounded_records),
            "bucket_dist": _dist(matched, "bucket"),
            "verdict_dist": _dist(matched, "verdict"),
            "modules": dict(Counter(_business_module_of_record(record) for record in matched)),
            "sample_case_ids": [str(record.get("id")) for record in sorted(matched, key=_record_sort_key)[:10]],
        }
    return coverage


def _quality_diagnostics(records: list[dict]) -> dict:
    p0_records = [record for record in records if record.get("priority") == "P0"]
    review_required_records = [record for record in records if _business_module_of_record(record) == "_review_required"]
    texts_by_record_id = {id(record): _record_text(record) for record in records}

    display_like_records = [
        record for record in records if has_display_or_existence_signal(texts_by_record_id[id(record)])
    ]
    low_value_display_records = [
        record
        for record in display_like_records
        if is_low_value_display_case(
            title=str(record.get("title") or ""),
            expected_results=[str(item or "") for item in record.get("expected_results") or []],
            step_expected_results=[
                str(step.get("expected_result") or "") for step in record.get("steps") or [] if isinstance(step, dict)
            ],
            dimensions=_dim_values(record.get("dimensions")),
        )
    ]
    vague_expected_records = [
        record
        for record in records
        if has_vague_assertion_signal(
            " ".join(str(item or "") for item in record.get("expected_results") or [])
            + " "
            + " ".join(
                str(step.get("expected_result") or "") for step in record.get("steps") or [] if isinstance(step, dict)
            )
        )
    ]
    pure_vague_expected_records = [
        record
        for record in records
        if is_pure_vague_assertion_case(
            [str(item or "") for item in record.get("expected_results") or []],
            [str(step.get("expected_result") or "") for step in record.get("steps") or [] if isinstance(step, dict)],
        )
    ]

    display_like_record_ids = {id(record) for record in display_like_records}
    low_value_display_record_ids = {id(record) for record in low_value_display_records}
    review_required_record_ids = {id(record) for record in review_required_records}

    p0_display_like_records = [record for record in p0_records if id(record) in display_like_record_ids]
    p0_low_value_display_records = [record for record in p0_records if id(record) in low_value_display_record_ids]
    p0_structural_records = [
        record for record in p0_records if _record_has_structural_signal(record, texts_by_record_id[id(record)])
    ]
    p0_business_risk_records = [
        record for record in p0_records if has_business_risk_signal(texts_by_record_id[id(record)])
    ]
    p0_review_required_records = [record for record in p0_records if id(record) in review_required_record_ids]
    review_issue_records = [record for record in records if _review_issue_type_of_record(record)]

    return {
        "case_count": len(records),
        "by_review_issue_type": _review_issue_type_dist(records),
        "p0_count": len(p0_records),
        "p0_ratio": round(len(p0_records) / len(records), 4) if records else 0,
        "p0_by_bucket": _dist(p0_records, "bucket"),
        "p0_by_verdict": _dist(p0_records, "verdict"),
        "p0_by_review_issue_type": _review_issue_type_dist(p0_records),
        "p0_by_business_module": dict(Counter(_business_module_of_record(record) for record in p0_records)),
        "p0_needs_spec_count": sum(1 for record in p0_records if record.get("bucket") == "needs_spec"),
        "p0_to_fix_count": sum(1 for record in p0_records if record.get("bucket") == "to_fix"),
        "p0_review_required_count": len(p0_review_required_records),
        "p0_structural_signal_count": len(p0_structural_records),
        "p0_business_risk_signal_count": len(p0_business_risk_records),
        "p0_display_like_count": len(p0_display_like_records),
        "p0_low_value_display_like_count": len(p0_low_value_display_records),
        "display_like_count": len(display_like_records),
        "low_value_display_like_count": len(low_value_display_records),
        "vague_expected_count": len(vague_expected_records),
        "pure_vague_expected_count": len(pure_vague_expected_records),
        "review_required_count": len(review_required_records),
        "critical_flow_coverage": _critical_flow_coverage(records),
        "samples": {
            "p0_low_value_display_like": _sample_records(p0_low_value_display_records),
            "vague_expected": _sample_records(vague_expected_records),
            "pure_vague_expected": _sample_records(pure_vague_expected_records),
            "p0_review_required": _sample_records(p0_review_required_records),
            "review_issue_type": _sample_records(review_issue_records),
        },
    }


def _stable_execution_records(records: list[dict]) -> list[dict]:
    """用例库默认执行视图：main + grounded + 非重复 + 非待分类。"""
    non_duplicate_records = _non_duplicate_records(records)
    return [
        record
        for record in non_duplicate_records
        if record.get("bucket") == "main"
        and record.get("verdict") == "grounded"
        and _business_module_of_record(record) != "_review_required"
    ]


def _dump_case_records(
    *,
    batch_id: str,
    document_id: str,
    document_title: str,
    generation_config,
    doc_content: str,
    image_captions,
    case_records: list[dict],
    point_records: list[dict],
    out_dir: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated_dirs(out_dir)
    case_records = [_with_audit_classification(record) for record in case_records]

    # PRD 原文（含图片 AI 描述，parse 阶段已插回 content）
    (out_dir / "prd.md").write_text(doc_content or "", encoding="utf-8")
    (out_dir / "image_captions.json").write_text(
        json.dumps(image_captions or {}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 解析 PRD 章节树（供每个模块挂对应原文块）
    sections = _parse_prd_sections(doc_content or "")

    # 测试点按 id 索引（用例通过外键 test_point_id 关联，而非 provenance）
    points_by_id: dict[str, dict] = {p["id"]: p for p in point_records}
    tree = build_audit_tree(case_records)
    module_index = _write_business_module_exports(
        tree=tree,
        out_dir=out_dir,
        points_by_id=points_by_id,
        sections=sections,
    )
    source_index = _write_source_section_exports(
        tree=tree,
        out_dir=out_dir,
        points_by_id=points_by_id,
        sections=sections,
    )
    unresolved_index = _write_unresolved_exports(
        tree=tree,
        out_dir=out_dir,
        points_by_id=points_by_id,
        sections=sections,
    )

    dim_counter: Counter = Counter()
    for record in case_records:
        for d in _dim_values(record.get("dimensions")):
            dim_counter[d] += 1
    non_duplicate_records = _non_duplicate_records(case_records)
    non_duplicate_dim_counter: Counter = Counter()
    for record in non_duplicate_records:
        for d in _dim_values(record.get("dimensions")):
            non_duplicate_dim_counter[d] += 1
    stable_execution_records = _stable_execution_records(case_records)
    quality_diagnostics = {
        "all": _quality_diagnostics(case_records),
        "non_duplicate": _quality_diagnostics(non_duplicate_records),
        "stable": _quality_diagnostics(stable_execution_records),
    }

    index_payload = {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "batch_id": batch_id,
        "document_id": document_id,
        "document_title": document_title,
        "generation_config": generation_config,
        "prd_chars": len(doc_content or ""),
        "image_caption_count": len(image_captions or {}),
        "active_case_count": len(case_records),
        "duplicate_count": sum(1 for record in case_records if record.get("duplicate_of")),
        "non_duplicate_case_count": len(non_duplicate_records),
        "stable_execution_case_count": len(stable_execution_records),
        "one_step_case_count": _one_step_count(case_records),
        "non_duplicate_one_step_case_count": _one_step_count(non_duplicate_records),
        "stable_execution_one_step_case_count": _one_step_count(stable_execution_records),
        "max_cases_per_test_point": _max_cases_per_test_point(case_records),
        "non_duplicate_max_cases_per_test_point": _max_cases_per_test_point(non_duplicate_records),
        "test_point_count": len(point_records),
        "module_count": len(module_index),
        "source_section_count": len(source_index),
        "source_ref_count": len(source_index),
        "unresolved_module_count": unresolved_index["case_count"],
        "non_duplicate_unresolved_module_count": unresolved_index["non_duplicate_case_count"],
        "bucket_dist": _dist(case_records, "bucket"),
        "non_duplicate_bucket_dist": _dist(non_duplicate_records, "bucket"),
        "verdict_dist": _dist(case_records, "verdict"),
        "non_duplicate_verdict_dist": _dist(non_duplicate_records, "verdict"),
        "review_issue_type_dist": _review_issue_type_dist(case_records),
        "non_duplicate_review_issue_type_dist": _review_issue_type_dist(non_duplicate_records),
        "priority_dist": _dist(case_records, "priority"),
        "non_duplicate_priority_dist": _dist(non_duplicate_records, "priority"),
        "dimension_dist": dict(dim_counter.most_common()),
        "non_duplicate_dimension_dist": dict(non_duplicate_dim_counter.most_common()),
        "quality_diagnostics": quality_diagnostics,
        "modules": module_index,
        "source_sections": source_index,
        "review_required": {
            "unresolved_module": unresolved_index,
        },
    }
    (out_dir / "index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_payload


def _dump_calibration_records(
    *,
    doc_content: str,
    image_captions,
    case_records: list[dict],
    out_dir: Path,
) -> dict:
    tree = build_audit_tree(case_records)
    return _write_calibration_exports(
        tree=tree,
        out_dir=out_dir,
        doc_content=doc_content,
        image_captions=image_captions,
    )


def dump(batch, doc, cases, points, out_dir: Path) -> None:
    active = [c for c in cases if c.review_status != "deleted"]
    case_records = [_with_audit_classification(_case_to_dict(c)) for c in active]
    point_records = [_point_to_dict(p) for p in points]
    index_payload = _dump_case_records(
        batch_id=str(batch.id),
        document_id=str(doc.id),
        document_title=doc.title,
        generation_config=batch.generation_config,
        doc_content=doc.content or "",
        image_captions=doc.image_captions or {},
        case_records=case_records,
        point_records=point_records,
        out_dir=out_dir,
    )
    print(f"已落盘到: {out_dir}")
    print(f"  prd.md ({len(doc.content or '')} 字符), image_captions.json")
    print(f"  modules/ 共 {index_payload['module_count']} 个业务模块树")
    print(f"  by_source_section/ 共 {index_payload['source_ref_count']} 个 source_ref 反查包")
    print("  index.json (业务模块树 + source_ref 反查 + 全局统计)")


def dump_calibration(batch, doc, cases, out_dir: Path) -> None:
    active = [c for c in cases if c.review_status != "deleted"]
    case_records = [_case_to_dict(c) for c in active]
    index_payload = _dump_calibration_records(
        doc_content=doc.content or "",
        image_captions=doc.image_captions or {},
        case_records=case_records,
        out_dir=out_dir,
    )
    print(f"已生成模块树校准包: {out_dir}")
    print(f"  samples/ 共 {index_payload['sample_count']} 条校准样本")
    print("  taxonomy_candidate.json / calibration_samples.jsonl / README.md")
    print(f"  dirty_branch_name_count={index_payload['dirty_branch_name_count']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--dump", action="store_true", help="落盘到 .audit/<batch_id>/")
    ap.add_argument(
        "--calibrate",
        action="store_true",
        help="生成独立模块树校准包到 .audit/<batch_id>-module-tree-calibration/",
    )
    args = ap.parse_args()

    batch_id = UUID(args.batch_id)
    batch, doc, cases, points = await load(batch_id)

    if args.calibrate:
        dump_calibration(batch, doc, cases, ROOT / ".audit" / f"{batch_id}-module-tree-calibration")
    elif args.dump:
        dump(batch, doc, cases, points, ROOT / ".audit" / str(batch_id))
    else:
        overview(batch, doc, cases, points)


if __name__ == "__main__":
    asyncio.run(main())
