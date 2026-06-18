"""add steps_text column and GIN index to test_cases

Revision ID: 008
Revises: 007
"""

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # 新增 steps_text 列（应用层写入时计算填充）
    op.add_column(
        "test_cases",
        sa.Column("steps_text", sa.Text(), nullable=True),
        schema="testcase",
    )

    # 创建 pg_trgm GIN 索引用于中文模糊搜索
    op.execute("CREATE INDEX idx_test_cases_trgm ON testcase.test_cases USING GIN (steps_text gin_trgm_ops)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS testcase.idx_test_cases_trgm")
    op.drop_column("test_cases", "steps_text", schema="testcase")
