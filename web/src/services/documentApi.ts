/**
 * 文档管理 API — 对齐契约 §4.9-4.14
 */
import api from './api';
import type {
  Document,
  DocumentDetail,
  DocAssociations,
  DocumentAssociation,
  PaginatedData,
  PaginationParams,
  UploadResult,
  CreateDocAssociationRequest,
  DocType,
  DocStatus,
} from '../types';

export interface DocumentFilterParams extends PaginationParams {
  doc_type?: DocType;
  status?: DocStatus;
}

/** 批量上传文档 POST /systems/:id/documents/batch
 *
 * 支持 zip / 单个 .md / 文件夹（含图片）。
 * 文件夹上传时用 webkitRelativePath 作为 filename，后端据此保留相对路径以解析图片。
 */
export async function batchUploadDocuments(
  systemId: string,
  files: File[],
): Promise<UploadResult> {
  const formData = new FormData();
  files.forEach((file) => {
    const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
    formData.append('files', file, relativePath || file.name);
  });

  const res = await api.post(`/systems/${systemId}/documents/batch`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000, // 上传给 2 分钟超时
  });
  return res.data;
}

/** 文档列表 GET /systems/:id/documents */
export async function listDocuments(
  systemId: string,
  params?: DocumentFilterParams,
): Promise<PaginatedData<Document>> {
  const res = await api.get(`/systems/${systemId}/documents`, { params });
  return res.data;
}

/** 文档详情 GET /documents/:id */
export async function getDocument(documentId: string): Promise<DocumentDetail> {
  const res = await api.get(`/documents/${documentId}`);
  return res.data;
}

/** 删除文档 DELETE /documents/:id */
export async function deleteDocument(documentId: string): Promise<void> {
  await api.delete(`/documents/${documentId}`);
}

/** 创建文档关联 POST /documents/:id/associations */
export async function createDocAssociation(
  documentId: string,
  params: CreateDocAssociationRequest,
): Promise<DocumentAssociation> {
  const res = await api.post(`/documents/${documentId}/associations`, params);
  return res.data;
}

/** 获取文档关联 GET /documents/:id/associations */
export async function getDocAssociations(
  documentId: string,
  depth = 1,
): Promise<DocAssociations> {
  const res = await api.get(`/documents/${documentId}/associations`, {
    params: { depth },
  });
  return res.data;
}
