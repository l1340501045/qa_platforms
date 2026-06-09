"""create indexes for all schemas

Revision ID: 004
Revises: 003
"""

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # ===== knowledge schema indexes =====

    # documents indexes
    op.create_index(
        "idx_documents_system_id",
        "documents",
        ["system_id"],
        schema="knowledge",
    )

    op.create_index(
        "idx_documents_system_status",
        "documents",
        ["system_id", "embedding_status"],
        schema="knowledge",
    )

    # 部分索引：排除已删除的文档
    op.execute("CREATE INDEX idx_documents_deleted_at ON knowledge.documents (deleted_at) WHERE deleted_at IS NULL")

    # 唯一索引：content_hash 排除已删除
    op.execute("CREATE UNIQUE INDEX idx_docs_hash ON knowledge.documents (content_hash) WHERE deleted_at IS NULL")

    # document_associations indexes（部分索引排除已删除）
    op.execute(
        "CREATE INDEX idx_doc_assoc_source ON knowledge.document_associations (source_doc_id) WHERE deleted_at IS NULL"
    )

    op.execute(
        "CREATE INDEX idx_doc_assoc_target ON knowledge.document_associations (target_doc_id) WHERE deleted_at IS NULL"
    )

    op.execute(
        "CREATE INDEX idx_doc_assoc_type ON knowledge.document_associations (relation_type) WHERE deleted_at IS NULL"
    )

    # document_embeddings indexes
    op.create_index(
        "idx_embeddings_document",
        "document_embeddings",
        ["document_id"],
        schema="knowledge",
    )

    # HNSW 向量索引
    op.execute(
        "CREATE INDEX idx_embeddings_vector "
        "ON knowledge.document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ===== testcase schema indexes =====

    # test_batches indexes
    op.create_index(
        "idx_batch_system",
        "test_batches",
        ["system_id"],
        schema="testcase",
    )

    op.create_index(
        "idx_batch_status",
        "test_batches",
        ["system_id", "status"],
        schema="testcase",
    )

    # test_cases indexes
    op.create_index(
        "idx_cases_batch",
        "test_cases",
        ["batch_id"],
        schema="testcase",
    )

    op.create_index(
        "idx_cases_review",
        "test_cases",
        ["batch_id", "review_status"],
        schema="testcase",
    )

    # test_points indexes
    op.create_index(
        "idx_points_batch",
        "test_points",
        ["batch_id"],
        schema="testcase",
    )

    # stage_artifacts indexes
    op.create_index(
        "idx_artifacts_batch_stage",
        "stage_artifacts",
        ["batch_id", "stage"],
        schema="testcase",
    )

    # quality_flywheel indexes
    op.create_index(
        "idx_flywheel_system_type",
        "quality_flywheel",
        ["system_id", "modification_type"],
        schema="testcase",
    )

    # 部分索引：few-shot 候选
    op.execute(
        "CREATE INDEX idx_flywheel_few_shot "
        "ON testcase.quality_flywheel (is_few_shot_candidate) "
        "WHERE is_few_shot_candidate = true"
    )

    # golden_set_results indexes
    op.create_index(
        "idx_golden_version",
        "golden_set_results",
        ["kernel_version", "golden_set_id"],
        schema="testcase",
    )

    # export_tasks indexes
    op.create_index(
        "idx_exports_status",
        "export_tasks",
        ["status"],
        schema="testcase",
    )


def downgrade():
    # testcase schema indexes
    op.drop_index("idx_exports_status", table_name="export_tasks", schema="testcase")
    op.drop_index("idx_golden_version", table_name="golden_set_results", schema="testcase")
    op.execute("DROP INDEX IF EXISTS testcase.idx_flywheel_few_shot")
    op.drop_index("idx_flywheel_system_type", table_name="quality_flywheel", schema="testcase")
    op.drop_index("idx_artifacts_batch_stage", table_name="stage_artifacts", schema="testcase")
    op.drop_index("idx_points_batch", table_name="test_points", schema="testcase")
    op.drop_index("idx_cases_review", table_name="test_cases", schema="testcase")
    op.drop_index("idx_cases_batch", table_name="test_cases", schema="testcase")
    op.drop_index("idx_batch_status", table_name="test_batches", schema="testcase")
    op.drop_index("idx_batch_system", table_name="test_batches", schema="testcase")

    # knowledge schema indexes
    op.execute("DROP INDEX IF EXISTS knowledge.idx_embeddings_vector")
    op.drop_index("idx_embeddings_document", table_name="document_embeddings", schema="knowledge")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_doc_assoc_type")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_doc_assoc_target")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_doc_assoc_source")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_docs_hash")
    op.execute("DROP INDEX IF EXISTS knowledge.idx_documents_deleted_at")
    op.drop_index("idx_documents_system_status", table_name="documents", schema="knowledge")
    op.drop_index("idx_documents_system_id", table_name="documents", schema="knowledge")
