"""add notification table

Revision ID: 006
Revises: 005
"""

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("actor", sa.String(100), nullable=False, server_default=sa.text("'system'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="public",
    )

    # 部分索引：仅索引未读消息，按创建时间降序
    op.create_index(
        "idx_notifications_unread",
        "notifications",
        ["is_read", sa.text("created_at DESC")],
        schema="public",
        postgresql_where=sa.text("is_read = FALSE"),
    )


def downgrade():
    op.drop_index("idx_notifications_unread", table_name="notifications", schema="public")
    op.drop_table("notifications", schema="public")
