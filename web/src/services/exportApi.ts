/**
 * 导出 API — 对齐契约 §4.21-4.23
 */
import api from './api';
import type {
  ExportTask,
  PaginatedData,
  PaginationParams,
  CreateExportRequest,
  ExportStatus,
} from '../types';

export interface ExportListParams extends PaginationParams {
  status?: ExportStatus;
}

/** 创建导出任务 POST /exports → 202 */
export async function createExport(body: CreateExportRequest): Promise<ExportTask> {
  const res = await api.post('/exports', body);
  return res.data;
}

/** 获取导出详情 GET /exports/:id */
export async function getExport(exportId: string): Promise<ExportTask> {
  const res = await api.get(`/exports/${exportId}`);
  return res.data;
}

/** 导出列表 GET /exports */
export async function listExports(params?: ExportListParams): Promise<PaginatedData<ExportTask>> {
  const res = await api.get('/exports', { params });
  return res.data;
}
