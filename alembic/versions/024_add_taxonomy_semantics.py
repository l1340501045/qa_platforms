"""add taxonomy semantic contracts

Revision ID: 024
Revises: 023
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


_GUARD_VERSION_V2 = """
CREATE OR REPLACE FUNCTION testcase.guard_taxonomy_version_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    latest_activated_version integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status != 'draft' THEN
            RAISE EXCEPTION 'taxonomy version must be inserted as draft: %', NEW.status
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
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
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
       OR NEW.manifest_hash IS DISTINCT FROM OLD.manifest_hash
       OR NEW.definition_hash IS DISTINCT FROM OLD.definition_hash
       OR NEW.change_note IS DISTINCT FROM OLD.change_note
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'taxonomy version identity/content is immutable: %', OLD.id
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'active' THEN
        SELECT max(version) INTO latest_activated_version
        FROM testcase.taxonomy_versions
        WHERE system_id = NEW.system_id
          AND status IN ('active', 'retired');
        IF latest_activated_version IS NOT NULL
           AND NEW.version <= latest_activated_version THEN
            RAISE EXCEPTION 'taxonomy activation must move forward: target %, latest %',
                NEW.version, latest_activated_version
                USING ERRCODE = '23514';
        END IF;
        IF NEW.activated_by IS NULL OR NEW.activated_at IS NULL THEN
            RAISE EXCEPTION 'taxonomy activation metadata required: %', OLD.id
                USING ERRCODE = '23514';
        END IF;
        IF NEW.schema_version = 2 AND (
            NOT EXISTS (
                SELECT 1
                FROM testcase.taxonomy_nodes node
                WHERE node.taxonomy_version_id = NEW.id
            )
            OR EXISTS (
                SELECT 1
                FROM testcase.taxonomy_nodes node
                WHERE node.taxonomy_version_id = NEW.id
                  AND (
                      NULLIF(btrim(node.definition), '') IS NULL
                      OR NULLIF(btrim(node.scope_note), '') IS NULL
                  )
            )
        ) THEN
            RAISE EXCEPTION 'v2 taxonomy node semantics required: %', NEW.id
                USING ERRCODE = '23514';
        END IF;
        IF NEW.schema_version = 2 AND EXISTS (
            SELECT 1
            FROM testcase.taxonomy_nodes node
            WHERE node.taxonomy_version_id = NEW.id
              AND node.node_type = 'capability'
              AND node.node_status = 'active'
              AND (
                  NULLIF(btrim(node.definition), '') IS NULL
                  OR NULLIF(btrim(node.scope_note), '') IS NULL
                  OR jsonb_array_length(node.in_scope_examples) = 0
              )
        ) THEN
            RAISE EXCEPTION 'v2 active capability semantics required: %', NEW.id
                USING ERRCODE = '23514';
        END IF;
        IF NEW.schema_version = 2 AND EXISTS (
            SELECT 1
            FROM testcase.taxonomy_nodes node
            CROSS JOIN LATERAL jsonb_array_elements(
                node.in_scope_examples || node.out_of_scope_examples
            ) AS example(value)
            WHERE node.taxonomy_version_id = NEW.id
              AND (
                  jsonb_typeof(example.value) != 'object'
                  OR NULLIF(btrim(example.value ->> 'text'), '') IS NULL
                  OR COALESCE(example.value ->> 'document_content_hash', '') !~ '^[0-9a-f]{64}$'
                  OR COALESCE(example.value ->> 'requirement_unit_id', '') !~ '^ru_[0-9a-f]{64}$'
              )
        ) THEN
            RAISE EXCEPTION 'v2 taxonomy example invalid: %', NEW.id
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
"""


_GUARD_VERSION_V1 = """
CREATE OR REPLACE FUNCTION testcase.guard_taxonomy_version_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    latest_activated_version integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status != 'draft' THEN
            RAISE EXCEPTION 'taxonomy version must be inserted as draft: %', NEW.status
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
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
        SELECT max(version) INTO latest_activated_version
        FROM testcase.taxonomy_versions
        WHERE system_id = NEW.system_id
          AND status IN ('active', 'retired');
        IF latest_activated_version IS NOT NULL
           AND NEW.version <= latest_activated_version THEN
            RAISE EXCEPTION 'taxonomy activation must move forward: target %, latest %',
                NEW.version, latest_activated_version
                USING ERRCODE = '23514';
        END IF;
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
"""


def upgrade() -> None:
    op.add_column(
        "taxonomy_versions",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        schema="testcase",
    )
    op.create_check_constraint(
        "ck_taxonomy_versions_schema_version",
        "taxonomy_versions",
        "schema_version IN (1, 2)",
        schema="testcase",
    )
    op.add_column("taxonomy_nodes", sa.Column("definition", sa.Text(), nullable=True), schema="testcase")
    op.add_column("taxonomy_nodes", sa.Column("scope_note", sa.Text(), nullable=True), schema="testcase")
    for column_name in ("in_scope_examples", "out_of_scope_examples"):
        op.add_column(
            "taxonomy_nodes",
            sa.Column(
                column_name,
                JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            schema="testcase",
        )
        op.create_check_constraint(
            f"ck_taxonomy_nodes_{column_name}_array",
            "taxonomy_nodes",
            f"jsonb_typeof({column_name}) = 'array'",
            schema="testcase",
        )
    op.execute(_GUARD_VERSION_V2)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM testcase.taxonomy_versions
                WHERE schema_version = 2
            ) OR EXISTS (
                SELECT 1
                FROM testcase.taxonomy_nodes
                WHERE definition IS NOT NULL
                   OR scope_note IS NOT NULL
                   OR in_scope_examples != '[]'::jsonb
                   OR out_of_scope_examples != '[]'::jsonb
            ) THEN
                RAISE EXCEPTION 'cannot downgrade taxonomy semantics while v2 data exists'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$
        """
    )
    op.execute(_GUARD_VERSION_V1)
    for column_name in ("out_of_scope_examples", "in_scope_examples"):
        op.drop_constraint(
            f"ck_taxonomy_nodes_{column_name}_array",
            "taxonomy_nodes",
            schema="testcase",
            type_="check",
        )
        op.drop_column("taxonomy_nodes", column_name, schema="testcase")
    op.drop_column("taxonomy_nodes", "scope_note", schema="testcase")
    op.drop_column("taxonomy_nodes", "definition", schema="testcase")
    op.drop_constraint(
        "ck_taxonomy_versions_schema_version",
        "taxonomy_versions",
        schema="testcase",
        type_="check",
    )
    op.drop_column("taxonomy_versions", "schema_version", schema="testcase")
