"""系统级业务 taxonomy、需求映射与历史回放模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.platform_api.models.public import Base


class TaxonomyConcept(Base):
    __tablename__ = "taxonomy_concepts"
    __table_args__ = (
        UniqueConstraint("system_id", "stable_key", name="uq_taxonomy_concepts_system_key"),
        UniqueConstraint("system_id", "id", name="uq_taxonomy_concepts_system_id"),
        {"schema": "testcase"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    stable_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TaxonomyVersion(Base):
    __tablename__ = "taxonomy_versions"
    __table_args__ = (
        UniqueConstraint("system_id", "version", name="uq_taxonomy_versions_system_version"),
        UniqueConstraint("system_id", "id", name="uq_taxonomy_versions_system_id"),
        CheckConstraint("version > 0", name="ck_taxonomy_versions_positive"),
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_taxonomy_versions_status"),
        Index(
            "uq_taxonomy_versions_one_active",
            "system_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "testcase"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'draft'")
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaxonomyNode(Base):
    __tablename__ = "taxonomy_nodes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["system_id", "taxonomy_version_id"],
            ["testcase.taxonomy_versions.system_id", "testcase.taxonomy_versions.id"],
            name="fk_taxonomy_nodes_version_system",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["system_id", "concept_id"],
            ["testcase.taxonomy_concepts.system_id", "testcase.taxonomy_concepts.id"],
            name="fk_taxonomy_nodes_concept_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "parent_concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_taxonomy_nodes_parent_same_version",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "replacement_concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_taxonomy_nodes_replacement_same_version",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("taxonomy_version_id", "concept_id", name="uq_taxonomy_nodes_version_concept"),
        CheckConstraint("node_type IN ('domain', 'module', 'capability')", name="ck_taxonomy_nodes_type"),
        CheckConstraint("node_status IN ('active', 'deprecated', 'merged')", name="ck_taxonomy_nodes_status"),
        CheckConstraint(
            "parent_concept_id IS NULL OR parent_concept_id != concept_id",
            name="ck_taxonomy_nodes_parent_self",
        ),
        CheckConstraint(
            "replacement_concept_id IS NULL OR replacement_concept_id != concept_id",
            name="ck_taxonomy_nodes_replacement_self",
        ),
        CheckConstraint(
            "node_status != 'merged' OR replacement_concept_id IS NOT NULL",
            name="ck_taxonomy_nodes_merged_replacement",
        ),
        CheckConstraint(
            "node_status != 'active' OR replacement_concept_id IS NULL",
            name="ck_taxonomy_nodes_active_replacement",
        ),
        {"schema": "testcase"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="'[]'::jsonb")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    node_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'active'")
    replacement_concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RequirementTaxonomyMapping(Base):
    __tablename__ = "requirement_taxonomy_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["system_id", "concept_id"],
            ["testcase.taxonomy_concepts.system_id", "testcase.taxonomy_concepts.id"],
            name="fk_req_tax_mapping_concept_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        ForeignKeyConstraint(
            ["system_id", "reviewed_taxonomy_version_id"],
            ["testcase.taxonomy_versions.system_id", "testcase.taxonomy_versions.id"],
            name="fk_req_tax_mapping_version_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        CheckConstraint("scope IN ('feature_default', 'test_point_selector')", name="ck_req_tax_mapping_scope"),
        CheckConstraint(
            "(scope = 'feature_default' AND selector IS NULL) OR "
            "(scope = 'test_point_selector' AND selector IS NOT NULL)",
            name="ck_req_tax_mapping_selector_scope",
        ),
        CheckConstraint(
            "mapping_method IN ('manual', 'deterministic', 'llm_assisted')",
            name="ck_req_tax_mapping_method",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'superseded')",
            name="ck_req_tax_mapping_review_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_req_tax_mapping_confidence"),
        CheckConstraint(
            "review_status != 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_req_tax_mapping_approved_review",
        ),
        Index(
            "uq_req_tax_mapping_current_approved",
            "system_id",
            "document_id",
            "document_content_hash",
            "feature_fingerprint",
            "scope",
            "selector_hash",
            unique=True,
            postgresql_where=text("review_status = 'approved'"),
        ),
        {"schema": "testcase"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge.documents.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    document_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)
    selector: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    selector_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    related_concept_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="'[]'::jsonb"
    )
    mapping_method: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supersedes_mapping_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.requirement_taxonomy_mappings.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TaxonomyBackfillRun(Base):
    __tablename__ = "taxonomy_backfill_runs"
    __table_args__ = (
        CheckConstraint("status IN ('applied', 'rolled_back')", name="ck_taxonomy_backfill_runs_status"),
        CheckConstraint(
            "changed_count >= 0 AND unchanged_count >= 0 AND unresolved_count >= 0",
            name="ck_taxonomy_backfill_runs_counts",
        ),
        {"schema": "testcase"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.test_batches.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("testcase.taxonomy_versions.id", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    assignment_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="'applied'")
    before_image: Mapped[dict] = mapped_column(JSONB, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
