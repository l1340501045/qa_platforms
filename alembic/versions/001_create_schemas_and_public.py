"""create schemas and public tables

Revision ID: 001
Revises: None
"""

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def upgrade():
    # 创建 schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.execute("CREATE SCHEMA IF NOT EXISTS testcase")

    # public.systems
    op.create_table(
        "systems",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="public",
    )

    # public.system_associations
    op.create_table(
        "system_associations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "source_system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("source_system_id", "target_system_id", "relation_type"),
        schema="public",
    )


def downgrade():
    op.drop_table("system_associations", schema="public")
    op.drop_table("systems", schema="public")
    op.execute("DROP SCHEMA IF EXISTS testcase")
    op.execute("DROP SCHEMA IF EXISTS knowledge")
