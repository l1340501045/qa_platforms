/**
 * Cheat Sheet（知识速查表）API — 对接 ②a 后端
 * 端点：documents/:id/cheat-sheets[/extract|/batch-approve]、cheat-sheets/:id[/review]
 */
import api from './api';
import type {
  CheatSheetItem,
  CheatSheetReviewStatus,
  CheatSheetType,
  PaginatedData,
} from '../types';

export interface CheatSheetListParams {
  page?: number;
  per_page?: number;
  type?: CheatSheetType;
  status?: CheatSheetReviewStatus;
}

/** 列出某文档最新版 cheat sheet 条目 GET /documents/:id/cheat-sheets */
export async function listCheatSheetItems(
  documentId: string,
  params?: CheatSheetListParams,
): Promise<PaginatedData<CheatSheetItem>> {
  const res = await api.get(`/documents/${documentId}/cheat-sheets`, { params });
  return res.data;
}

/** 触发提取 POST /documents/:id/cheat-sheets/extract → 202 */
export interface ExtractResult {
  enabled: boolean;
  sheet_id?: string;
  version?: number;
  message?: string;
}
export async function extractCheatSheets(documentId: string): Promise<ExtractResult> {
  const res = await api.post(`/documents/${documentId}/cheat-sheets/extract`);
  return res.data;
}

/** 批量通过 POST /documents/:id/cheat-sheets/batch-approve */
export async function batchApproveCheatSheets(
  documentId: string,
  body: { sheet_type: CheatSheetType; tier?: string; by?: string },
): Promise<{ updated_count: number }> {
  const res = await api.post(`/documents/${documentId}/cheat-sheets/batch-approve`, body);
  return res.data;
}

/** 单条详情 GET /cheat-sheets/:id */
export async function getCheatSheetItem(itemId: string): Promise<CheatSheetItem> {
  const res = await api.get(`/cheat-sheets/${itemId}`);
  return res.data;
}

/** 编辑 QA 版内容 PATCH /cheat-sheets/:id */
export async function editCheatSheetItem(
  itemId: string,
  qaContent: Record<string, unknown>,
): Promise<CheatSheetItem> {
  const res = await api.patch(`/cheat-sheets/${itemId}`, { qa_content: qaContent });
  return res.data;
}

/** 审核单条 PATCH /cheat-sheets/:id/review */
export async function reviewCheatSheetItem(
  itemId: string,
  body: { status: 'approved' | 'rejected'; comment?: string; by?: string },
): Promise<CheatSheetItem> {
  const res = await api.patch(`/cheat-sheets/${itemId}/review`, body);
  return res.data;
}
