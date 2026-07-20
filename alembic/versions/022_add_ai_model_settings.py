"""add encrypted versioned AI model settings

Revision ID: 022
Revises: 021
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_config_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("revision", name="uq_ai_model_config_versions_revision"),
        schema="public",
    )
    op.create_table(
        "ai_model_config_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.ai_model_config_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_role", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vector_dimension", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "model_role IN ('primary', 'vision', 'verify', 'embedding')",
            name="ck_ai_model_config_entries_role",
        ),
        sa.CheckConstraint("source IN ('environment', 'database')", name="ck_ai_model_config_entries_source"),
        sa.CheckConstraint(
            "validation_status IN ('untested', 'passed', 'key_unreadable')",
            name="ck_ai_model_config_entries_validation",
        ),
        sa.UniqueConstraint("version_id", "model_role", name="uq_ai_model_config_entries_version_role"),
        schema="public",
    )
    op.create_index(
        "ix_ai_model_config_entries_version_id",
        "ai_model_config_entries",
        ["version_id"],
        schema="public",
    )
    op.create_table(
        "ai_model_config_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "active_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.ai_model_config_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_ai_model_config_state_singleton"),
        schema="public",
    )
    op.execute("INSERT INTO public.ai_model_config_state (id, revision) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table("ai_model_config_state", schema="public")
    op.drop_index("ix_ai_model_config_entries_version_id", table_name="ai_model_config_entries", schema="public")
    op.drop_table("ai_model_config_entries", schema="public")
    op.drop_table("ai_model_config_versions", schema="public")
