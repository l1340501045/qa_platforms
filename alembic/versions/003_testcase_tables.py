"""create testcase schema tables

Revision ID: 003
Revises: 002
"""

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


def upgrade():
    # testcase.test_batches
    op.create_table(
        "test_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge.documents.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("current_stage", sa.String(50), nullable=True),
        sa.Column("total_cases", sa.Integer, nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column("generation_config", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.test_points
    op.create_table(
        "test_points",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature_id", sa.String(50), nullable=False),
        sa.Column("dimension", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("derived_from", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.test_cases
    op.create_table(
        "test_cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "test_point_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_points.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("preconditions", JSONB, nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("expected_results", JSONB, nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("dimensions", JSONB, nullable=False),
        sa.Column("provenance", JSONB, nullable=False),
        sa.Column("trust_level", sa.Integer, nullable=False),
        sa.Column("confidence_note", sa.Text, nullable=True),
        sa.Column("review_status", sa.String(30), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("review_comment", sa.Text, nullable=True),
        sa.Column("iteration", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.stage_artifacts
    op.create_table(
        "stage_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("artifact", JSONB, nullable=True),
        sa.Column("open_questions", JSONB, nullable=True),
        sa.Column("clarification_answers", JSONB, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.quality_flywheel
    op.create_table(
        "quality_flywheel",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "test_case_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_cases.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="RESTRICT", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("ai_version_yaml", sa.Text, nullable=False),
        sa.Column("qa_final_version_yaml", sa.Text, nullable=True),
        sa.Column("modification_reason", sa.Text, nullable=False),
        sa.Column("modification_type", sa.String(30), nullable=False),
        sa.Column("feature_types", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dimensions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_few_shot_candidate", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.golden_set_results
    op.create_table(
        "golden_set_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column("golden_set_id", sa.String(50), nullable=False),
        sa.Column("kernel_version", sa.String(20), nullable=False),
        sa.Column("coverage_overlap", sa.Float, nullable=False),
        sa.Column("ai_miss_rate", sa.Float, nullable=False),
        sa.Column("ai_valuable_addition_rate", sa.Float, nullable=False),
        sa.Column("direct_usability_rate", sa.Float, nullable=False),
        sa.Column("gate_accuracy", sa.Float, nullable=True),
        sa.Column("detail_report", JSONB, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        schema="testcase",
    )

    # testcase.export_tasks
    op.create_table(
        "export_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("testcase.test_batches.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "system_id",
            UUID(as_uuid=True),
            sa.ForeignKey("public.systems.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column("export_scope", sa.String(20), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'processing'")),
        sa.Column("file_url", sa.String(1000), nullable=True),
        sa.Column("total_cases", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema="testcase",
    )


def downgrade():
    op.drop_table("export_tasks", schema="testcase")
    op.drop_table("golden_set_results", schema="testcase")
    op.drop_table("quality_flywheel", schema="testcase")
    op.drop_table("stage_artifacts", schema="testcase")
    op.drop_table("test_cases", schema="testcase")
    op.drop_table("test_points", schema="testcase")
    op.drop_table("test_batches", schema="testcase")
