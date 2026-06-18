"""backfill steps_text for existing test_cases

Revision ID: 009
Revises: 008
"""

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # 批量回填 steps_text: title + steps[*].action 拼接
    # 使用单条 SQL 覆盖全部 NULL 行；若数据量巨大可拆分批次，
    # 当前 MVP 阶段数据量可控，单次执行即可。
    op.execute("""
        UPDATE testcase.test_cases
        SET steps_text = title || ' ' || COALESCE(
            (
                SELECT string_agg(elem->>'action', ' ')
                FROM jsonb_array_elements(steps) AS elem
                WHERE elem->>'action' IS NOT NULL
            ),
            ''
        )
        WHERE steps_text IS NULL
    """)


def downgrade():
    # 回滚：清空 steps_text 列（列本身由 008 管理）
    op.execute("UPDATE testcase.test_cases SET steps_text = NULL")
