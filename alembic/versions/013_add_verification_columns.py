"""add grounding verification columns to test_cases

verify 事实核验关卡产出：verdict（grounded/ungrounded/conflict/undefined/unverified）、
bucket（main/needs_spec/to_fix）、verification（完整核验明细 JSON）。

Revision ID: 013
Revises: 012
"""

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade():
    op.add_column("test_cases", sa.Column("verdict", sa.String(20), nullable=True), schema="testcase")
    op.add_column("test_cases", sa.Column("bucket", sa.String(20), nullable=True), schema="testcase")
    op.add_column("test_cases", sa.Column("verification", JSONB(), nullable=True), schema="testcase")
    # 便于按桶筛主集/待补规格/需修正
    op.execute("CREATE INDEX idx_test_cases_bucket ON testcase.test_cases (batch_id, bucket)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS testcase.idx_test_cases_bucket")
    op.drop_column("test_cases", "verification", schema="testcase")
    op.drop_column("test_cases", "bucket", schema="testcase")
    op.drop_column("test_cases", "verdict", schema="testcase")
