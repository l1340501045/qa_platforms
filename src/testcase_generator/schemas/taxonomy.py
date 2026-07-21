"""业务 taxonomy manifest 的强类型契约。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

StableKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=160)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomySelector(BaseModel):
    """只允许能跨文案变化保持稳定的 Test Point 选择条件。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rule_id: str | None = Field(default=None, min_length=1, max_length=100)
    structural_key: str | None = Field(default=None, min_length=1, max_length=255)
    requirement_anchor: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_value(self) -> TaxonomySelector:
        if not any((self.rule_id, self.structural_key, self.requirement_anchor)):
            raise ValueError("selector_value_required")
        return self

    @property
    def canonical_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json", exclude_none=True))


class TaxonomyNodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stable_key: StableKey
    node_type: Literal["domain", "module", "capability"]
    display_name: str = Field(min_length=1, max_length=255)
    parent_stable_key: StableKey | None = None
    aliases: list[str] = Field(default_factory=list)
    sort_order: int = Field(default=0, ge=0)
    node_status: Literal["active", "deprecated", "merged"] = "active"
    replacement_stable_key: StableKey | None = None

    @model_validator(mode="after")
    def validate_status(self) -> TaxonomyNodeManifest:
        if self.node_status == "merged" and self.replacement_stable_key is None:
            raise ValueError("merged_replacement_required")
        if self.node_status == "active" and self.replacement_stable_key is not None:
            raise ValueError("active_replacement_forbidden")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("duplicate_alias")
        if any(not alias.strip() for alias in self.aliases):
            raise ValueError("empty_alias")
        return self


class TaxonomyMappingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: UUID
    document_content_hash: Sha256
    feature_fingerprint: Sha256
    scope: Literal["feature_default", "test_point_selector"]
    selector: TaxonomySelector | None = None
    target_stable_key: StableKey
    related_stable_keys: list[StableKey] = Field(default_factory=list)
    mapping_method: Literal["manual", "deterministic", "llm_assisted"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=100)
    reviewed_at: datetime | None = None
    supersedes_mapping_id: UUID | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> TaxonomyMappingManifest:
        if self.scope == "feature_default" and self.selector is not None:
            raise ValueError("feature_default_selector_forbidden")
        if self.scope == "test_point_selector" and self.selector is None:
            raise ValueError("test_point_selector_required")
        if self.review_status == "approved" and not (self.reviewed_by and self.reviewed_at):
            raise ValueError("approved_review_metadata_required")
        if self.reviewed_at and (self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None):
            raise ValueError("reviewed_at_timezone_required")
        if self.supersedes_mapping_id and self.review_status != "approved":
            raise ValueError("supersedes_requires_approved")
        if len(self.related_stable_keys) != len(set(self.related_stable_keys)):
            raise ValueError("duplicate_related_concept")
        if self.target_stable_key in self.related_stable_keys:
            raise ValueError("target_repeated_as_related")
        return self

    @property
    def selector_hash(self) -> str:
        return self.selector.canonical_hash if self.selector else _canonical_hash({})

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.document_content_hash,
            self.feature_fingerprint,
            self.scope,
            self.selector_hash,
        )


class TaxonomyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal[1]
    system_id: UUID
    version: int = Field(ge=1)
    change_note: str = Field(min_length=1)
    created_by: str = Field(min_length=1, max_length=100)
    nodes: list[TaxonomyNodeManifest] = Field(min_length=1)
    mappings: list[TaxonomyMappingManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_and_mappings(self) -> TaxonomyManifest:
        nodes_by_key = {node.stable_key: node for node in self.nodes}
        if len(nodes_by_key) != len(self.nodes):
            raise ValueError("duplicate_stable_key")

        self._validate_relation(nodes_by_key, "parent_stable_key", "parent")
        self._validate_relation(nodes_by_key, "replacement_stable_key", "replacement")

        mapping_identities: set[tuple[str, str, str, str]] = set()
        for mapping in self.mappings:
            target = nodes_by_key.get(mapping.target_stable_key)
            if target is None:
                raise ValueError(f"mapping_target_missing:{mapping.target_stable_key}")
            if target.node_status != "active":
                raise ValueError(f"mapping_target_not_active:{mapping.target_stable_key}")
            for related_key in mapping.related_stable_keys:
                related = nodes_by_key.get(related_key)
                if related is None:
                    raise ValueError(f"mapping_related_missing:{related_key}")
                if related.node_status != "active":
                    raise ValueError(f"mapping_related_not_active:{related_key}")
            if mapping.identity in mapping_identities:
                raise ValueError("duplicate_mapping_identity")
            mapping_identities.add(mapping.identity)

        for node in self.nodes:
            if node.replacement_stable_key:
                replacement = nodes_by_key[node.replacement_stable_key]
                if replacement.node_status != "active":
                    raise ValueError(f"replacement_target_not_active:{node.replacement_stable_key}")
        return self

    @staticmethod
    def _validate_relation(
        nodes_by_key: dict[str, TaxonomyNodeManifest],
        field_name: Literal["parent_stable_key", "replacement_stable_key"],
        relation_name: str,
    ) -> None:
        edges: dict[str, str] = {}
        for key, node in nodes_by_key.items():
            target = getattr(node, field_name)
            if target is None:
                continue
            if target not in nodes_by_key:
                raise ValueError(f"{relation_name}_target_missing:{target}")
            if target == key:
                raise ValueError(f"{relation_name}_cycle:{key}")
            edges[key] = target

        for start in edges:
            seen: set[str] = set()
            current: str | None = start
            while current in edges:
                if current in seen:
                    raise ValueError(f"{relation_name}_cycle:{start}")
                seen.add(current)
                current = edges[current]
