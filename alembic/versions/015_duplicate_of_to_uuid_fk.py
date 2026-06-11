"""change test_cases.duplicate_of to UUID self-FK (dedup 可 join)

把 duplicate_of 从 String(50)（存逻辑 id，DB 不可 join）改为指向 test_cases.id 的 UUID 外键。
落库时由 callbacks 将逻辑 id 解析为规范用例真实 UUID。存量值均为 NULL，转换无损。

Revision ID: 015
Revises: 014
"""

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # 存量 duplicate_of 均为 NULL，USING 转换无损
    op.execute(
        "ALTER TABLE testcase.test_cases "
        "ALTER COLUMN duplicate_of TYPE uuid USING duplicate_of::uuid"
    )
    op.execute(
        "ALTER TABLE testcase.test_cases "
        "ADD CONSTRAINT fk_test_cases_duplicate_of "
        "FOREIGN KEY (duplicate_of) REFERENCES testcase.test_cases(id) "
        "ON DELETE SET NULL ON UPDATE CASCADE"
    )


def downgrade():
    op.execute("ALTER TABLE testcase.test_cases DROP CONSTRAINT IF EXISTS fk_test_cases_duplicate_of")
    op.execute(
        "ALTER TABLE testcase.test_cases "
        "ALTER COLUMN duplicate_of TYPE varchar(50) USING duplicate_of::text"
    )
