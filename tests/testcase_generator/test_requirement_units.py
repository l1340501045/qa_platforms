from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.testcase_generator.schemas.requirement_unit import (
    RequirementUnit,
    build_requirement_unit_id,
    build_source_quote_hash,
)

SYSTEM_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTENT_HASH = "c" * 64


def _unit_data(*, statement: str = "商品库数据从巨量平台同步。") -> dict:
    source_ref = "prd:商品管理 §3.2 商品同步"
    source_quote = "商品库数据由巨量平台同步，系统不提供单个新建商品入口。"
    return {
        "unit_id": build_requirement_unit_id(
            document_content_hash=CONTENT_HASH,
            source_ref=source_ref,
            statement=statement,
        ),
        "system_id": str(SYSTEM_ID),
        "document_id": str(DOCUMENT_ID),
        "document_content_hash": CONTENT_HASH,
        "source_ref": source_ref,
        "source_quote": source_quote,
        "source_quote_hash": build_source_quote_hash(source_quote),
        "structural_key": "product.sync",
        "title": "商品同步",
        "statement": statement,
        "observable_outcome": "同步完成后，商品库展示巨量平台返回的商品。",
        "scope_status": "atomic",
    }


def test_requirement_unit_id_is_independent_of_collection_position_and_title() -> None:
    first = RequirementUnit.model_validate(_unit_data())
    renamed = _unit_data()
    renamed["title"] = "同步商品数据"

    second = RequirementUnit.model_validate(renamed)

    assert first.unit_id == second.unit_id


def test_requirement_unit_id_normalizes_non_semantic_whitespace() -> None:
    first = build_requirement_unit_id(
        document_content_hash=CONTENT_HASH,
        source_ref="prd:商品管理  §3.2\n商品同步",
        statement="商品库数据从巨量平台同步。",
    )
    second = build_requirement_unit_id(
        document_content_hash=CONTENT_HASH,
        source_ref="prd:商品管理 §3.2 商品同步",
        statement="商品库数据从巨量平台同步。",
    )

    assert first == second


def test_requirement_unit_id_changes_when_grounded_statement_changes() -> None:
    first = build_requirement_unit_id(
        document_content_hash=CONTENT_HASH,
        source_ref="prd:商品管理 §3.2 商品同步",
        statement="商品库数据从巨量平台同步。",
    )
    second = build_requirement_unit_id(
        document_content_hash=CONTENT_HASH,
        source_ref="prd:商品管理 §3.2 商品同步",
        statement="商品库允许人工新建商品。",
    )

    assert first != second


def test_requirement_unit_rejects_tampered_stable_id() -> None:
    data = _unit_data()
    data["unit_id"] = f"ru_{'0' * 64}"

    with pytest.raises(ValidationError, match="requirement_unit_id_mismatch"):
        RequirementUnit.model_validate(data)


def test_requirement_unit_rejects_tampered_source_quote_hash() -> None:
    data = _unit_data()
    data["source_quote_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="source_quote_hash_mismatch"):
        RequirementUnit.model_validate(data)
