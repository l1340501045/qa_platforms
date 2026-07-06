export const VIEWABLE_BATCH_STATUSES = ['pending_review', 'completed', 'archived'] as const;

const VIEWABLE_BATCH_STATUS_LABELS: Record<string, string> = {
  pending_review: '待审阅',
  completed: '已完成',
  archived: '已落库',
};

export function isViewableBatchStatus(status: string): boolean {
  return VIEWABLE_BATCH_STATUSES.includes(
    status as (typeof VIEWABLE_BATCH_STATUSES)[number],
  );
}

export function formatViewableBatchStatus(status: string): string {
  return VIEWABLE_BATCH_STATUS_LABELS[status] || status;
}
