"""add trigger to auto-compute steps_text on INSERT/UPDATE

Revision ID: 010
Revises: 009

将 steps_text 维护从"应用层计算"改为 DB 触发器，原因：
- 真实写入路径在 testcase_generator（第一段冻结，不可修改）
- 触发器一次性覆盖所有写入路径（新生成/迭代/未来版本写入）
- 公式与 009 回填迁移保持一致
"""

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # 创建触发器函数：从 title + steps[].action 拼接 steps_text
    op.execute("""
        CREATE OR REPLACE FUNCTION testcase.compute_steps_text()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.steps_text := NEW.title || ' ' || COALESCE(
                (
                    SELECT string_agg(elem->>'action', ' ')
                    FROM jsonb_array_elements(NEW.steps) AS elem
                    WHERE elem->>'action' IS NOT NULL
                ),
                ''
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 创建 BEFORE INSERT OR UPDATE 触发器
    op.execute("""
        CREATE TRIGGER trg_test_cases_steps_text
        BEFORE INSERT OR UPDATE OF title, steps
        ON testcase.test_cases
        FOR EACH ROW
        EXECUTE FUNCTION testcase.compute_steps_text();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_test_cases_steps_text ON testcase.test_cases")
    op.execute("DROP FUNCTION IF EXISTS testcase.compute_steps_text()")
