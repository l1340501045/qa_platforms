"""把 taxonomy replay 结果输出为可审查、可追溯的离线产物。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.testcase_generator.schemas.taxonomy import TaxonomyAssignmentSet, TaxonomyManifest
from src.testcase_generator.services.taxonomy_manifest import canonical_manifest_dict
from src.testcase_generator.services.taxonomy_replay import ReplayCaseResult, TaxonomyReplayResult


def write_replay_artifacts(
    *,
    output_dir: Path,
    result: TaxonomyReplayResult,
    assignments: TaxonomyAssignmentSet,
    manifest: TaxonomyManifest,
    replace_existing: bool = True,
    expected_anomaly_case_ids: frozenset[UUID] | None = None,
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-",
            dir=output_dir.parent,
        )
    )
    backup_dir: Path | None = None
    try:
        _write_replay_artifacts_to_dir(
            output_dir=staging_dir,
            result=result,
            assignments=assignments,
            manifest=manifest,
            expected_anomaly_case_ids=expected_anomaly_case_ids,
        )
        if output_dir.exists():
            if not replace_existing:
                raise FileExistsError(f"replay artifact output already exists: {output_dir}")
            if not output_dir.is_dir():
                raise NotADirectoryError(str(output_dir))
            backup_dir = output_dir.with_name(f".{output_dir.name}.backup-{uuid4().hex}")
            output_dir.rename(backup_dir)
        staging_dir.rename(output_dir)
    except Exception:
        if backup_dir is not None and backup_dir.exists() and not output_dir.exists():
            backup_dir.rename(output_dir)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    if backup_dir is not None:
        shutil.rmtree(backup_dir, ignore_errors=True)


def _write_replay_artifacts_to_dir(
    *,
    output_dir: Path,
    result: TaxonomyReplayResult,
    assignments: TaxonomyAssignmentSet,
    manifest: TaxonomyManifest,
    expected_anomaly_case_ids: frozenset[UUID] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(exist_ok=True)
    for old_sample in samples_dir.glob("*.md"):
        old_sample.unlink()

    _write_json(output_dir / "manifest.json", canonical_manifest_dict(manifest))
    assignment_payload = assignments.model_dump(mode="json", exclude_none=True)
    _write_json(output_dir / "assignment-set.json", assignment_payload)
    reviewed_assignment_path = output_dir / "reviewed-assignments.json"
    if assignments.approval_status == "approved":
        _write_json(reviewed_assignment_path, assignment_payload)
    elif reviewed_assignment_path.exists():
        reviewed_assignment_path.unlink()
    actual_anomaly_case_ids = frozenset(
        case.case_id for case in result.cases if case.legacy_anomaly_category is not None
    )
    anomaly_set_verified: bool | None = None
    if expected_anomaly_case_ids is not None:
        anomaly_set_verified = actual_anomaly_case_ids == expected_anomaly_case_ids
        if not anomaly_set_verified:
            missing = sorted(str(case_id) for case_id in expected_anomaly_case_ids - actual_anomaly_case_ids)
            extra = sorted(str(case_id) for case_id in actual_anomaly_case_ids - expected_anomaly_case_ids)
            raise ValueError(f"legacy anomaly case set drift: missing={missing[:5]} extra={extra[:5]}")

    _write_json(
        output_dir / "baseline.json",
        {
            "batch_id": result.batch_id,
            "source_scope": result.source_scope,
            "taxonomy_version_id": result.taxonomy_version_id,
            "taxonomy_version": result.taxonomy_version,
            "manifest_hash": result.manifest_hash,
            "assignment_hash": result.assignment_hash,
            "baseline_hash": result.baseline_hash,
            "plan_hash": result.plan_hash,
            "case_set_hash": result.case_set_hash,
            "provenance_hash": result.provenance_hash,
            "case_count": result.total_count,
            "legacy_anomaly_count": len(actual_anomaly_case_ids),
            "legacy_anomaly_case_set_hash": _uuid_set_hash(actual_anomaly_case_ids),
            "legacy_anomaly_set_verified": anomaly_set_verified,
        },
    )

    case_payloads = [_case_payload(case) for case in result.cases]
    _write_json(output_dir / "old-vs-new.json", case_payloads)
    _write_jsonl(
        output_dir / "assignments.jsonl",
        [assignment.model_dump(mode="json", exclude_none=True) for assignment in assignments.assignments],
    )
    _write_jsonl(
        output_dir / "unresolved.jsonl",
        [payload for payload in case_payloads if payload["target_stable_key"] is None],
    )
    _write_jsonl(
        output_dir / "known-anomalies.jsonl",
        [payload for payload in case_payloads if payload["legacy_anomaly_category"] is not None],
    )

    source_trace = _source_trace(result.cases)
    _write_json(output_dir / "source-trace.json", source_trace)
    _write_samples(samples_dir, result)
    (output_dir / "REPORT.md").write_text(
        _render_report(result, source_trace, assignments, anomaly_set_verified=anomaly_set_verified),
        encoding="utf-8",
    )

    if result.run_id is not None:
        _write_json(
            output_dir / "rollback.json",
            {
                "run_id": result.run_id,
                "batch_id": result.batch_id,
                "applied_state_hash": result.applied_state_hash,
                "command": f"uv run python scripts/taxonomy_replay.py rollback {result.run_id} --actor <name>",
            },
        )


def _case_payload(case: ReplayCaseResult) -> dict[str, Any]:
    return {
        **asdict(case),
        "case_id": str(case.case_id),
        "old_taxonomy_concept_id": (str(case.old_taxonomy_concept_id) if case.old_taxonomy_concept_id else None),
        "source_refs": list(case.source_refs),
        "legacy_branch_path": list(case.legacy_branch_path),
        "target_path": list(case.target_path),
        "related_stable_keys": list(case.related_stable_keys),
    }


def _source_trace(cases: tuple[ReplayCaseResult, ...]) -> dict[str, Any]:
    case_ids_by_ref: dict[str, list[str]] = defaultdict(list)
    cases_with_refs: set[str] = set()
    total_references = 0
    for case in cases:
        case_id = str(case.case_id)
        if case.source_refs:
            cases_with_refs.add(case_id)
        for source_ref in case.source_refs:
            total_references += 1
            case_ids_by_ref[source_ref].append(case_id)

    return {
        "total_reference_count": total_references,
        "unique_case_count": len(cases_with_refs),
        "source_ref_count": len(case_ids_by_ref),
        "items": [
            {
                "source_ref": source_ref,
                "reference_count": len(case_ids),
                "unique_case_count": len(set(case_ids)),
                "case_ids": sorted(set(case_ids)),
            }
            for source_ref, case_ids in sorted(case_ids_by_ref.items())
        ],
    }


def _render_report(
    result: TaxonomyReplayResult,
    source_trace: dict[str, Any],
    assignments: TaxonomyAssignmentSet,
    *,
    anomaly_set_verified: bool | None,
) -> str:
    path_counts = Counter(_path_label(case) for case in result.cases)
    source_counts = Counter(case.assignment_source for case in result.cases)
    legacy_counts = Counter(case.legacy_business_module for case in result.cases)
    anomaly_counts = Counter(
        case.legacy_anomaly_category for case in result.cases if case.legacy_anomaly_category is not None
    )
    anomaly_mapped_counts = Counter(
        case.legacy_anomaly_category
        for case in result.cases
        if case.legacy_anomaly_category is not None and case.target_stable_key is not None
    )
    anomaly_main_counts = Counter(
        case.legacy_anomaly_category
        for case in result.cases
        if case.legacy_anomaly_category is not None and case.is_main_candidate
    )
    dirty_paths = sorted(path for path in path_counts if _is_dirty_path(path))
    large_paths = sorted((path, count) for path, count in path_counts.items() if path != "未决" and count > 30)
    coverage_gate = result.overall_coverage >= 0.90 and result.main_coverage >= 0.95
    name_gate = not dirty_paths
    large_gate = not large_paths
    assignment_approved = assignments.approval_status == "approved"
    approved_assignment_count = result.mapped_count if assignment_approved else 0
    approved_mapping_count = source_counts.get("approved_mapping", 0) if assignment_approved else 0
    approved_mapping_main_count = (
        sum(case.assignment_source == "approved_mapping" and case.is_main_candidate for case in result.cases)
        if assignment_approved
        else 0
    )
    approved_assignment_coverage = approved_assignment_count / result.total_count if result.total_count else 0
    approved_mapping_coverage = approved_mapping_count / result.total_count if result.total_count else 0
    approved_mapping_main_coverage = (
        approved_mapping_main_count / result.main_total_count if result.main_total_count else 0
    )
    approved_mapping_gate = approved_mapping_coverage >= 0.90 and approved_mapping_main_coverage >= 0.95
    approved_mapping_gate_status = (
        "PASS"
        if approved_mapping_gate
        else ("FAIL：覆盖未达标" if approved_mapping_count else "PENDING：当前没有 approved mapping")
    )
    non_capability_cases = [
        case for case in result.cases if case.target_stable_key is not None and case.target_node_type != "capability"
    ]
    capability_count = result.mapped_count - len(non_capability_cases)
    capability_coverage = capability_count / result.mapped_count if result.mapped_count else 0
    granularity_counts = Counter(_path_label(case) for case in non_capability_cases)
    granularity_text = (
        "；".join(f"{path}（{count}）" for path, count in granularity_counts.most_common())
        if granularity_counts
        else "无"
    )
    granularity_gate_status = (
        "PASS"
        if not non_capability_cases
        else f"PENDING：{len(non_capability_cases)} 条落在 domain/module，需确认是否缺少 capability"
    )

    path_rows = "\n".join(f"| {path} | {count} |" for path, count in path_counts.most_common()) or "| - | 0 |"
    legacy_rows = "\n".join(f"| {module} | {count} |" for module, count in legacy_counts.most_common()) or "| - | 0 |"
    large_rows = (
        "\n".join(f"| {path} | {count} | 待说明或继续拆分 |" for path, count in large_paths) or "| 无 | - | 通过 |"
    )
    dirty_text = "、".join(dirty_paths) if dirty_paths else "无"
    anomaly_labels = {
        "source_section_fallback": "source-section 回退",
        "unresolved": "待分类/未分类",
        "legacy_catch_all_module": "旧 catch-all 模块",
    }
    anomaly_rows = (
        "\n".join(
            f"| {anomaly_labels.get(category, category)} | {count} | "
            f"{anomaly_main_counts.get(category, 0)} | "
            f"{anomaly_mapped_counts.get(category, 0)} |"
            for category, count in anomaly_counts.most_common()
        )
        or "| 无 | 0 | 0 | 0 |"
    )
    approved_assignment_row = (
        f"| 可执行 approved assignment 覆盖 | {approved_assignment_count}/{result.total_count} "
        f"({approved_assignment_coverage:.1%}) | assignment set 批准后计算 |"
    )
    capability_row = (
        f"| 候选 capability 粒度 | {capability_count}/{result.mapped_count} "
        f"({capability_coverage:.1%}) | 宽粒度定位不冒充叶能力完整度 |"
    )
    approved_mapping_row = (
        f"| 可复用 approved mapping 覆盖 | {approved_mapping_count}/{result.total_count} "
        f"({approved_mapping_coverage:.1%})；main "
        f"{approved_mapping_main_count}/{result.main_total_count} ({approved_mapping_main_coverage:.1%}) | "
        "overall ≥90%，main ≥95%；不由逐 case assignment 冒充 |"
    )
    gate_warning = (
        "在 assignment 批准、独立抽样精度、用户校准以及可复用 mapping 证据完成前，"
        "即使候选 coverage 达标，Gate A 仍是 NO-GO；不得启动 Pipeline 子任务。"
    )
    source_warning = (
        "> 警告：本报告基于远端公开 API 的本地影子快照；API 未公开的 verification、taxonomy "
        "与完整 TestPoint 字段不在该基线中，生产 apply 前必须在目标数据库重跑。"
        if result.source_scope == "remote_api_shadow"
        else "> 数据库直读；是否为生产环境仍由运行者与部署上下文确认。"
    )
    anomaly_set_status = (
        "PASS" if anomaly_set_verified else ("FAIL" if anomaly_set_verified is False else "未提供冻结集合")
    )

    return f"""# Taxonomy 真实批次回放报告

