"""add testcase.rules table + test_points.rule_id（规则台账）

规则台账：沿 PRD 章节树抽出的「明示业务规则」逐条落库，作为测试点/用例的覆盖锚点。
test_points.rule_id 为软关联（不加强外键）：兼容历史批次（无 rule_id）与落库顺序，
落库时由 callbacks 把规则码（R-001）解析为 rules.id 真实 UUID 后写入。

Revision ID: 016
Revises: 015
"""

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.execute(
        """
        CREATE TABLE testcase.rules (
            id uuid PRIMARY KEY,
            batch_id uuid NOT NULL
                REFERENCES testcase.test_batches(id) ON DELETE CASCADE ON UPDATE CASCADE,
            rule_code varchar(50) NOT NULL,
            module varchar(255) NOT NULL DEFAULT '',
            rule text NOT NULL,
            source_quote text NOT NULL DEFAULT '',
            category varchar(50) NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_rules_batch_id ON testcase.rules(batch_id)")
    # 软关联：不加强外键，容忍历史批次（rule_id=NULL）与落库顺序
    op.execute("ALTER TABLE testcase.test_points ADD COLUMN rule_id uuid NULL")


def downgrade():
    op.execute("ALTER TABLE testcase.test_points DROP COLUMN IF EXISTS rule_id")
    op.execute("DROP INDEX IF EXISTS testcase.ix_rules_batch_id")
    op.execute("DROP TABLE IF EXISTS testcase.rules")
