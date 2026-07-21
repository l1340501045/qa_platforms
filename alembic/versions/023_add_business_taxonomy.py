"""add versioned business taxonomy and replay metadata

Revision ID: 023
Revises: 022
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_concepts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("stable_key", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("system_id", "stable_key", name="uq_taxonomy_concepts_system_key"),
        sa.UniqueConstraint("system_id", "id", name="uq_taxonomy_concepts_system_id"),
        schema="testcase",
    )
    op.create_table(
        "taxonomy_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_by", sa.String(length=100), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_taxonomy_versions_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_taxonomy_versions_status"),
        sa.UniqueConstraint("system_id", "version", name="uq_taxonomy_versions_system_version"),
        sa.UniqueConstraint("system_id", "id", name="uq_taxonomy_versions_system_id"),
        schema="testcase",
    )
    op.create_index(
        "uq_taxonomy_versions_one_active",
        "taxonomy_versions",
        ["system_id"],
        unique=True,
        schema="testcase",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "taxonomy_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("system_id", UUID(as_uuid=True), nullable=False),
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parent_concept_id", UUID(as_uuid=True), nullable=True),
        sa.Column("node_type", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("aliases", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("node_status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("replacement_concept_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["system_id", "taxonomy_version_id"],
            ["testcase.taxonomy_versions.system_id", "testcase.taxonomy_versions.id"],
            name="fk_taxonomy_nodes_version_system",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id", "concept_id"],
            ["testcase.taxonomy_concepts.system_id", "testcase.taxonomy_concepts.id"],
            name="fk_taxonomy_nodes_concept_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "parent_concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_taxonomy_nodes_parent_same_version",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "replacement_concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_taxonomy_nodes_replacement_same_version",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint("taxonomy_version_id", "concept_id", name="uq_taxonomy_nodes_version_concept"),
        sa.CheckConstraint("node_type IN ('domain', 'module', 'capability')", name="ck_taxonomy_nodes_type"),
        sa.CheckConstraint("node_status IN ('active', 'deprecated', 'merged')", name="ck_taxonomy_nodes_status"),
        sa.CheckConstraint(
            "parent_concept_id IS NULL OR parent_concept_id != concept_id",
            name="ck_taxonomy_nodes_parent_self",
        ),
        sa.CheckConstraint(
            "replacement_concept_id IS NULL OR replacement_concept_id != concept_id",
            name="ck_taxonomy_nodes_replacement_self",
        ),
        sa.CheckConstraint(
            "node_status != 'merged' OR replacement_concept_id IS NOT NULL",
            name="ck_taxonomy_nodes_merged_replacement",
        ),
        sa.CheckConstraint(
            "node_status != 'active' OR replacement_concept_id IS NULL",
            name="ck_taxonomy_nodes_active_replacement",
        ),
        schema="testcase",
    )
    op.create_table(
        "requirement_taxonomy_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("system_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_content_hash", sa.String(length=64), nullable=False),
        sa.Column("feature_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("selector", JSONB(), nullable=True),
        sa.Column("selector_hash", sa.String(length=64), nullable=False),
        sa.Column("concept_id", UUID(as_uuid=True), nullable=False),
        sa.Column("related_concept_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mapping_method", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_taxonomy_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "supersedes_mapping_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.requirement_taxonomy_mappings.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["system_id", "concept_id"],
            ["testcase.taxonomy_concepts.system_id", "testcase.taxonomy_concepts.id"],
            name="fk_req_tax_mapping_concept_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id", "reviewed_taxonomy_version_id"],
            ["testcase.taxonomy_versions.system_id", "testcase.taxonomy_versions.id"],
            name="fk_req_tax_mapping_version_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.CheckConstraint("scope IN ('feature_default', 'test_point_selector')", name="ck_req_tax_mapping_scope"),
        sa.CheckConstraint(
            "(scope = 'feature_default' AND selector IS NULL) OR "
            "(scope = 'test_point_selector' AND selector IS NOT NULL)",
            name="ck_req_tax_mapping_selector_scope",
        ),
        sa.CheckConstraint(
            "mapping_method IN ('manual', 'deterministic', 'llm_assisted')",
            name="ck_req_tax_mapping_method",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'superseded')",
            name="ck_req_tax_mapping_review_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_req_tax_mapping_confidence"),
        sa.CheckConstraint(
            "review_status != 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_req_tax_mapping_approved_review",
        ),
        schema="testcase",
    )
    op.create_index(
        "uq_req_tax_mapping_current_approved",
        "requirement_taxonomy_mappings",
        [
            "system_id",
            "document_id",
            "document_content_hash",
            "feature_fingerprint",
            "scope",
            "selector_hash",
        ],
        unique=True,
        schema="testcase",
        postgresql_where=sa.text("review_status = 'approved'"),
    )
    op.create_index(
        "ix_req_tax_mapping_concept",
        "requirement_taxonomy_mappings",
        ["concept_id"],
        schema="testcase",
    )
    op.create_table(
        "taxonomy_backfill_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "taxonomy_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.taxonomy_versions.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("assignment_hash", sa.String(length=64), nullable=False),
        sa.Column("baseline_hash", sa.String(length=64), nullable=False),
        sa.Column("applied_state_hash", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'applied'")),
        sa.Column("before_image", JSONB(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('applied', 'rolled_back')", name="ck_taxonomy_backfill_runs_status"),
        sa.CheckConstraint(
            "changed_count >= 0 AND unchanged_count >= 0 AND unresolved_count >= 0",
            name="ck_taxonomy_backfill_runs_counts",
        ),
        schema="testcase",
    )

    op.add_column(
        "test_batches",
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), nullable=True),
        schema="testcase",
    )
    op.create_foreign_key(
        "fk_test_batches_taxonomy_version",
        "test_batches",
        "taxonomy_versions",
        ["taxonomy_version_id"],
        ["id"],
        source_schema="testcase",
        referent_schema="testcase",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )

    for table in ("test_points", "test_cases"):
        op.add_column(table, sa.Column("taxonomy_concept_id", UUID(as_uuid=True), nullable=True), schema="testcase")
        op.add_column(table, sa.Column("related_taxonomy_concept_ids", JSONB(), nullable=True), schema="testcase")
        op.add_column(table, sa.Column("taxonomy_resolution", JSONB(), nullable=True), schema="testcase")
        op.create_foreign_key(
            f"fk_{table}_taxonomy_concept",
            table,
            "taxonomy_concepts",
            ["taxonomy_concept_id"],
            ["id"],
            source_schema="testcase",
            referent_schema="testcase",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        )
        op.create_index(f"ix_{table}_taxonomy_concept", table, ["taxonomy_concept_id"], schema="testcase")


def downgrade() -> None:
    for table in ("test_cases", "test_points"):
        op.drop_index(f"ix_{table}_taxonomy_concept", table_name=table, schema="testcase")
        op.drop_constraint(f"fk_{table}_taxonomy_concept", table, schema="testcase", type_="foreignkey")
        op.drop_column(table, "taxonomy_resolution", schema="testcase")
        op.drop_column(table, "related_taxonomy_concept_ids", schema="testcase")
        op.drop_column(table, "taxonomy_concept_id", schema="testcase")

    op.drop_constraint("fk_test_batches_taxonomy_version", "test_batches", schema="testcase", type_="foreignkey")
    op.drop_column("test_batches", "taxonomy_version_id", schema="testcase")

    op.drop_table("taxonomy_backfill_runs", schema="testcase")
    op.drop_index(
        "ix_req_tax_mapping_concept",
        table_name="requirement_taxonomy_mappings",
        schema="testcase",
    )
    op.drop_index(
        "uq_req_tax_mapping_current_approved",
        table_name="requirement_taxonomy_mappings",
        schema="testcase",
    )
    op.drop_table("requirement_taxonomy_mappings", schema="testcase")
    op.drop_table("taxonomy_nodes", schema="testcase")
    op.drop_index(
        "uq_taxonomy_versions_one_active",
        table_name="taxonomy_versions",
        schema="testcase",
    )
    op.drop_table("taxonomy_versions", schema="testcase")
    op.drop_table("taxonomy_concepts", schema="testcase")
