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
        sa.Column("definition_hash", sa.String(length=64), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_by", sa.String(length=100), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_taxonomy_versions_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_taxonomy_versions_status"),
        sa.CheckConstraint(
            "(status = 'draft' AND activated_by IS NULL AND activated_at IS NULL) OR "
            "(status IN ('active', 'retired') AND activated_by IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_taxonomy_versions_activation_metadata",
        ),
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
            ["system_id", "reviewed_taxonomy_version_id"],
            ["testcase.taxonomy_versions.system_id", "testcase.taxonomy_versions.id"],
            name="fk_req_tax_mapping_version_system",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_taxonomy_version_id", "concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_req_tax_mapping_target_node",
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
            "(review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL "
            "AND supersedes_mapping_id IS NULL) OR "
            "(review_status = 'rejected' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL "
            "AND supersedes_mapping_id IS NULL) OR "
            "(review_status IN ('approved', 'superseded') "
            "AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_req_tax_mapping_review_metadata",
        ),
        sa.CheckConstraint(
            "supersedes_mapping_id IS NULL OR supersedes_mapping_id != id",
            name="ck_req_tax_mapping_not_self_supersede",
        ),
        sa.UniqueConstraint("id", "reviewed_taxonomy_version_id", name="uq_req_tax_mapping_id_version"),
        sa.UniqueConstraint("supersedes_mapping_id", name="uq_req_tax_mapping_direct_successor"),
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
        "requirement_taxonomy_mapping_related_concepts",
        sa.Column("mapping_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["mapping_id", "taxonomy_version_id"],
            [
                "testcase.requirement_taxonomy_mappings.id",
                "testcase.requirement_taxonomy_mappings.reviewed_taxonomy_version_id",
            ],
            name="fk_req_tax_mapping_related_owner_version",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_req_tax_mapping_related_node",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
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
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("applied_state_hash", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'applied'")),
        sa.Column("before_image", JSONB(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("rolled_back_by", sa.String(length=100), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('applied', 'rolled_back')", name="ck_taxonomy_backfill_runs_status"),
        sa.CheckConstraint(
            "changed_count >= 0 AND unchanged_count >= 0 AND unresolved_count >= 0",
            name="ck_taxonomy_backfill_runs_counts",
        ),
        sa.CheckConstraint(
            "(status = 'applied' AND rolled_back_by IS NULL AND rolled_back_at IS NULL) OR "
            "(status = 'rolled_back' AND rolled_back_by IS NOT NULL AND rolled_back_at IS NOT NULL)",
            name="ck_taxonomy_backfill_runs_rollback_metadata",
        ),
        schema="testcase",
    )

    op.add_column(
        "test_batches",
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), nullable=True),
        schema="testcase",
    )
    op.create_unique_constraint(
        "uq_test_batches_id_taxonomy_version",
        "test_batches",
        ["id", "taxonomy_version_id"],
        schema="testcase",
    )
    op.create_foreign_key(
        "fk_test_batches_taxonomy_version_system",
        "test_batches",
        "taxonomy_versions",
        ["system_id", "taxonomy_version_id"],
        ["system_id", "id"],
        source_schema="testcase",
        referent_schema="testcase",
        ondelete="RESTRICT",
        onupdate="CASCADE",
        deferrable=True,
        initially="DEFERRED",
    )

    for table in ("test_points", "test_cases"):
        op.add_column(table, sa.Column("taxonomy_version_id", UUID(as_uuid=True), nullable=True), schema="testcase")
        op.add_column(table, sa.Column("taxonomy_concept_id", UUID(as_uuid=True), nullable=True), schema="testcase")
        op.add_column(table, sa.Column("taxonomy_resolution", JSONB(), nullable=True), schema="testcase")
        op.create_unique_constraint(
            f"uq_{table}_id_taxonomy_version",
            table,
            ["id", "taxonomy_version_id"],
            schema="testcase",
        )
        op.create_foreign_key(
            f"fk_{table}_batch_taxonomy_version",
            table,
            "test_batches",
            ["batch_id", "taxonomy_version_id"],
            ["id", "taxonomy_version_id"],
            source_schema="testcase",
            referent_schema="testcase",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        )
        op.create_foreign_key(
            f"fk_{table}_taxonomy_node",
            table,
            "taxonomy_nodes",
            ["taxonomy_version_id", "taxonomy_concept_id"],
            ["taxonomy_version_id", "concept_id"],
            source_schema="testcase",
            referent_schema="testcase",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        )
        op.create_check_constraint(
            f"ck_{table}_taxonomy_concept_requires_version",
            table,
            "taxonomy_concept_id IS NULL OR taxonomy_version_id IS NOT NULL",
            schema="testcase",
        )
        op.create_index(f"ix_{table}_taxonomy_concept", table, ["taxonomy_concept_id"], schema="testcase")

    op.add_column("test_points", sa.Column("taxonomy_selector_facts", JSONB(), nullable=True), schema="testcase")

    op.create_table(
        "test_case_related_taxonomy_concepts",
        sa.Column("case_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["case_id", "taxonomy_version_id"],
            ["testcase.test_cases.id", "testcase.test_cases.taxonomy_version_id"],
            name="fk_case_related_taxonomy_owner_version",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_case_related_taxonomy_node",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        schema="testcase",
    )
    op.create_table(
        "test_point_related_taxonomy_concepts",
        sa.Column("test_point_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("taxonomy_version_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("concept_id", UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["test_point_id", "taxonomy_version_id"],
            ["testcase.test_points.id", "testcase.test_points.taxonomy_version_id"],
            name="fk_test_point_related_taxonomy_owner_version",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            ["testcase.taxonomy_nodes.taxonomy_version_id", "testcase.taxonomy_nodes.concept_id"],
            name="fk_test_point_related_taxonomy_node",
            ondelete="RESTRICT",
            onupdate="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        schema="testcase",
    )

    for statement in (
        """
        CREATE FUNCTION testcase.guard_taxonomy_version_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status IN ('active', 'retired') THEN
                    RAISE EXCEPTION 'active/retired taxonomy version cannot be deleted: %', OLD.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.system_id IS DISTINCT FROM OLD.system_id
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash
               OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
               OR NEW.change_note IS DISTINCT FROM OLD.change_note
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'taxonomy version identity/content is immutable: %', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'draft' AND NEW.status = 'active' THEN
                IF NEW.activated_by IS NULL OR NEW.activated_at IS NULL THEN
                    RAISE EXCEPTION 'taxonomy activation metadata required: %', OLD.id
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'active' AND NEW.status = 'retired'
               AND NEW.activated_by IS NOT DISTINCT FROM OLD.activated_by
               AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at THEN
                RETURN NEW;
            END IF;
            IF NEW IS NOT DISTINCT FROM OLD THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid taxonomy version transition: % -> %', OLD.status, NEW.status
                USING ERRCODE = '23514';
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_guard_taxonomy_version_mutation
        BEFORE UPDATE OR DELETE ON testcase.taxonomy_versions
        FOR EACH ROW EXECUTE FUNCTION testcase.guard_taxonomy_version_mutation()
        """,
        """
        CREATE FUNCTION testcase.guard_taxonomy_node_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            version_id uuid := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.taxonomy_version_id
                ELSE NEW.taxonomy_version_id
            END;
            version_status text;
        BEGIN
            IF TG_OP = 'UPDATE' AND (
                NEW.id IS DISTINCT FROM OLD.id
                OR NEW.system_id IS DISTINCT FROM OLD.system_id
                OR NEW.taxonomy_version_id IS DISTINCT FROM OLD.taxonomy_version_id
                OR NEW.concept_id IS DISTINCT FROM OLD.concept_id
            ) THEN
                RAISE EXCEPTION 'taxonomy node identity is immutable: %', OLD.id USING ERRCODE = '55000';
            END IF;
            SELECT status INTO version_status
            FROM testcase.taxonomy_versions
            WHERE id = version_id
            FOR UPDATE;
            IF version_status IN ('active', 'retired') THEN
                RAISE EXCEPTION 'nodes of active/retired taxonomy are immutable: %', version_id
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_guard_taxonomy_node_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON testcase.taxonomy_nodes
        FOR EACH ROW EXECUTE FUNCTION testcase.guard_taxonomy_node_mutation()
        """,
        """
        CREATE FUNCTION testcase.guard_reviewed_mapping_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.review_status IN ('approved', 'rejected', 'superseded') THEN
                    RAISE EXCEPTION 'reviewed taxonomy mapping cannot be deleted: %', OLD.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.review_status IN ('approved', 'rejected', 'superseded') THEN
                IF OLD.review_status = 'approved'
                   AND NEW.review_status = 'superseded'
                   AND (to_jsonb(NEW) - 'review_status') = (to_jsonb(OLD) - 'review_status') THEN
                    RETURN NEW;
                END IF;
                IF NEW IS NOT DISTINCT FROM OLD THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'reviewed taxonomy mapping is immutable: %', OLD.id USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_guard_reviewed_mapping_mutation
        BEFORE UPDATE OR DELETE ON testcase.requirement_taxonomy_mappings
        FOR EACH ROW EXECUTE FUNCTION testcase.guard_reviewed_mapping_mutation()
        """,
        """
        CREATE FUNCTION testcase.guard_reviewed_mapping_related_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            owner_id uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.mapping_id ELSE NEW.mapping_id END;
            owner_status text;
        BEGIN
            SELECT review_status INTO owner_status
            FROM testcase.requirement_taxonomy_mappings
            WHERE id = owner_id
            FOR UPDATE;
            IF owner_status IN ('approved', 'rejected', 'superseded') THEN
                RAISE EXCEPTION 'related concepts of reviewed mapping are immutable: %', owner_id
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_guard_reviewed_mapping_related_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON testcase.requirement_taxonomy_mapping_related_concepts
        FOR EACH ROW EXECUTE FUNCTION testcase.guard_reviewed_mapping_related_mutation()
        """,
        """
        CREATE FUNCTION testcase.guard_taxonomy_backfill_run_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'taxonomy backfill run cannot be deleted: %', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF NEW IS NOT DISTINCT FROM OLD THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'applied'
               AND NEW.status = 'rolled_back'
               AND (to_jsonb(NEW) - 'status' - 'rolled_back_by' - 'rolled_back_at') =
                   (to_jsonb(OLD) - 'status' - 'rolled_back_by' - 'rolled_back_at') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'taxonomy backfill run is immutable: %', OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_guard_taxonomy_backfill_run_mutation
        BEFORE UPDATE OR DELETE ON testcase.taxonomy_backfill_runs
        FOR EACH ROW EXECUTE FUNCTION testcase.guard_taxonomy_backfill_run_mutation()
        """,
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("test_point_related_taxonomy_concepts", schema="testcase")
    op.drop_table("test_case_related_taxonomy_concepts", schema="testcase")
    op.drop_column("test_points", "taxonomy_selector_facts", schema="testcase")
    for table in ("test_cases", "test_points"):
        op.drop_index(f"ix_{table}_taxonomy_concept", table_name=table, schema="testcase")
        op.drop_constraint(
            f"ck_{table}_taxonomy_concept_requires_version",
            table,
            schema="testcase",
            type_="check",
        )
        op.drop_constraint(f"fk_{table}_taxonomy_node", table, schema="testcase", type_="foreignkey")
        op.drop_constraint(f"fk_{table}_batch_taxonomy_version", table, schema="testcase", type_="foreignkey")
        op.drop_constraint(f"uq_{table}_id_taxonomy_version", table, schema="testcase", type_="unique")
        op.drop_column(table, "taxonomy_resolution", schema="testcase")
        op.drop_column(table, "taxonomy_concept_id", schema="testcase")
        op.drop_column(table, "taxonomy_version_id", schema="testcase")

    op.drop_constraint(
        "fk_test_batches_taxonomy_version_system",
        "test_batches",
        schema="testcase",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_test_batches_id_taxonomy_version",
        "test_batches",
        schema="testcase",
        type_="unique",
    )
    op.drop_column("test_batches", "taxonomy_version_id", schema="testcase")

    op.drop_table("taxonomy_backfill_runs", schema="testcase")
    op.drop_index(
        "ix_req_tax_mapping_concept",
        table_name="requirement_taxonomy_mappings",
        schema="testcase",
    )
    op.drop_table("requirement_taxonomy_mapping_related_concepts", schema="testcase")
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
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_reviewed_mapping_related_mutation()")
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_reviewed_mapping_mutation()")
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_taxonomy_node_mutation()")
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_taxonomy_version_mutation()")
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_taxonomy_backfill_run_mutation()")
