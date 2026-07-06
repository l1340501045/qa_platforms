"""fix document_embeddings vector dimension 1536 -> 1024

Revision ID: 021
Revises: 020

建表迁移(002)按 text-embedding-3-small(1536) 写死了 embedding 维度，
但自建网关实际使用的 embedding 模型为 text-embedding-v4(1024 维)。
1024 维向量写入 vector(1536) 列触发维度冲突，导致向量化异常、
embedding_status=failed、切片数为 0（PRD 无法语义检索）。

本迁移将列维度对齐到 1024（与网关模型一致）并重建 hnsw 索引。
注：失败状态下表内本无有效切片，TRUNCATE 仅为防御旧维度残留数据阻断 ALTER。
"""

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.execute("TRUNCATE TABLE knowledge.document_embeddings")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_embeddings_vector")
    op.execute("ALTER TABLE knowledge.document_embeddings ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX idx_embeddings_vector ON knowledge.document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')"
    )


def downgrade():
    op.execute("TRUNCATE TABLE knowledge.document_embeddings")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_embeddings_vector")
    op.execute("ALTER TABLE knowledge.document_embeddings ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX idx_embeddings_vector ON knowledge.document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')"
    )
