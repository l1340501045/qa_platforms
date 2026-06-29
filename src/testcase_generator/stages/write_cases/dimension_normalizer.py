"""把 write_cases LLM 自由填的维度，归一化到 dimensions.yaml 的英文 enum。

未命中 enum 也未命中 alias 的 → 'other' + 告警（暴露漏网标签，便于补 alias 表）。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CFG = Path(__file__).resolve().parents[2] / "config"
_DIMENSIONS_PATH = _CFG / "dimensions.yaml"
_ALIASES_PATH = _CFG / "dimension_aliases.yaml"


@lru_cache(maxsize=1)
def _enum_names() -> frozenset[str]:
    data = yaml.safe_load(_DIMENSIONS_PATH.read_text(encoding="utf-8"))
    return frozenset(d["name"] for d in data.get("dimensions", []))


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    if not _ALIASES_PATH.exists():
        return {}
    data = yaml.safe_load(_ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return dict(data.get("aliases", {}))


def normalize_dimensions(dims: list[str]) -> list[str]:
    """归一到 enum；未命中→'other'+告警。去重保序。"""
    enum, alias = _enum_names(), _aliases()
    out: list[str] = []
    for d in dims or []:
        key = (d or "").strip()
        if key in enum:
            norm = key
        elif key in alias and alias[key] in enum:
            norm = alias[key]
        else:
            logger.warning("未知维度标签 %r → other（建议补 dimension_aliases.yaml）", d)
            norm = "other"
        if norm not in out:
            out.append(norm)
    return out
