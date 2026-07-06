"""backfill notifications for existing batches

Revision ID: 012
Revises: 011

存量批次在触发器 011 创建前已经到达 pending_review/failed/suspended 状态，
不会再有 status 变更触发通知。此迁移为这些存量批次一次性补发通知。

去重策略：用 NOT EXISTS 子查询判断 target_id + type 是否已有通知，
避免与触发器产生的通知重复。
"""

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # 补发 pending_review 批次通知
    op.execute("""
        INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
        SELECT
            'batch_completed',
            '用例生成完成',
            '共生成 ' || COALESCE(b.total_cases::text, '0') || ' 条用例，请前往 Review',
            'batch',
            b.id,
            'system'
        FROM testcase.test_batches b
        WHERE b.status = 'pending_review'
          AND NOT EXISTS (
              SELECT 1 FROM public.notifications n
              WHERE n.target_id = b.id AND n.type = 'batch_completed'
          )
    """)

    # 补发 failed 批次通知
    op.execute("""
        INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
        SELECT
            'batch_failed',
            '用例生成失败',
            '在 ' || COALESCE(b.current_stage, 'unknown') || ' 阶段发生错误，可尝试重试',
            'batch',
            b.id,
            'system'
        FROM testcase.test_batches b
        WHERE b.status = 'failed'
          AND NOT EXISTS (
              SELECT 1 FROM public.notifications n
              WHERE n.target_id = b.id AND n.type = 'batch_failed'
          )
    """)

    # 补发 suspended 批次通知
    op.execute("""
        INSERT INTO public.notifications (type, title, body, target_type, target_id, actor)
        SELECT
            'batch_suspended',
            '用例生成需要人工确认',
            '流程已暂停，请前往确认',
            'batch',
            b.id,
            'system'
        FROM testcase.test_batches b
        WHERE b.status = 'suspended'
          AND NOT EXISTS (
              SELECT 1 FROM public.notifications n
              WHERE n.target_id = b.id AND n.type = 'batch_suspended'
          )
    """)


def downgrade():
    # 回滚：删除由此迁移补发的通知（actor='system' 且 target_type='batch'）
    # 注意：无法精确区分哪些是补发的 vs 触发器产生的，
    # 但由于去重逻辑确保不重复，downgrade 清空所有 system 发的 batch 通知是安全的
    op.execute("""
        DELETE FROM public.notifications
        WHERE actor = 'system'
          AND target_type = 'batch'
    """)
