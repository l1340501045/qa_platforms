/**
 * 系统管理 API — 对齐契约 §4.1-4.8
 */
import api from './api';
import type {
  System,
  SystemDetail,
  SystemAssociation,
  SystemAssociations,
  PaginatedData,
  PaginationParams,
  CreateSystemRequest,
  UpdateSystemRequest,
  CreateSystemAssociationRequest,
} from '../types';

/** 创建系统 POST /systems */
export async function createSystem(params: CreateSystemRequest): Promise<System> {
  const res = await api.post('/systems', params);
  return res.data;
}

/** 系统列表 GET /systems */
export async function listSystems(params?: PaginationParams): Promise<PaginatedData<System>> {
  const res = await api.get('/systems', { params });
  return res.data;
}

/** 系统详情 GET /systems/:id */
export async function getSystem(systemId: string): Promise<SystemDetail> {
  const res = await api.get(`/systems/${systemId}`);
  return res.data;
}

/** 更新系统 PUT /systems/:id */
export async function updateSystem(systemId: string, params: UpdateSystemRequest): Promise<System> {
  const res = await api.put(`/systems/${systemId}`, params);
  return res.data;
}

/** 删除系统 DELETE /systems/:id */
export async function deleteSystem(systemId: string): Promise<void> {
  await api.delete(`/systems/${systemId}`);
}

/** 创建系统关联 POST /systems/:id/associations */
export async function createSystemAssociation(
  systemId: string,
  params: CreateSystemAssociationRequest,
): Promise<SystemAssociation> {
  const res = await api.post(`/systems/${systemId}/associations`, params);
  return res.data;
}

/** 获取系统关联 GET /systems/:id/associations */
export async function getSystemAssociations(systemId: string): Promise<SystemAssociations> {
  const res = await api.get(`/systems/${systemId}/associations`);
  return res.data;
}

/** 删除系统关联 DELETE /systems/:id/associations/:assocId */
export async function deleteSystemAssociation(
  systemId: string,
  assocId: string,
): Promise<void> {
  await api.delete(`/systems/${systemId}/associations/${assocId}`);
}
