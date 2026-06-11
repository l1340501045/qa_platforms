"""add duplicate_of column to test_cases (dedup 关卡产出)

记录近重复簇的规范用例逻辑 id；非重复或簇内规范用例为 NULL。

Revision ID: 014
Revises: 013
"""

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("test_cases", sa.Column("duplicate_of", sa.String(50), nullable=True), schema="testcase")


def downgrade():
    op.drop_column("test_cases", "duplicate_of", schema="testcase")
