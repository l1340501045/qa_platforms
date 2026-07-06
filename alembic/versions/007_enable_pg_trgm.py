"""enable pg_trgm extension

Revision ID: 007
Revises: 006
"""

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade():
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
