"""add knowledge.documents.image_captions（图描述持久化）

图解析（image_caption_enabled）后的结构化描述存入此 JSONB 列，
格式为 {filename: {caption_text, kind, ui_elements, ...}}。
重复 parse 时按 content_hash + 图清单 hash 命中缓存跳过。

Revision ID: 017
Revises: 016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("image_captions", JSONB, nullable=True),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_column("documents", "image_captions", schema="knowledge")
