import {
  VIEWABLE_BATCH_STATUSES,
  formatViewableBatchStatus,
  isViewableBatchStatus,
} from './batchVisibility.ts';

export const CASE_ASSET_VISIBLE_BATCH_STATUSES = VIEWABLE_BATCH_STATUSES;

export interface CaseAssetBatchScopeItem {
  document_title: string;
  status: string;
  total_cases: number | null;
  created_at: string;
}

interface CaseAssetBatchScopeInput {
  selectedBatch?: CaseAssetBatchScopeItem;
  batchError?: string | null;
  visibleBatchCount: number;
}

export function isCaseAssetVisibleBatch(status: string): boolean {
  return isViewableBatchStatus(status);
}

export function formatCaseAssetBatchStatus(status: string): string {
  return formatViewableBatchStatus(status);
}

export function buildCaseAssetBatchScopeLabel({
  selectedBatch,
  batchError,
}: CaseAssetBatchScopeInput): string {
  if (selectedBatch) {
    return `${selectedBatch.document_title} · ${formatCaseAssetBatchStatus(selectedBatch.status)}`;
  }
  if (batchError) return '默认：各文档最新可见批次（批次列表未加载）';
  return '默认：各文档最新可见批次';
}

export function buildCaseAssetBatchScopeHelp({
  selectedBatch,
  batchError,
  visibleBatchCount,
}: CaseAssetBatchScopeInput): string {
  if (selectedBatch) {
    const totalCases = selectedBatch.total_cases ?? 0;
    const date = new Date(selectedBatch.created_at).toLocaleDateString('zh-CN');
    return `正在查看该批次生成的资产：${date} · ${totalCases} 例 · ${formatCaseAssetBatchStatus(selectedBatch.status)}。`;
  }
  if (batchError) {
    return '批次列表加载失败，但资产仍按后端默认规则展示；不能据此判断没有历史批次。';
  }
  if (visibleBatchCount === 0) {
    return '未指定批次时，后端会按每份文档最新的待审阅/已完成/已落库批次聚合；当前没有可手动选择的可见批次。';
  }
  return `未指定批次时，后端会按每份文档最新的待审阅/已完成/已落库批次聚合；当前可手动选择 ${visibleBatchCount} 个可见批次。`;
}