> Batch：`{result.batch_id}`
> Taxonomy version：`{result.taxonomy_version}` (`{result.taxonomy_version_id}`)
> 模式：{"APPLY" if result.applied else "DRY-RUN"}
> 数据来源：`{result.source_scope}`
> Assignment approval：`{assignments.approval_status}`
> 重要：旧分类器仅作 proposal，不是正式 assignment authority。
{source_warning}

## 1. 守恒与审计

| 指标 | 值 |
|---|---:|
| 用例总数 | {result.total_count} |
| Case set hash | `{result.case_set_hash}` |
| Provenance hash | `{result.provenance_hash}` |
| Baseline hash | `{result.baseline_hash}` |
| Plan hash | `{result.plan_hash}` |
| Manifest hash | `{result.manifest_hash}` |
| Assignment hash | `{result.assignment_hash}` |
| 冻结旧异常集合 | {anomaly_set_status} |
| Source reference count | {source_trace["total_reference_count"]} |
| 有来源的 unique case count | {source_trace["unique_case_count"]} |

## 2. Assignment 覆盖口径

`候选定位覆盖`只说明每条 case 都有建议位置；它不等于审批、准确率或未来批次可复用 mapping 覆盖。

| 指标 | 结果 | 门槛 |
|---|---:|---:|
| 候选定位覆盖（overall） | {result.mapped_count}/{result.total_count} ({result.overall_coverage:.1%}) | ≥90% |
| 候选定位覆盖（main） | {result.main_mapped_count}/{result.main_total_count} ({result.main_coverage:.1%}) | ≥95% |
{capability_row}
{approved_assignment_row}
{approved_mapping_row}
| Unresolved | {result.unresolved_count} | 必须逐条有原因 |
| Changed / unchanged | {result.changed_count} / {result.unchanged_count} | 计数守恒 |

