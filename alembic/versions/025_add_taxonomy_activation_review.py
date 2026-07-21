"""add initial v2 taxonomy activation review

Revision ID: 025
Revises: 024
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


_INITIAL_V2_REVIEW_GUARD = """
CREATE OR REPLACE FUNCTION testcase.guard_initial_v2_taxonomy_activation_review()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status IN ('active', 'retired')
       AND (
           NEW.activation_review_id IS DISTINCT FROM OLD.activation_review_id
           OR NEW.activation_package_hash IS DISTINCT FROM OLD.activation_package_hash
           OR NEW.activation_review_hash IS DISTINCT FROM OLD.activation_review_hash
           OR NEW.activation_review_artifact IS DISTINCT FROM OLD.activation_review_artifact
           OR NEW.activation_rollback_plan IS DISTINCT FROM OLD.activation_rollback_plan
       ) THEN
        RAISE EXCEPTION 'taxonomy activation review is immutable: %', OLD.id
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'draft'
       AND NEW.status = 'active'
       AND NEW.schema_version = 2
       AND NOT EXISTS (
           SELECT 1
           FROM testcase.taxonomy_versions history
           WHERE history.system_id = NEW.system_id
             AND history.id != NEW.id
             AND history.schema_version = 2
             AND history.status IN ('active', 'retired')
       ) THEN
        IF NEW.activation_review_id IS NULL
           OR NEW.activation_package_hash IS NULL
           OR NEW.activation_review_hash IS NULL
           OR NEW.activation_review_artifact IS NULL
           OR NULLIF(btrim(NEW.activation_rollback_plan), '') IS NULL THEN
            RAISE EXCEPTION 'initial v2 taxonomy activation review required: %', NEW.id
                USING ERRCODE = '23514';
        END IF;
        IF jsonb_typeof(NEW.activation_review_artifact) IS DISTINCT FROM 'object'
           OR jsonb_typeof(NEW.activation_review_artifact -> 'package') IS DISTINCT FROM 'object'
           OR jsonb_typeof(NEW.activation_review_artifact -> 'review') IS DISTINCT FROM 'object'
           OR NEW.activation_review_artifact ->> 'package_hash' IS DISTINCT FROM NEW.activation_package_hash
           OR NEW.activation_review_artifact ->> 'review_hash' IS DISTINCT FROM NEW.activation_review_hash
           OR NEW.activation_review_artifact -> 'package' ->> 'system_id' IS DISTINCT FROM NEW.system_id::text
           OR NEW.activation_review_artifact -> 'package' ->> 'draft_manifest_hash' IS DISTINCT FROM NEW.manifest_hash
           OR NEW.activation_review_artifact -> 'package' ->> 'gate_status' IS DISTINCT FROM 'pass'
           OR NEW.activation_review_artifact -> 'package' ->> 'gold_review_method' IS DISTINCT FROM
              'human_independent'
           OR NEW.activation_review_artifact -> 'package' ->> 'calibration_gold_review_method' IS DISTINCT FROM
              'human_independent'
           OR NULLIF(btrim(NEW.activation_review_artifact -> 'package' ->> 'prepared_by'), '') IS NULL
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'evaluation_run_hash', '') !~
              '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'dataset_hash', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'gold_hash', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'prediction_hash', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'policy_hash', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'frozen_policy_hash', '') !~ '^[0-9a-f]{64}$'
           OR COALESCE(NEW.activation_review_artifact -> 'package' ->> 'gate_hash', '') !~ '^[0-9a-f]{64}$'
           OR NEW.activation_review_artifact -> 'review' ->> 'draft_manifest_hash' IS DISTINCT FROM NEW.manifest_hash
           OR NEW.activation_review_artifact -> 'review' ->> 'decision' IS DISTINCT FROM 'approved'
           OR lower(NEW.activation_review_artifact -> 'review' ->> 'reviewer') IS DISTINCT FROM lower(NEW.activated_by)
           OR lower(NEW.activation_review_artifact -> 'review' ->> 'reviewer') = lower(NEW.created_by)
           OR lower(NEW.activation_review_artifact -> 'review' ->> 'reviewer') =
              lower(NEW.activation_review_artifact -> 'package' ->> 'prepared_by')
           OR NULLIF(NEW.activation_review_artifact -> 'package' ->> 'prepared_at', '') IS NULL
           OR NULLIF(NEW.activation_review_artifact -> 'review' ->> 'reviewed_at', '') IS NULL
           OR (NEW.activation_review_artifact -> 'package' ->> 'prepared_at')::timestamptz >
              (NEW.activation_review_artifact -> 'review' ->> 'reviewed_at')::timestamptz
           OR (NEW.activation_review_artifact -> 'review' ->> 'reviewed_at')::timestamptz > NEW.activated_at
           OR NEW.activation_review_artifact -> 'review' ->> 'review_id' IS DISTINCT FROM NEW.activation_review_id
           OR NEW.activation_review_artifact -> 'review' ->> 'package_hash' IS DISTINCT FROM
              NEW.activation_package_hash
           OR NEW.activation_review_artifact -> 'review' ->> 'evaluation_run_hash' IS DISTINCT FROM
              NEW.activation_review_artifact -> 'package' ->> 'evaluation_run_hash'
           OR NEW.activation_review_artifact -> 'review' ->> 'rollback_plan' IS DISTINCT FROM
              NEW.activation_rollback_plan THEN
            RAISE EXCEPTION 'initial v2 taxonomy activation review invalid: %', NEW.id
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column(
        "taxonomy_versions",
        sa.Column("activation_review_id", sa.String(length=160), nullable=True),
        schema="testcase",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM testcase.taxonomy_versions
                WHERE schema_version = 2
                  AND status IN ('active', 'retired')
            ) THEN
                RAISE EXCEPTION 'cannot install activation review gate while unreviewed v2 history exists'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$
        """
    )
    op.add_column(
        "taxonomy_versions",
        sa.Column("activation_package_hash", sa.String(length=64), nullable=True),
        schema="testcase",
    )
    op.add_column(
        "taxonomy_versions",
        sa.Column("activation_review_hash", sa.String(length=64), nullable=True),
        schema="testcase",
    )
    op.add_column(
        "taxonomy_versions",
        sa.Column("activation_review_artifact", JSONB(none_as_null=True), nullable=True),
        schema="testcase",
    )
    op.add_column(
        "taxonomy_versions",
        sa.Column("activation_rollback_plan", sa.Text(), nullable=True),
        schema="testcase",
    )
    op.create_check_constraint(
        "ck_taxonomy_versions_activation_review_complete",
        "taxonomy_versions",
        "(activation_review_id IS NULL AND activation_package_hash IS NULL "
        "AND activation_review_hash IS NULL AND activation_review_artifact IS NULL "
        "AND activation_rollback_plan IS NULL) OR "
        "(activation_review_id IS NOT NULL AND activation_package_hash IS NOT NULL "
        "AND activation_review_hash IS NOT NULL AND activation_review_artifact IS NOT NULL "
        "AND NULLIF(btrim(activation_rollback_plan), '') IS NOT NULL)",
        schema="testcase",
    )
    op.create_check_constraint(
        "ck_taxonomy_versions_activation_package_hash",
        "taxonomy_versions",
        "activation_package_hash IS NULL OR activation_package_hash ~ '^[0-9a-f]{64}$'",
        schema="testcase",
    )
    op.create_check_constraint(
        "ck_taxonomy_versions_activation_review_hash",
        "taxonomy_versions",
        "activation_review_hash IS NULL OR activation_review_hash ~ '^[0-9a-f]{64}$'",
        schema="testcase",
    )
    op.create_check_constraint(
        "ck_taxonomy_versions_activation_review_artifact_object",
        "taxonomy_versions",
        "activation_review_artifact IS NULL OR jsonb_typeof(activation_review_artifact) = 'object'",
        schema="testcase",
    )
    op.execute(_INITIAL_V2_REVIEW_GUARD)
    op.execute(
        "DROP TRIGGER IF EXISTS trg_zz_guard_initial_v2_taxonomy_activation_review ON testcase.taxonomy_versions"
    )
    op.execute(
        "CREATE TRIGGER trg_zz_guard_initial_v2_taxonomy_activation_review "
        "BEFORE UPDATE ON testcase.taxonomy_versions "
        "FOR EACH ROW EXECUTE FUNCTION testcase.guard_initial_v2_taxonomy_activation_review()"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM testcase.taxonomy_versions
                WHERE activation_review_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'cannot downgrade taxonomy activation review while audit data exists'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_zz_guard_initial_v2_taxonomy_activation_review ON testcase.taxonomy_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS testcase.guard_initial_v2_taxonomy_activation_review()")
    for constraint in (
        "ck_taxonomy_versions_activation_review_artifact_object",
        "ck_taxonomy_versions_activation_review_hash",
        "ck_taxonomy_versions_activation_package_hash",
        "ck_taxonomy_versions_activation_review_complete",
    ):
        op.drop_constraint(constraint, "taxonomy_versions", schema="testcase", type_="check")
    for column in (
        "activation_rollback_plan",
        "activation_review_artifact",
        "activation_review_hash",
        "activation_package_hash",
        "activation_review_id",
    ):
        op.drop_column("taxonomy_versions", column, schema="testcase")
