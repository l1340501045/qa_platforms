/**
 * 批次与用例 API — 对齐契约 §4.15-4.19
 */
import api from './api';
import type {
  BatchDetail,
  GenerateResponse,
  ClarifyResponse,
  ClarifyRequest,
  IterateResponse,
  ArchiveResponse,
  ReviewResponse,
  ReviewRequest,
  PaginationParams,
  ReviewStatus,
} from '../types';

export interface BatchQueryParams extends PaginationParams {
  review_status?: ReviewStatus;
}

/** 触发用例生成 POST /documents/:id/generate → 202 */
export async function triggerGeneration(documentId: string): Promise<GenerateResponse> {
  const res = await api.post(`/documents/${documentId}/generate`);
  return res.data;
}

/** 获取批次详情（合并响应）GET /batches/:id */
export async function getBatchDetail(
  batchId: string,
  params?: BatchQueryParams,
): Promise<BatchDetail> {
  const res = await api.get(`/batches/${batchId}`, { params });
  return res.data;
}

/** 提交澄清 POST /batches/:id/clarify */
export async function submitClarification(
  batchId: string,
  body: ClarifyRequest,
): Promise<ClarifyResponse> {
  const res = await api.post(`/batches/${batchId}/clarify`, body);
  return res.data;
}

/** 触发迭代 POST /batches/:id/iterate → 202 */
export async function triggerIterate(
  batchId: string,
  modifiedCaseIds: string[],
  feedback?: Record<string, string>,
): Promise<IterateResponse> {
  const res = await api.post(`/batches/${batchId}/iterate`, {
    modified_case_ids: modifiedCaseIds,
    feedback,
  });
  return res.data;
}

/** 落库归档 POST /batches/:id/archive */
export async function archiveBatch(batchId: string): Promise<ArchiveResponse> {
  const res = await api.post(`/batches/${batchId}/archive`);
  return res.data;
}

/** Review 用例 PATCH /testcases/:id/review */
export async function reviewTestCase(
  caseId: string,
  body: ReviewRequest,
): Promise<ReviewResponse> {
  const res = await api.patch(`/testcases/${caseId}/review`, body);
  return res.data;
}
