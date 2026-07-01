"""离线评估 verify verdict 同构一致化效果。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.testcase_generator.schemas.test_case import CaseVerification
from src.testcase_generator.stages.verify.verifier import VerifyCase, reconcile_verdicts

_TITLE_KEEP = re.compile(r"[一-鿿a-zA-Z0-9]+")


def _normalize_title(title: str) -> str:
    return "".join(_TITLE_KEEP.findall((title or "").lower()))


def _resolve_batch_path(batch: str) -> Path:
    path = Path(batch)
    if path.exists():
        return path
    return Path(".audit") / batch


def _iter_case_records(batch_path: Path):
    modules_dir = batch_path / "modules"
    for path in sorted(modules_dir.glob("*.cases.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield path, line_no, json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no} 不是合法 JSONL") from exc


def _module_feature_id(path: Path) -> str:
    return path.name.removesuffix(".cases.jsonl")


def _to_case(path: Path, record: dict) -> tuple[VerifyCase, CaseVerification] | None:
    case_id = str(record.get("id") or record.get("case_id") or "")
    title = str(record.get("title") or "")
    if not case_id or not title:
        return None

    verification_payload = record.get("verification") or {}
    verdict = verification_payload.get("verdict") or record.get("verdict")
    bucket = verification_payload.get("bucket") or record.get("bucket")
    if not verdict or not bucket:
        return None

    # 历史 audit JSONL 通常没有生产态 feature_id，test_point_id 粒度又比 verify_cases 的
    # feature 分组更细；离线评估缺 feature_id 时用 module 文件名近似 feature/章节粒度。
    feature_id = str(record.get("feature_id") or _module_feature_id(path))
    case = VerifyCase(case_id=case_id, feature_id=feature_id, title=title)
    verification_data = {**verification_payload, "verdict": verdict, "bucket": bucket}
    verification = CaseVerification(**verification_data)
    return case, verification


def _changed_cluster_count(cases: list[VerifyCase], changed_ids: set[str], sim: float) -> int:
    by_feature: dict[str, list[VerifyCase]] = defaultdict(list)
    for case in cases:
        by_feature[case.feature_id].append(case)

    changed_roots: set[tuple[str, str]] = set()
    for feature_cases in by_feature.values():
        parent = {c.case_id: c.case_id for c in feature_cases}

        def find(case_id: str) -> str:
            while parent[case_id] != case_id:
                parent[case_id] = parent[parent[case_id]]
                case_id = parent[case_id]
            return case_id

        def union(left: str, right: str) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        titles = {c.case_id: _normalize_title(c.title) for c in feature_cases}
        from difflib import SequenceMatcher

        for idx, left in enumerate(feature_cases):
            for right in feature_cases[idx + 1 :]:
                if SequenceMatcher(None, titles[left.case_id], titles[right.case_id]).ratio() >= sim:
                    union(left.case_id, right.case_id)

        for case in feature_cases:
            if case.case_id in changed_ids:
                changed_roots.add((case.feature_id, find(case.case_id)))
    return len(changed_roots)


def main() -> int:
    parser = argparse.ArgumentParser(description="离线评估 verdict 同构一致化效果")
    parser.add_argument("batch", help="batch id 或 .audit/<batch> 路径")
    parser.add_argument(
        "--sim", type=float, default=0.93, help="标题相似度阈值，默认 0.93（与 settings.reconcile_sim 生产默认对齐）"
    )
    parser.add_argument("--examples", type=int, default=10, help="输出改判示例数量")
    args = parser.parse_args()

    batch_path = _resolve_batch_path(args.batch)
    if not batch_path.exists():
        raise SystemExit(f"batch 不存在：{batch_path}")

    cases: list[VerifyCase] = []
    results: dict[str, CaseVerification] = {}
    uses_module_fallback = False
    for path, _, record in _iter_case_records(batch_path):
        converted = _to_case(path, record)
        if converted is None:
            continue
        if not record.get("feature_id"):
            uses_module_fallback = True
        case, verification = converted
        cases.append(case)
        results[case.case_id] = verification

    reconciled = reconcile_verdicts(results, cases, sim=args.sim)
    changed_ids = {
        case_id
        for case_id, verification in results.items()
        if case_id in reconciled and verification.verdict != reconciled[case_id].verdict
    }
    cases_by_id = {case.case_id: case for case in cases}

    before = Counter(item.verdict for item in results.values())
    after = Counter(item.verdict for item in reconciled.values())
    cluster_count = _changed_cluster_count(cases, changed_ids, args.sim) if changed_ids else 0

    print(f"batch: {batch_path.name}")
    print(f"cases: {len(cases)}")
    if uses_module_fallback:
        print("feature_fallback: module filename (audit jsonl has no feature_id)")
    print(f"changed_clusters: {cluster_count}")
    print(f"changed_verdicts: {len(changed_ids)}")
    print(f"before: {dict(before)}")
    print(f"after: {dict(after)}")

    if changed_ids:
        print("examples:")
        for case_id in sorted(changed_ids)[: args.examples]:
            case = cases_by_id[case_id]
            print(
                f"- {case_id} [{case.feature_id}] {case.title}: "
                f"{results[case_id].verdict} -> {reconciled[case_id].verdict}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
