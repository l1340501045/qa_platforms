/**
 * Testcase Store — 批次管理 + 用例 + 轮询 + Gate 澄清
 * 对齐契约：合并端点、page/per_page 分页、连字符阶段名
 */
import { create } from 'zustand';
import type {
  BatchDetail,
  BatchInfo,
  StageInfo,
  TestCase,
  OpenQuestion,
  ClarifyAnswer,
  ReviewStatus,
} from '../types';
import {
  getBatchDetail,
  submitClarification,
  triggerIterate,
  archiveBatch,
  reviewTestCase,
  triggerGeneration,
} from '../services/batchApi';
import type { BatchQueryParams } from '../services/batchApi';

interface TestcaseState {
  // 批次信息
  batch: BatchInfo | null;
  stages: StageInfo[];
  openQuestions: OpenQuestion[] | null;
  batchLoading: boolean;

  // 用例列表
  cases: TestCase[];
  casesTotal: number;
  casesPage: number;
  casesPerPage: number;
  casesTotalPages: number;
  casesLoading: boolean;
  reviewFilter: ReviewStatus | undefined;

  // 轮询状态
  isPolling: boolean;
  pollTimer: number | null;
  pollFailCount: number;

  // Actions
  generateBatch: (documentId: string) => Promise<string>;
  fetchBatchDetail: (batchId: string, params?: BatchQueryParams) => Promise<void>;
  startPolling: (batchId: string) => void;
  stopPolling: () => void;
  submitClarification: (batchId: string, answers: ClarifyAnswer[]) => Promise<void>;
  reviewCase: (caseId: string, action: 'confirmed' | 'needs_modification' | 'deleted', comment?: string) => Promise<void>;
  triggerIterate: (batchId: string, modifiedCaseIds: string[]) => Promise<void>;
  archiveBatch: (batchId: string) => Promise<void>;
  setReviewFilter: (filter: ReviewStatus | undefined) => void;
  clearBatch: () => void;
}

/** 轮询终止状态 — completed 是中间态（后端会自动转 pending_review），不终止 */
const POLL_STOP_STATUSES = new Set(['pending_review', 'reviewing', 'archived', 'failed']);

export const useTestcaseStore = create<TestcaseState>((set, get) => ({
  batch: null,
  stages: [],
  openQuestions: null,
  batchLoading: false,

  cases: [],
  casesTotal: 0,
  casesPage: 1,
  casesPerPage: 20,
  casesTotalPages: 0,
  casesLoading: false,
  reviewFilter: undefined,

  isPolling: false,
  pollTimer: null,
  pollFailCount: 0,

  generateBatch: async (documentId: string) => {
    const resp = await triggerGeneration(documentId);
    return resp.batch_id;
  },

  fetchBatchDetail: async (batchId: string, params?: BatchQueryParams) => {
    set({ batchLoading: true });
    try {
      const detail: BatchDetail = await getBatchDetail(batchId, params);
      set({
        batch: detail.batch,
        stages: detail.stage_progress?.stages || [],
        openQuestions: detail.open_questions,
        cases: detail.cases.items,
        casesTotal: detail.cases.total,
        casesPage: detail.cases.page,
        casesPerPage: detail.cases.per_page,
        casesTotalPages: detail.cases.total_pages,
      });
    } finally {
      set({ batchLoading: false });
    }
  },

  startPolling: (batchId: string) => {
    const { stopPolling } = get();
    stopPolling();

    const poll = async () => {
      try {
        const { casesPage, casesPerPage, reviewFilter } = get();
        const detail = await getBatchDetail(batchId, {
          page: casesPage,
          per_page: casesPerPage,
          review_status: reviewFilter,
        });
        set({
          batch: detail.batch,
          stages: detail.stage_progress?.stages || [],
          openQuestions: detail.open_questions,
          cases: detail.cases.items,
          casesTotal: detail.cases.total,
          casesPage: detail.cases.page,
          casesPerPage: detail.cases.per_page,
          casesTotalPages: detail.cases.total_pages,
          pollFailCount: 0,
        });

        // 终止条件：到达终态
        if (detail.batch.status && POLL_STOP_STATUSES.has(detail.batch.status)) {
          get().stopPolling();
        }
      } catch {
        const failCount = get().pollFailCount + 1;
        set({ pollFailCount: failCount });
        // 连续 3 次失败停止轮询
        if (failCount >= 3) {
          get().stopPolling();
        }
      }
    };

    // 立即执行一次
    poll();
    const timer = window.setInterval(poll, 5000);
    set({ pollTimer: timer, isPolling: true, pollFailCount: 0 });
  },

  stopPolling: () => {
    const { pollTimer } = get();
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
    }
    set({ pollTimer: null, isPolling: false });
  },

  submitClarification: async (batchId: string, answers: ClarifyAnswer[]) => {
    await submitClarification(batchId, { answers });
    // 提交后恢复轮询
    get().startPolling(batchId);
  },

  reviewCase: async (
    caseId: string,
    action: 'confirmed' | 'needs_modification' | 'deleted',
    comment?: string,
  ) => {
    const resp = await reviewTestCase(caseId, { action, comment });
    // 局部更新用例状态
    set((state) => ({
      cases: state.cases.map((c) =>
        c.id === caseId
          ? { ...c, review_status: resp.review_status, review_comment: resp.review_comment, updated_at: resp.updated_at }
          : c,
      ),
    }));
  },

  triggerIterate: async (batchId: string, modifiedCaseIds: string[]) => {
    await triggerIterate(batchId, modifiedCaseIds);
    // 迭代后恢复轮询
    get().startPolling(batchId);
  },

  archiveBatch: async (batchId: string) => {
    const resp = await archiveBatch(batchId);
    set((state) => ({
      batch: state.batch ? { ...state.batch, status: resp.status } : null,
    }));
  },

  setReviewFilter: (filter: ReviewStatus | undefined) => {
    set({ reviewFilter: filter });
  },

  clearBatch: () => {
    get().stopPolling();
    set({
      batch: null,
      stages: [],
      openQuestions: null,
      cases: [],
      casesTotal: 0,
      reviewFilter: undefined,
    });
  },
}));