Assignment source：`{dict(source_counts)}`

## 3. 新业务树

| 路径 | Unique cases |
|---|---:|
{path_rows}

### 大节点检查

| 路径 | 用例数 | 结论 |
|---|---:|---|
{large_rows}

### 名称卫生

- 脏路径：{dirty_text}
- 禁止项：`prd:`、HTML、裸章节号、source-section 模块、`通用规则` 占位节点。

### 能力粒度债务

- 落在 domain/module 的候选用例：{len(non_capability_cases)} 条。
- 宽粒度路径：{granularity_text}。
- 宽粒度定位不等于错误；它必须由业务确认是有意归到模块，还是 taxonomy 尚缺 capability。

## 4. 旧平台坐标对照

| 旧派生模块 | Cases |
|---|---:|
{legacy_rows}

这里还原平台实际展示坐标；分类器原始结果仍只作为证据，不参与 apply。

## 5. 已知异常审查集合

| 类型 | 旧坐标用例数 | Main | 已有候选新位置 |
|---|---:|---:|---:|
{anomaly_rows}

- 自动识别总计：{sum(anomaly_counts.values())} 条；逐条明细见 `known-anomalies.jsonl`。
- `旧 catch-all 模块`表示旧坐标粒度不可直接作为业务归属，并不预设其中每条业务断言都错误。
- “已有候选新位置”不是准确率结论，仍需独立审查或用户确认。

