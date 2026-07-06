"""write_cases cheat sheet 过滤与格式化。"""

from __future__ import annotations

import re
from collections.abc import Mapping

from src.knowledge_base.schemas.cheat_sheet import CheatSheetInjectionItem
from src.platform_api.models.enums import CheatSheetType
from src.testcase_generator.schemas.parsed_context import FeatureItem
from src.testcase_generator.stages.test_points.rule_anchor import _tokenize as _rule_tokenize

_ASCII_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{1,}")
_DEFAULT_MAX_PER_TYPE = 5


def filter_cheat_sheet_for_feature(
    feature: FeatureItem,
    approved_by_type: Mapping[CheatSheetType | str, list[CheatSheetInjectionItem]],
) -> dict[str, list[dict]]:
    """按 feature 的章节号/文本 token 过滤 approved cheat sheet。"""
    feature_text = "\n".join([feature.name, feature.description, *feature.source_refs])
    feature_tokens = _tokens(feature_text)
    feature_section_tokens = _tokens(" ".join(feature.source_refs))

    filtered: dict[str, list[dict]] = {}
    for raw_type, items in approved_by_type.items():
        sheet_type = str(raw_type)
        for item in items:
            if not _matches_feature(item, feature_tokens, feature_section_tokens):
                continue
            filtered.setdefault(sheet_type, []).append(_compact_item(item))
    return filtered


def format_cheat_sheet_for_prompt(
    filtered: Mapping[str, list[dict]],
    *,
    max_per_type: int = _DEFAULT_MAX_PER_TYPE,
) -> dict[str, list[dict]]:
    """限制每类条目数量，保持 prompt 中的 cheat_sheet 字段紧凑。"""
    return {sheet_type: items[:max_per_type] for sheet_type, items in filtered.items() if items[:max_per_type]}


def _matches_feature(
    item: CheatSheetInjectionItem,
    feature_tokens: set[str],
    feature_section_tokens: set[str],
) -> bool:
    source_section_tokens = _tokens(" ".join(item.source_section_refs or []))
    if source_section_tokens and feature_section_tokens and source_section_tokens & feature_section_tokens:
        return True

    item_text = "\n".join([item.title, _flatten_content(item.content), " ".join(item.source_section_refs or [])])
    item_tokens = _tokens(item_text)
    return bool(item_tokens & feature_tokens)


def _compact_item(item: CheatSheetInjectionItem) -> dict:
    return {
        "title": item.title,
        "content": item.content,
        "source_section_refs": item.source_section_refs or [],
    }


def _flatten_content(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_content(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_content(v) for v in value)
    return "" if value is None else str(value)


def _tokens(text: str) -> set[str]:
    tokens = set(_rule_tokenize(text or ""))
    tokens.update(word.lower() for word in _ASCII_WORD.findall(text or ""))
    # 去掉单段章节号（如 5），避免 §5.0.3 与 §5.8.7 仅因顶层章节误匹配。
    return {token for token in tokens if not token.isdigit()}
