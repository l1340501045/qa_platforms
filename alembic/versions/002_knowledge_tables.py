"""create knowledge schema tables

Revision ID: 002
Revises: 001
"""

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    # 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # knowledge.documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("doc_type", sa.String(30), nullable=False),
        sa.Column("trust_level", sa.SmallInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("image_refs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding_status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("folder_path", sa.String(500), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="knowledge",
    )

    # knowledge.document_associations
    op.create_table(
        "document_associations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "source_doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_doc_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="knowledge",
    )

    # 部分唯一索引 WHERE deleted_at IS NULL
    op.execute(
        "CREATE UNIQUE INDEX uq_doc_assoc_active "
        "ON knowledge.document_associations (source_doc_id, target_doc_id, relation_type) "
        "WHERE deleted_at IS NULL"
    )

    # knowledge.document_embeddings（使用 raw SQL 创建以支持 vector 类型）
    op.execute("""
        CREATE TABLE knowledge.document_embeddings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE ON UPDATE CASCADE,
            chunk_index INTEGER NOT NULL,
            chunk_heading VARCHAR(200),
            chunk_content TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # knowledge.prototype_links
    op.create_table(
        "prototype_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="knowledge",
    )


def downgrade():
    op.drop_table("prototype_links", schema="knowledge")
    op.execute("DROP TABLE IF EXISTS knowledge.document_embeddings")
    op.execute("DROP INDEX IF EXISTS knowledge.uq_doc_assoc_active")
    op.drop_table("document_associations", schema="knowledge")
    op.drop_table("documents", schema="knowledge")
    op.execute("DROP EXTENSION IF EXISTS vector")
