/**
 * 全局 TypeScript 类型定义
 * 与 platform-api contracts.md 严格对齐
 */

// ═══════════════════════════════════════════════════════════════════════════════
// 统一响应结构（契约 §2）
// ═══════════════════════════════════════════════════════════════════════════════

/** 成功响应信封 */
export interface ApiResponse<T> {
  code: number; // 0 表示成功
  message: string; // "success" 或错误描述
  data: T;
}

/** 错误响应信封 */
export interface ApiError {
  error_code: string; // 如 "E4001"
  message: string; // 人类可读说明
  request_id: string; // 请求唯一 ID
}

/** 分页响应结构（契约要求 page/per_page/total_pages） */
export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/** 分页请求参数 */
export interface PaginationParams {
  page?: number;
  per_page?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

// ═══════════════════════════════════════════════════════════════════════════════
// 枚举类型（对齐契约）
// ═══════════════════════════════════════════════════════════════════════════════

/** 批次状态 8 态（契约 §4.16） */
export type BatchStatus =
  | 'pending' // 等待 Worker 拾取
  | 'running' // 流水线执行中
  | 'suspended' // Gate NO_GO 等待澄清
  | 'completed' // 流水线完成
  | 'pending_review' // 等待 QA review
  | 'reviewing' // QA review 中
  | 'archived' // 已落库
  | 'failed'; // 执行失败

/** Review 状态（契约 §4.20） */
export type ReviewStatus = 'pending' | 'confirmed' | 'needs_modification' | 'deleted';

/** 文档类型（契约 §4.9） */
export type DocType =
  | 'prd'
  | 'tech_doc'
  | 'test_rule'
  | 'test_case'
  | 'bug_record'
  | 'prototype'
  | 'other';

/** 文档状态 */
export type DocStatus = 'uploading' | 'uploaded' | 'importing' | 'imported' | 'import_failed';

/** 优先级 */
export type Priority = 'P0' | 'P1' | 'P2' | 'P3';

/** 文档关联类型 */
export type DocRelationType =
  | 'req_to_tech'
  | 'req_to_case'
  | 'req_to_bug'
  | 'req_to_proto'
  | 'tech_to_case'
  | 'case_to_bug'
  | 'general';

/** 系统关联类型 */
export type SystemRelationType = 'api_call' | 'data_share' | 'event';

/** Gate 评审结果 */
export type GateResult = 'GO' | 'CONDITIONAL' | 'NO_GO';

/** 阶段状态 */
export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'suspended';

/** 导出格式 */
export type ExportFormat = 'markdown' | 'excel';

/** 导出范围 */
export type ExportScope = 'batch' | 'system';

/** 导出状态 */
export type ExportStatus = 'processing' | 'completed' | 'failed';

// ═══════════════════════════════════════════════════════════════════════════════
// 业务实体类型
// ═══════════════════════════════════════════════════════════════════════════════

// ─── 系统 ───

export interface System {
  id: string;
  name: string;
  description: string | null;
  document_count?: number;
  batch_count?: number;
  created_at: string;
  updated_at: string;
}

export interface SystemDetail extends System {
  associations: SystemAssociationInfo[];
}

export interface SystemAssociationInfo {
  id: string;
  target_system: { id: string; name: string };
  relation_type: SystemRelationType;
  description: string | null;
}

export interface SystemAssociation {
  id: string;
  source_system_id: string;
  target_system_id: string;
  relation_type: SystemRelationType;
  description: string | null;
  created_at: string;
}

export interface SystemAssociations {
  outgoing: Array<{
    id: string;
    target_system: { id: string; name: string };
    relation_type: SystemRelationType;
    description: string | null;
  }>;
  incoming: Array<{
    id: string;
    source_system: { id: string; name: string };
    relation_type: SystemRelationType;
    description: string | null;
  }>;
}

// ─── 文档 ───

export interface Document {
  id: string;
  title: string;
  doc_type: DocType;
  folder_path: string | null;
  status: DocStatus;
  association_count?: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends Document {
  storage_path: string;
  content_url: string;
  metadata: Record<string, unknown> | null;
  associations: DocAssociationInfo[];
  prototype_links: PrototypeLink[];
}

export interface DocAssociationInfo {
  id: string;
  target_document: { id: string; title: string; doc_type: string };
  relation_type: DocRelationType;
}

export interface DocumentAssociation {
  id: string;
  source_doc_id: string;
  target_doc_id: string;
  relation_type: DocRelationType;
  created_at: string;
}

export interface DocAssociations {
  direct: Array<{
    id: string;
    document: { id: string; title: string; doc_type: string };
    relation_type: DocRelationType;
    direction: 'outgoing' | 'incoming';
  }>;
  indirect: Array<{
    document: { id: string; title: string; doc_type: string };
    path: string[];
    depth: number;
  }>;
}

export interface PrototypeLink {
  id: string;
  url: string;
  note: string | null;
}

// ─── 上传结果 ───

export interface UploadResult {
  uploaded: Array<{
    id: string;
    title: string;
    doc_type: DocType;
    folder_path: string | null;
    status: 'uploading';
  }>;
  skipped: Array<{
    filename: string;
    reason: string;
  }>;
  failed: Array<{
    filename: string;
    error: string;
  }>;
  image_count?: number;
  summary: {
    total_files: number;
    uploaded_count: number;
    skipped_count: number;
    failed_count: number;
    image_count?: number;
  };
}

// ─── 测试批次 ───

export interface StageInfo {
  name: string;
  status: StageStatus;
  progress?: number;
  duration_ms?: number;
  gate_result?: GateResult;
}

export interface StageProgress {
  current_stage: string;
  stage_progress: number;
  total_stages: number;
  completed_stages: number;
  stages: StageInfo[];
}

export interface BatchInfo {
  id: string;
  document_id: string;
  document_title?: string;
  system_id?: string;
  status: BatchStatus;
  current_stage: string | null;
  total_cases: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface OpenQuestion {
  id: string;
  question: string;
  context: string;
  priority: 'high' | 'medium' | 'low';
}

/** 批次详情合并响应（实际 API 返回结构）
 * stage_progress 是顶层字段（与 batch 同级），包含完整 5 字段
 */
export interface BatchDetail {
  batch: BatchInfo;
  stage_progress: StageProgress;
  cases: PaginatedData<TestCase>;
  open_questions: OpenQuestion[] | null;
}

// ─── 测试用例 ───

export interface TestStep {
  step_number: number;
  action: string;
  input_data: string;
  expected_result: string;
}

export interface Provenance {
  derived_from: string[];
  source_section: string;
  verbatim_excerpt: string;
  trust_level: number;
}

export interface TestCase {
  id: string;
  batch_id: string;
  test_point_id: string | null;
  title: string;
  preconditions: string[];
  steps: TestStep[];
  expected_results: string[];
  priority: Priority;
  dimensions: string[];
  provenance: Provenance;
  trust_level: number;
  confidence_note: string | null;
  review_status: ReviewStatus;
  review_comment: string | null;
  iteration: number;
  created_at: string;
  updated_at: string;
}

// ─── 生成/澄清/迭代/归档响应 ───

export interface GenerateResponse {
  batch_id: string;
  status: 'pending';
  current_stage: string;
  created_at: string;
}

export interface ClarifyResponse {
  batch_id: string;
  status: 'running';
  message: string;
}

export interface IterateResponse {
  batch_id: string;
  status: 'running';
  iteration: number;
  cases_to_regenerate: number;
}

export interface ArchiveResponse {
  batch_id: string;
  status: 'archived';
  archived_count: number;
  archived_at: string;
}

export interface ReviewResponse {
  id: string;
  title: string;
  review_status: ReviewStatus;
  review_comment: string | null;
  updated_at: string;
}

// ─── 导出任务 ───

export interface ExportTask {
  id: string;
  export_scope: ExportScope;
  format: ExportFormat;
  status: ExportStatus;
  file_url: string | null;
  total_cases: number | null;
  error_message?: string | null;
  created_at: string;
  completed_at: string | null;
}

// ─── 请求体类型 ───

export interface CreateSystemRequest {
  name: string;
  description?: string;
}

export interface UpdateSystemRequest {
  name: string;
  description?: string;
}

export interface CreateSystemAssociationRequest {
  target_system_id: string;
  relation_type: SystemRelationType;
  description?: string;
}

export interface CreateDocAssociationRequest {
  target_document_id: string;
  relation_type: DocRelationType;
}

export interface ClarifyAnswer {
  question_id: string;
  answer: string;
}

export interface ClarifyRequest {
  answers: ClarifyAnswer[];
}

export interface ReviewRequest {
  action: 'confirmed' | 'needs_modification' | 'deleted';
  comment?: string;
}

export interface IterateRequest {
  modified_case_ids: string[];
  feedback?: Record<string, string>;
}

export interface CreateExportRequest {
  scope: ExportScope;
  batch_id?: string;
  system_id?: string;
  format: ExportFormat;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 搜索相关类型（契约 §3.8）
// ═══════════════════════════════════════════════════════════════════════════════

/** 搜索结果条目 */
export interface SearchResultItem {
  id: string;
  title: string;
  priority: Priority;
  trust_level: number;
  review_status: ReviewStatus;
  system_id: string;
  system_name: string;
  document_id: string;
  document_title: string;
  batch_id: string;
  score: number;
  created_at: string;
}

/** 搜索响应 */
export interface SearchResponse extends PaginatedData<SearchResultItem> {
  query: string;
}

/** 搜索请求参数 */
export interface SearchParams {
  q: string;
  system_id?: string;
  priority?: Priority;
  review_status?: ReviewStatus;
  page?: number;
  per_page?: number;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 通知相关类型
// ═══════════════════════════════════════════════════════════════════════════════

/** 通知类型 */
export type NotificationType = 'batch_completed' | 'batch_failed' | 'batch_suspended';

/** 通知条目 */
export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  target_type: string | null;
  target_id: string | null;
  read: boolean;
  actor: string;
  created_at: string;
}

/** 未读数响应 */
export interface UnreadCountResponse {
  count: number;
}

/** 全部标记已读响应 */
export interface MarkAllReadResponse {
  updated_count: number;
}

// ═══════════════════════════════════════════════════════════════════════════════
// 用例树相关类型
// ═══════════════════════════════════════════════════════════════════════════════

/** 用例树节点 — 用例级 */
export interface CaseTreeCase {
  id: string;
  title: string;
  priority: Priority;
  trust_level: number;
  review_status: ReviewStatus;
}

/** 用例树节点 — 模块级 */
export interface CaseTreeModule {
  module_name: string;
  case_count: number;
  cases: CaseTreeCase[];
}

/** 用例树节点 — 文档级 */
export interface CaseTreeDocument {
  document_id: string;
  document_title: string;
  modules: CaseTreeModule[];
}

/** 用例树请求参数 */
export interface CaseTreeParams {
  batch_id?: string;
  priority?: Priority;
  review_status?: ReviewStatus;
}
