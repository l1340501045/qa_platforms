/**
 * 文档解析产物（知识图谱）API — 对接 GET /documents/:id/knowledge-graph
 * 返回 Stage 1 GraphRAG 的实体、关系、图片 AI 理解 + 统计
 */
import api from './api';
import type { KnowledgeGraph } from '../types';

export async function getKnowledgeGraph(documentId: string): Promise<KnowledgeGraph> {
  const res = await api.get(`/documents/${documentId}/knowledge-graph`);
  return res.data;
}
