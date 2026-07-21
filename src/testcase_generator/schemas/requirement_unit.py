"""可追溯到文档快照的原子需求单元契约。"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RequirementUnitId = Annotated[str, Field(pattern=r"^ru_[0-9a-f]{64}$")]


def _normalize_identity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_requirement_unit_id(
    *,
    document_content_hash: str,
    source_ref: str,
    statement: str,
) -> str:
    """用文档快照、来源锚点和规范化陈述生成位置无关的稳定 ID。"""

    digest = _canonical_hash(
        {
            "document_content_hash": document_content_hash,
            "source_ref": _normalize_identity_text(source_ref),
            "statement": _normalize_identity_text(statement),
        }
    )
    return f"ru_{digest}"


def build_source_quote_hash(source_quote: str) -> str:
    return hashlib.sha256(source_quote.strip().encode("utf-8")).hexdigest()


class RequirementUnit(BaseModel):
    """一个有单一可观察结果、可回放来源证据的需求事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    unit_id: RequirementUnitId
    system_id: UUID
    document_id: UUID
    document_content_hash: Sha256
    source_ref: str = Field(min_length=1, max_length=1000)
    source_quote: str = Field(min_length=1)
    source_quote_hash: Sha256
    structural_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1)
    observable_outcome: str = Field(min_length=1)
    scope_status: Literal["atomic", "wide", "unsupported", "conflicted"]

    @model_validator(mode="after")
    def validate_identity_and_evidence(self) -> RequirementUnit:
        expected_id = build_requirement_unit_id(
            document_content_hash=self.document_content_hash,
            source_ref=self.source_ref,
            statement=self.statement,
        )
        if self.unit_id != expected_id:
            raise ValueError("requirement_unit_id_mismatch")
        if self.source_quote_hash != build_source_quote_hash(self.source_quote):
            raise ValueError("source_quote_hash_mismatch")
        return self

    @property
    def evidence_hash(self) -> str:
        return _canonical_hash(
            {
                "document_content_hash": self.document_content_hash,
                "source_ref": _normalize_identity_text(self.source_ref),
                "source_quote_hash": self.source_quote_hash,
                "statement": _normalize_identity_text(self.statement),
            }
        )
