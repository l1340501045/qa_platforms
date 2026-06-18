/**
 * 搜索 API — 对齐 GET /api/v1/cases/search
 */
import api from './api';
import type { SearchParams, SearchResponse } from '../types';

/** 全局用例搜索 */
export async function searchCases(params: SearchParams): Promise<SearchResponse> {
  const res = await api.get('/cases/search', { params });
  return res.data;
}