## 6. Gate A

| 门禁 | 状态 |
|---|---|
| 候选 coverage（overall/main） | {"PASS" if coverage_gate else "FAIL"} |
| Assignment 已批准 | {"PASS" if assignment_approved else "PENDING"} |
| 可复用 approved mapping | {approved_mapping_gate_status} |
| 审批身份可信边界 | PENDING：本机 CLI 仅提供职责分离审计，身份可信度依赖部署账号与数据库权限 |
| 名称卫生 | {"PASS" if name_gate else "FAIL"} |
| >30 大节点 | {"PASS" if large_gate else "PENDING"} |
| 能力粒度债务 | {granularity_gate_status} |
| 独立抽样精度 ≥95% | PENDING：本报告不把 assignment 自审当作独立精度证据 |
| 用户业务校准 | PENDING |

{gate_warning}
"""


def _write_samples(samples_dir: Path, result: TaxonomyReplayResult) -> None:
    grouped: dict[str, list[ReplayCaseResult]] = defaultdict(list)
    for case in result.cases:
        grouped[_path_label(case)].append(case)

    for path, cases in sorted(grouped.items()):
        sampled = sorted(
            cases,
            key=lambda case: hashlib.sha256(f"{result.batch_id}:{case.case_id}".encode()).hexdigest(),
        )[:5]
        rows = "\n".join(
            f"| `{case.case_id}` | {case.title.replace('|', '/')} | "
            f"{case.legacy_business_module.replace('|', '/')} | "
            f"{case.assignment_source} | {case.reason.replace('|', '/')} | "
            f"{'; '.join(case.source_refs).replace('|', '/')} |"
            for case in sampled
        )
        content = f"""# 分层样本：{path}

固定依据：`sha256(batch_id + case_id)`；最多 5 条。assignment 审批元数据变化不会重洗样本。

| Case ID | 标题 | 旧 proposal | Assignment source | 理由 | Source refs |
|---|---|---|---|---|---|
{rows}
"""
        (samples_dir / f"{_safe_name(path)}.md").write_text(content, encoding="utf-8")


def _path_label(case: ReplayCaseResult) -> str:
    return " / ".join(case.target_path) if case.target_path else "未决"


def _is_dirty_path(path: str) -> bool:
    if path == "未决":
        return False
    return (
        "prd:" in path.lower()
        or "<" in path
        or ">" in path
        or "通用规则" in path
        or any(re.fullmatch(r"\d+(?:\.\d+)*", segment.strip()) for segment in path.split("/"))
    )


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value).strip("_")
    return normalized[:80] or "未决"


def _uuid_set_hash(case_ids: frozenset[UUID]) -> str:
    payload = json.dumps(sorted(str(case_id) for case_id in case_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False, default=str) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
