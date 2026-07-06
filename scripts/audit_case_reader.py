"""审查包用例 JSONL 读取工具。

新版审查包按业务模块树落盘：
``.audit/<batch>/modules/<module>/branches/**/cases.jsonl``。
为兼容历史包，也保留旧平铺：
``.audit/<batch>/modules/*.cases.jsonl``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def resolve_batch_path(batch: str) -> Path:
    """支持传入 batch id 或 .audit/<batch> 目录路径。"""
    path = Path(batch)
    if path.exists():
        return path
    return Path(".audit") / batch


def case_jsonl_files(batch_path: Path) -> list[Path]:
    """新版模块树优先；没有新版产物时回退旧平铺文件。"""
    modules_dir = batch_path / "modules"
    files = sorted(modules_dir.glob("*/branches/**/cases.jsonl"))
    if files:
        return files
    return sorted(modules_dir.glob("*.cases.jsonl"))


def iter_case_records(batch_path: Path) -> Iterator[tuple[Path, int, dict]]:
    """遍历审查包用例记录，并按 case id 去重。

    同一用例可能出现在多个审查视图/分支中。离线评估应以用例实体为单位，
    否则重复行会污染压缩率、verdict 一致化和 cap debt 统计。
    """
    seen_ids: set[str] = set()
    for path in case_jsonl_files(batch_path):
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no} 不是合法 JSONL") from exc

                case_id = str(record.get("id") or record.get("case_id") or "")
                if case_id and case_id in seen_ids:
                    continue
                if case_id:
                    seen_ids.add(case_id)
                yield path, line_no, record


def feature_fallback_from_path(path: Path) -> str:
    """历史审查包缺 feature_id 时，给 verdict 一致化提供稳定近似分组。

    旧平铺文件用文件名；新版模块树用 ``模块/分支/子分支``，避免所有嵌套文件
    都退化成 ``cases``。
    """
    parts = path.parts
    if path.name == "cases.jsonl" and "modules" in parts and "branches" in parts:
        module_idx = parts.index("modules")
        branch_idx = parts.index("branches", module_idx)
        module = parts[module_idx + 1] if module_idx + 1 < len(parts) else ""
        branch_parts = parts[branch_idx + 1 : -1]
        return "/".join(part for part in (module, *branch_parts) if part) or "unknown"
    return path.name.removesuffix(".cases.jsonl")
