"""add knowledge.cheat_sheets + knowledge.cheat_sheet_items（cheat sheet 存储）

支持 AI 版/QA 版双内容与审核状态，作用域按 document 维护版本。

Revision ID: 019
Revises: 018
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cheat_sheets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("system_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("source_entity_count", sa.Integer(), nullable=True),
        sa.Column("source_relation_count", sa.Integer(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="knowledge",
    )

    op.create_table(
        "cheat_sheet_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "sheet_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.cheat_sheets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sheet_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("ai_content", JSONB, nullable=False),
        sa.Column("qa_content", JSONB, nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("review_tier", sa.String(length=10), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=50), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_entity_ids", JSONB, nullable=True),
        sa.Column("source_relation_ids", JSONB, nullable=True),
        sa.Column("source_section_refs", JSONB, nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="knowledge",
    )
    op.create_index(
        "ix_cheat_sheet_items_sheet_type",
        "cheat_sheet_items",
        ["sheet_id", "sheet_type"],
        unique=False,
        schema="knowledge",
    )
    op.create_index(
        "ix_cheat_sheet_items_sheet_review",
        "cheat_sheet_items",
        ["sheet_id", "review_status"],
        unique=False,
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_table("cheat_sheet_items", schema="knowledge")
    op.drop_table("cheat_sheets", schema="knowledge")
