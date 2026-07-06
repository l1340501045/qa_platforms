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
  ApiError,
} from '../types';

export interface ExportListParams extends PaginationParams {
  status?: ExportStatus;
}

export interface ExportDownload {
  blob: Blob;
  filename: string;
}

function extractFilename(contentDisposition: string | undefined, fallback: string): string {
  if (!contentDisposition) return fallback;

  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return encodedMatch[1];
    }
  }

  const quotedMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  return quotedMatch?.[1] || fallback;
}

function isApiErrorPayload(value: unknown): value is ApiError {
  return (
    typeof value === 'object' &&
    value !== null &&
    'message' in value &&
    typeof (value as { message?: unknown }).message === 'string'
  );
}

async function parseBlobApiError(error: unknown): Promise<ApiError | null> {
  const data = (error as { response?: { data?: unknown } })?.response?.data;
  if (!(data instanceof Blob)) return null;

  try {
    const parsed = JSON.parse(await data.text()) as unknown;
    return isApiErrorPayload(parsed) ? parsed : null;
  } catch {
    return null;
  }
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

/** 下载导出文件 GET /exports/:id/download */
export async function downloadExportFile(exportId: string, fallbackFilename: string): Promise<ExportDownload> {
  try {
    const res = await api.get<Blob>(`/exports/${exportId}/download`, {
      responseType: 'blob',
    });
    return {
      blob: res.data,
      filename: extractFilename(res.headers['content-disposition'], fallbackFilename),
    };
  } catch (err) {
    const apiError = await parseBlobApiError(err);
    throw apiError || err;
  }
}
