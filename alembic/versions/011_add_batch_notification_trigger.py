"""add trigger to auto-create notifications on batch status change

Revision ID: 011
Revises: 010

将通知创建从"HTTP 回调端点"改为 DB 触发器，原因：
- 真实写入路径在 testcase_generator（第一段冻结），直接 UPDATE test_batches.status
- testcase_generator 从不调用 platform_api 的 /internal/callbacks/* HTTP 端点
- 触发器覆盖所有 status 变更路径（generator 完成/失败/挂起）

触发条件守卫：
- WHEN (NEW.status IS DISTINCT FROM OLD.status AND NEW.status IN ('pending_review','failed','suspended'))
- 避免 retry 流程（running↔failed 来回切）重复发通知
"""

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # 创建通知触发器函数
    op.execute("""
        CREATE OR REPLACE FUNCTION testcase.notify_on_batch_status_change()
        RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.status = 'pending_review' THEN
                INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
                VALUES (
                    'batch_completed',
                    '用例生成完成',
                    '共生成 ' || COALESCE(NEW.total_cases::text, '0') || ' 条用例，请前往 Review',
                    'batch',
                    NEW.id,
                    'system'
                );
            ELSIF NEW.status = 'failed' THEN
                INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
                VALUES (
                    'batch_failed',
                    '用例生成失败',
                    '在 ' || COALESCE(NEW.current_stage, 'unknown') || ' 阶段发生错误，可尝试重试',
                    'batch',
                    NEW.id,
                    'system'
                );
            ELSIF NEW.status = 'suspended' THEN
                INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
                VALUES (
                    'batch_suspended',
                    '用例生成需要人工确认',
                    '流程已暂停，请前往确认',
                    'batch',
                    NEW.id,
                    'system'
                );
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 创建 AFTER UPDATE 触发器（带条件守卫）
    op.execute("""
        CREATE TRIGGER trg_batch_status_notify
        AFTER UPDATE OF status
        ON testcase.test_batches
        FOR EACH ROW
        WHEN (NEW.status IS DISTINCT FROM OLD.status
              AND NEW.status IN ('pending_review', 'failed', 'suspended'))
        EXECUTE FUNCTION testcase.notify_on_batch_status_change();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_batch_status_notify ON testcase.test_batches")
    op.execute("DROP FUNCTION IF EXISTS testcase.notify_on_batch_status_change()")
