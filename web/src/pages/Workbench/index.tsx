/**
 * 用例工作台 — /batches/:batchId
 * 核心页面：阶段进度 + 用例 Review + Gate 澄清 + 迭代/落库
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  CheckOutlined,
  CloseOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';

import { useTestcaseStore } from '../../stores/testcaseStore';
import CaseTreeReview from '../../components/CaseTreeReview';
import EmptyState from '../../components/common/EmptyState';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';
import { buildDocumentReturnUrl, buildKnowledgeReturnUrl } from '../../utils/batchReturn';
import { buildSearchReturnUrl } from '../../utils/searchReturn';
import { getFailedStageDetail } from '../../utils/stageFailure';
import type {
  BatchStatus,
  CaseBucket,
  CaseTreeCase,
  CaseVerdict,
  ClarifyAnswer,
  OpenQuestion,
  ReviewIssueType,
  ReviewStatus,
} from '../../types';

const { TextArea } = Input;
const { Text } = Typography;

export function answerFromChoice(q: OpenQuestion, choice: string, custom: string): string {
  const d = q.conflict_detail;
  if (choice === 'side_a' && d) return `以 ${d.side_a.location} 为准：${d.side_a.statement}`;
  if (choice === 'side_b' && d) return `以 ${d.side_b.location} 为准：${d.side_b.statement}`;
  return custom.trim();
}

// ─── 阶段配置 ───
const STAGE_ORDER = [
  'parse',
  'comprehend',
  'gate',
  'test-points',
  'write-cases',
  'review-cases',
  'export',
] as const;

const STAGE_LABELS: Record<string, string> = {
  parse: '解析',
  comprehend: '理解',
  gate: '质量门',
  'test-points': '测试点',
  'write-cases': '用例生成',
  'review-cases': '覆盖审计',
  export: '导出',
};

// ─── 状态 Badge 映射 ───
const STATUS_BADGE_MAP: Record<BatchStatus, { status: 'default' | 'processing' | 'success' | 'error' | 'warning'; text: string }> = {
  pending: { status: 'default', text: '等待中' },
  running: { status: 'processing', text: '运行中' },
  suspended: { status: 'warning', text: '已暂停' },
  completed: { status: 'success', text: '已完成' },
  pending_review: { status: 'processing', text: '待审阅' },
  reviewing: { status: 'processing', text: '审阅中' },
  archived: { status: 'success', text: '已落库' },
  failed: { status: 'error', text: '失败' },
};

const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: '待审',
  confirmed: '已确认',
  needs_modification: '需修改',
  deleted: '已删除',
};

const REVIEW_RETURN_STATUS_LABELS: Partial<Record<BatchStatus, string>> = {
  suspended: '待澄清',
  failed: '失败',
  running: '生成中',
  pending_review: '待审核',
  pending: '排队中',
  reviewing: '审核中',
  completed: '已完成',
  archived: '已落库',
};

const GUIDANCE_BY_STATUS: Record<BatchStatus, { type: 'success' | 'info' | 'warning' | 'error'; message: string; description: string }> = {
  pending: {
    type: 'info',
    message: '任务已创建，等待 Worker 处理',
    description: '批次还没进入生成流水线；如果长时间无进展，可以重新入队。',
  },
  running: {
    type: 'info',
    message: '生成流水线正在执行',
    description: '先观察阶段进度；进入待审后再逐模块审查用例。',
  },
  suspended: {
    type: 'warning',
    message: '质量门需要澄清',
    description: '先回答阻塞问题，流水线才会继续生成后续用例。',
  },
  completed: {
    type: 'success',
    message: '生成阶段已完成',
    description: '系统正在切换到审查阶段；如果页面未自动更新，请稍后刷新或回到工作台查看。',
  },
  pending_review: {
    type: 'info',
    message: '进入用例审查',
    description: '按模块/分支浏览候选用例：正确的确认，有问题的标记需修改，废弃的删除。',
  },
  reviewing: {
    type: 'info',
    message: '审查进行中',
    description: '继续处理待审用例；需修改项确认完后可触发迭代，全部可接受后落库归档。',
  },
  archived: {
    type: 'success',
    message: '批次已落库',
    description: '本批次已经进入用例资产库，可去用例资产或导出中心继续使用。',
  },
  failed: {
    type: 'error',
    message: '生成任务失败',
    description: '可重新入队整批重跑；重跑前建议确认 Worker、Redis 和模型网关状态。',
  },
};

function getStageLabel(stageName?: string | null): string {
  if (!stageName) return '未开始';
  return STAGE_LABELS[stageName] || stageName;
}

function normalizeReviewReturnStatus(value: string | null): BatchStatus | undefined {
  if (!value) return undefined;
  return value in REVIEW_RETURN_STATUS_LABELS ? (value as BatchStatus) : undefined;
}

const Workbench: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Store
  const {
    batch,
    stages,
    openQuestions,
    batchLoading,
    reviewFilter,
    setReviewFilter,
    fetchBatchDetail,
    startPolling,
    stopPolling,
    submitClarification,
    reviewCase,
    triggerIterate,
    retryBatch,
    archiveBatch,
    clearBatch,
  } = useTestcaseStore();

  // Local state
  const [gateModalOpen, setGateModalOpen] = useState(false);
  const [clarifyAnswers, setClarifyAnswers] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [clarifySubmitting, setClarifySubmitting] = useState(false);
  const [retrySubmitting, setRetrySubmitting] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [bucketFilter, setBucketFilter] = useState<CaseBucket | undefined>();
  const [verdictFilter, setVerdictFilter] = useState<CaseVerdict | undefined>();
  const [reviewIssueTypeFilter, setReviewIssueTypeFilter] = useState<ReviewIssueType | undefined>();
  const [allCasesForIterate, setAllCasesForIterate] = useState<CaseTreeCase[]>([]);
  const [treeReloadSignal, setTreeReloadSignal] = useState(0);

  // Ref to track if gate modal was auto-shown for current suspended state
  const gateAutoShownRef = useRef(false);

  // ─── 初始化 ───
  useEffect(() => {
    if (!batchId) return;

    const init = async () => {
      try {
        await fetchBatchDetail(batchId);
      } catch (err: unknown) {
        message.error('加载批次详情失败');
      }
    };

    init();

    return () => {
      clearBatch();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId]);

  // ─── 根据状态决定是否轮询 ───
  useEffect(() => {
    if (!batchId || !batch) return;
    if (
      batch.status === 'pending' ||
      batch.status === 'running' ||
      batch.status === 'suspended' ||
      batch.status === 'completed'
    ) {
      startPolling(batchId);
    }
    return () => {
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchId, batch?.status]);

  // ─── suspended 且有 openQuestions → 自动弹窗 ───
  useEffect(() => {
    if (
      batch?.status === 'suspended' &&
      openQuestions &&
      openQuestions.length > 0 &&
      !gateAutoShownRef.current
    ) {
      gateAutoShownRef.current = true;
      setGateModalOpen(true);
    }
    if (batch?.status !== 'suspended') {
      gateAutoShownRef.current = false;
    }
  }, [batch?.status, openQuestions]);

  // ─── 筛选/搜索（交给 CaseTreeReview：reviewFilter 走后端 case-tree，searchKeyword 前端跨模块过滤） ───
  const handleFilterChange = useCallback(
    (value: ReviewStatus | undefined) => {
      setReviewFilter(value);
    },
    [setReviewFilter],
  );

  const handleSearch = useCallback((value: string) => {
    setSearchKeyword(value.trim());
  }, []);

  // ─── 澄清提交 ───
  const handleClarifySubmit = useCallback(async () => {
    if (!batchId || !openQuestions) return;

    const answers: ClarifyAnswer[] = openQuestions.map((q) => ({
      question_id: q.id,
      answer:
        q.question_type === 'conflict' && q.conflict_detail
          ? answerFromChoice(q, choices[q.id] ?? '', clarifyAnswers[q.id] ?? '')
          : (clarifyAnswers[q.id] ?? ''),
    }));

    const unanswered = answers.filter((a) => !a.answer.trim());
    if (unanswered.length > 0) {
      message.warning('请回答所有问题');
      return;
    }

    setClarifySubmitting(true);
    try {
      await submitClarification(batchId, answers);
      message.success('澄清已提交，流水线恢复运行');
      setGateModalOpen(false);
      setClarifyAnswers({});
      setChoices({});
    } catch {
      // 错误 toast 已由全局拦截器处理
    } finally {
      setClarifySubmitting(false);
    }
  }, [batchId, openQuestions, clarifyAnswers, choices, submitClarification]);

  // ─── 重试/重新入队 ───
  const handleRetry = useCallback(async () => {
    if (!batchId) return;
    setRetrySubmitting(true);
    try {
      await retryBatch(batchId);
      message.success('任务已重新入队，等待 Worker 处理');
    } catch {
      // 错误 toast 已由全局拦截器处理
    } finally {
      setRetrySubmitting(false);
    }
  }, [batchId, retryBatch]);

  // ─── 触发迭代 ───
  const handleIterate = useCallback(async () => {
    if (!batchId) return;
    const modifiedIds = allCasesForIterate
      .filter((c) => c.review_status === 'needs_modification')
      .map((c) => c.id);

    if (modifiedIds.length === 0) {
      message.warning('没有标记为「需修改」的用例');
      return;
    }

    try {
      await triggerIterate(batchId, modifiedIds);
      message.success(`已触发迭代，${modifiedIds.length} 条用例将重新生成`);
      setTreeReloadSignal((n) => n + 1);
    } catch {
      // 错误 toast 已由全局拦截器处理
    }
  }, [batchId, allCasesForIterate, triggerIterate]);

  // ─── 落库 ───
  const handleArchive = useCallback(() => {
    if (!batchId) return;
    Modal.confirm({
      title: '确认落库',
      content: '落库后批次状态变为 archived，不可逆转。是否继续？',
      okText: '确认落库',
      cancelText: '取消',
      onOk: async () => {
        try {
          await archiveBatch(batchId);
          message.success('已落库');
        } catch {
          // 错误 toast 已由全局拦截器处理
        }
      },
    });
  }, [batchId, archiveBatch]);

  // ─── Steps 渲染 ───
  const stepsItems = useMemo(() => {
    const stageMap = new Map(stages.map((s) => [s.name, s]));

    return STAGE_ORDER.map((name) => {
      const stage = stageMap.get(name);
      const label = STAGE_LABELS[name] || name;

      let icon: React.ReactNode | undefined;
      let status: 'wait' | 'process' | 'finish' | 'error' | undefined;

      if (stage) {
        switch (stage.status) {
          case 'running':
            icon = <LoadingOutlined />;
            status = 'process';
            break;
          case 'completed':
            icon = <CheckOutlined />;
            status = 'finish';
            break;
          case 'failed':
            icon = <CloseOutlined />;
            status = 'error';
            break;
          case 'suspended':
            icon = <ExclamationCircleOutlined style={{ color: '#f5222d' }} />;
            status = 'error';
            break;
          default:
            status = 'wait';
        }
      } else {
        status = 'wait';
      }

      return { title: label, icon, status };
    });
  }, [stages]);

  const stageSummary = useMemo(() => {
    const completed = stages.filter((stage) => stage.status === 'completed').length;
    const failed = stages.some((stage) => stage.status === 'failed');
    const suspended = stages.some((stage) => stage.status === 'suspended');
    const activeStage =
      stages.find((stage) => ['running', 'suspended', 'failed'].includes(stage.status)) ||
      stages.find((stage) => stage.name === batch?.current_stage);
    const activeProgress = activeStage?.progress ? activeStage.progress / 100 : 0;
    const percent = Math.min(
      100,
      Math.round(((completed + activeProgress) / STAGE_ORDER.length) * 100),
    );

    return {
      completed,
      percent,
      activeStageLabel: getStageLabel(activeStage?.name || batch?.current_stage),
      progressStatus: failed ? 'exception' as const : suspended ? 'exception' as const : 'active' as const,
    };
  }, [batch?.current_stage, stages]);
  const failedStageDetail = useMemo(
    () => (batch?.status === 'failed' ? getFailedStageDetail(stages, batch.current_stage) : null),
    [batch?.current_stage, batch?.status, stages],
  );

  const caseReviewStats = useMemo(() => {
    const stats: Record<ReviewStatus, number> = {
      pending: 0,
      confirmed: 0,
      needs_modification: 0,
      deleted: 0,
    };

    for (const item of allCasesForIterate) {
      stats[item.review_status] += 1;
    }

    return stats;
  }, [allCasesForIterate]);

  const totalCasesForDisplay = allCasesForIterate.length || batch?.total_cases || 0;
  const openQuestionCount = openQuestions?.length ?? 0;
  const highPriorityQuestionCount = openQuestions?.filter((item) => item.priority === 'high').length ?? 0;
  const cameFromReview = searchParams.get('from') === 'review';
  const cameFromSearch = searchParams.get('from') === 'search';
  const cameFromKnowledge = searchParams.get('from') === 'knowledge';
  const cameFromDocument = searchParams.get('from') === 'document';
  const searchHighlightedCaseId = cameFromSearch ? searchParams.get('case_id') || undefined : undefined;
  const reviewReturnStatus = cameFromReview
    ? normalizeReviewReturnStatus(searchParams.get('status'))
    : undefined;
  const reviewReturnUrl = reviewReturnStatus
    ? `/review?status=${reviewReturnStatus}`
    : '/review';
  const reviewReturnLabel = reviewReturnStatus
    ? `返回工作台（${REVIEW_RETURN_STATUS_LABELS[reviewReturnStatus]}）`
    : '返回工作台';
  const knowledgeReturnUrl = cameFromKnowledge ? buildKnowledgeReturnUrl(searchParams.get('system_id')) : null;
  const documentReturnUrl = cameFromDocument ? buildDocumentReturnUrl(searchParams) : null;
  const contextualReturn = cameFromReview
    ? { url: reviewReturnUrl, label: reviewReturnLabel }
    : cameFromSearch
      ? { url: buildSearchReturnUrl(searchParams), label: '返回搜索结果' }
      : knowledgeReturnUrl
        ? { url: knowledgeReturnUrl, label: '返回知识库' }
        : documentReturnUrl
          ? { url: documentReturnUrl, label: '返回文档详情' }
          : null;

  const metricItems = useMemo(() => {
    if (!batch) return [];

    return [
      {
        key: 'status',
        label: '批次状态',
        value: STATUS_BADGE_MAP[batch.status].text,
        hint: `当前阶段：${stageSummary.activeStageLabel}`,
        tone: batch.status === 'failed' ? 'danger' as const : batch.status === 'suspended' ? 'warning' as const : 'primary' as const,
      },
      {
        key: 'stage',
        label: '阶段进度',
        value: `${stageSummary.completed}/${STAGE_ORDER.length}`,
        hint: `${stageSummary.percent}%`,
      },
      {
        key: 'total',
        label: '用例总数',
        value: totalCasesForDisplay || '—',
        hint: allCasesForIterate.length ? '来自当前用例树' : '等待用例树加载',
      },
      {
        key: 'pending',
        label: REVIEW_STATUS_LABELS.pending,
        value: caseReviewStats.pending,
        hint: '需要人工判断',
        tone: caseReviewStats.pending > 0 ? 'warning' as const : 'default' as const,
      },
      {
        key: 'needs_modification',
        label: REVIEW_STATUS_LABELS.needs_modification,
        value: caseReviewStats.needs_modification,
        hint: '可触发迭代',
        tone: caseReviewStats.needs_modification > 0 ? 'warning' as const : 'default' as const,
      },
      {
        key: 'questions',
        label: '待澄清',
        value: openQuestionCount,
        hint: highPriorityQuestionCount > 0 ? `${highPriorityQuestionCount} 个高优先级` : '质量门问题',
        tone: openQuestionCount > 0 ? 'danger' as const : 'success' as const,
      },
    ];
  }, [
    allCasesForIterate.length,
    batch,
    caseReviewStats.needs_modification,
    caseReviewStats.pending,
    highPriorityQuestionCount,
    openQuestionCount,
    stageSummary.activeStageLabel,
    stageSummary.completed,
    stageSummary.percent,
    totalCasesForDisplay,
  ]);

  // ─── 是否展示底部操作栏 ───
  const showBottomActions = batch?.status === 'pending_review' || batch?.status === 'reviewing';

  // ─── 渲染 ───
  if (batchLoading && !batch) {
    return (
      <PageShell style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
        <div style={{ marginTop: 12, color: layoutTokens.textSecondary }}>加载中...</div>
      </PageShell>
    );
  }

  if (!batch) {
    return (
      <PageShell>
        <EmptyState
          title="批次不存在"
          description="请从工作台或系统批次列表重新进入。"
        />
      </PageShell>
    );
  }

  const badgeCfg = STATUS_BADGE_MAP[batch.status];
  const statusGuidance = GUIDANCE_BY_STATUS[batch.status];
  const canIterate = caseReviewStats.needs_modification > 0;
  const renderPrimaryActions = () => (
    <>
      {batch.status === 'suspended' && openQuestionCount > 0 && (
        <Button type="primary" onClick={() => setGateModalOpen(true)}>
          处理澄清
        </Button>
      )}
      {(batch.status === 'pending' || batch.status === 'failed') && (
        <Button danger={batch.status === 'failed'} loading={retrySubmitting} onClick={handleRetry}>
          重新入队
        </Button>
      )}
      {showBottomActions && (
        <>
          <Button type={canIterate ? 'primary' : 'default'} disabled={!canIterate} onClick={handleIterate}>
            触发迭代
          </Button>
          <Button type={canIterate ? 'default' : 'primary'} onClick={handleArchive}>
            落库归档
          </Button>
        </>
      )}
    </>
  );
  const renderHeaderActions = () => (
    <>
      {contextualReturn && (
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(contextualReturn.url)}>
          {contextualReturn.label}
        </Button>
      )}
      {renderPrimaryActions()}
    </>
  );

  return (
    <PageShell>
      <PageHeader
        eyebrow="生成与审查"
        title={batch.document_title || '用例工作台'}
        description="集中查看批次状态、质量门澄清和候选用例审查；先处理阻塞，再按模块逐块确认、修改或落库。"
        meta={<Badge status={badgeCfg.status} text={badgeCfg.text} />}
        actions={renderHeaderActions()}
      />

      <MetricStrip items={metricItems} />

      <Alert
        type={statusGuidance.type}
        showIcon
        style={{ marginBottom: 16 }}
        message={statusGuidance.message}
        description={statusGuidance.description}
        action={<Space wrap>{renderPrimaryActions()}</Space>}
      />

      {/* ─── 阶段进度条 ─── */}
      <div
        style={{
          marginBottom: 20,
          padding: 16,
          border: `1px solid ${layoutTokens.border}`,
          borderRadius: layoutTokens.radius,
          background: layoutTokens.surface,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 16,
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <div>
            <Text strong>生成阶段</Text>
            <Text style={{ display: 'block', marginTop: 4, color: layoutTokens.textSecondary }}>
              当前：{stageSummary.activeStageLabel}
            </Text>
          </div>
          <Text style={{ color: layoutTokens.textMuted }}>
            {stageSummary.completed}/{STAGE_ORDER.length} 已完成
          </Text>
        </div>
        <Progress
          percent={stageSummary.percent}
          size="small"
          status={stageSummary.progressStatus}
          style={{ marginBottom: 16 }}
        />
        <Steps size="small" items={stepsItems} />
        {failedStageDetail && (
          <Alert
            type="error"
            showIcon
            style={{ marginTop: 16 }}
            message={`失败阶段：${getStageLabel(failedStageDetail.stageName)}`}
            description={
              <Space direction="vertical" size={4}>
                <Text>
                  {failedStageDetail.errorMessage ||
                    '后端没有返回详细错误；重试前建议检查 Worker、Redis 和模型网关日志。'}
                </Text>
                <Text type="secondary">
                  重新入队会优先尝试从失败阶段恢复；如果缺少检查点，系统会降级为整批重跑。
                </Text>
              </Space>
            }
          />
        )}
      </div>

      {/* ─── 筛选栏 ─── */}
      <div style={{ marginBottom: 8 }}>
        <Text strong>用例审查</Text>
        <Text style={{ marginLeft: 8, color: layoutTokens.textSecondary }}>
          通过筛选收敛待处理范围，左侧按文档/模块/分支定位，右侧逐条确认。
        </Text>
      </div>
      <FilterBar>
        <Input.Search
          allowClear
          enterButton
          placeholder="按用例标题搜索（模糊匹配，回车/点按钮搜索）"
          style={{ width: 340 }}
          onSearch={handleSearch}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Review 状态筛选"
          style={{ width: 180 }}
          value={reviewFilter}
          onChange={handleFilterChange}
          options={[
            { value: 'pending', label: '待审' },
            { value: 'confirmed', label: '已确认' },
            { value: 'needs_modification', label: '需修改' },
            { value: 'deleted', label: '已删除' },
          ]}
        />
        <Select
          allowClear
          placeholder="质量桶"
          style={{ width: 140 }}
          value={bucketFilter}
          onChange={setBucketFilter}
          options={[
            { value: 'main', label: '主集' },
            { value: 'needs_spec', label: '待澄清' },
            { value: 'to_fix', label: '待修正' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="核验结论"
          style={{ width: 160 }}
          value={verdictFilter}
          onChange={setVerdictFilter}
          options={[
            { value: 'grounded', label: 'grounded' },
            { value: 'ungrounded', label: 'ungrounded' },
            { value: 'undefined', label: 'undefined' },
            { value: 'conflict', label: 'conflict' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="审查诊断"
          style={{ width: 160 }}
          value={reviewIssueTypeFilter}
          onChange={setReviewIssueTypeFilter}
          options={[
            { value: 'case_wrong', label: '用例错' },
            { value: 'prd_conflict', label: 'PRD冲突' },
            { value: 'verify_uncertain', label: '核验不确定' },
          ]}
        />
      </FilterBar>

      {/* ─── 用例审核树（左模块树 + 右用例表） ─── */}
      <CaseTreeReview
        batchId={batchId!}
        systemId={batch.system_id}
        reviewFilter={reviewFilter}
        bucketFilter={bucketFilter}
        verdictFilter={verdictFilter}
        reviewIssueTypeFilter={reviewIssueTypeFilter}
        searchKeyword={searchKeyword}
        highlightedCaseId={searchHighlightedCaseId}
        editable={showBottomActions}
        onReview={async (caseId, status, comment) => {
          await reviewCase(caseId, status, comment);
        }}
        onAllCasesChange={setAllCasesForIterate}
        reloadSignal={treeReloadSignal}
      />

      {/* ─── 底部操作栏 ─── */}
      {showBottomActions && (
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            zIndex: 5,
            marginTop: 16,
            padding: '12px 16px',
            border: `1px solid ${layoutTokens.border}`,
            borderRadius: layoutTokens.radius,
            background: layoutTokens.surface,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
            boxShadow: '0 -8px 24px rgba(15, 23, 42, 0.06)',
          }}
        >
          <Text style={{ color: layoutTokens.textSecondary }}>
            {canIterate
              ? `已标记 ${caseReviewStats.needs_modification} 条需修改，可触发迭代重写。`
              : '没有需修改用例时，可将当前批次落库归档。'}
          </Text>
          <Space wrap>{renderPrimaryActions()}</Space>
        </div>
      )}

      {/* ─── Gate 澄清 Modal ─── */}
      <Modal
        title="质量门澄清"
        open={gateModalOpen}
        onCancel={() => { setGateModalOpen(false); setChoices({}); }}
        onOk={handleClarifySubmit}
        confirmLoading={clarifySubmitting}
        okText="提交澄清"
        cancelText="取消"
        width={720}
        maskClosable={false}
      >
        {openQuestions?.map((q: OpenQuestion) => (
          <div key={q.id} style={{ marginBottom: 24 }}>
            <div style={{ marginBottom: 4 }}>
              <Tag color={q.priority === 'high' ? 'red' : q.priority === 'medium' ? 'orange' : 'blue'}>
                {q.priority === 'high' ? '高' : q.priority === 'medium' ? '中' : '低'}
              </Tag>
              <strong>{q.question}</strong>
            </div>
            {q.context && (
              <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>{q.context}</div>
            )}

            {/* 冲突类 + 有结构化 detail → 卡片 + 选项 */}
            {q.question_type === 'conflict' && q.conflict_detail ? (
              <>
                <div style={{ fontWeight: 500, marginBottom: 8 }}>{q.conflict_detail.topic}</div>
                <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                  <Card size="small" style={{ flex: 1 }} title={q.conflict_detail.side_a.location || '方 A'}>
                    <div>{q.conflict_detail.side_a.statement}</div>
                    <div style={{ fontSize: 12, color: '#888' }}>信任等级: {q.conflict_detail.side_a.trust_level}</div>
                  </Card>
                  <Card size="small" style={{ flex: 1 }} title={q.conflict_detail.side_b.location || '方 B'}>
                    <div>{q.conflict_detail.side_b.statement}</div>
                    <div style={{ fontSize: 12, color: '#888' }}>信任等级: {q.conflict_detail.side_b.trust_level}</div>
                  </Card>
                </div>
                <div style={{ fontSize: 12, color: '#1677ff', marginBottom: 8 }}>
                  {q.conflict_detail.recommendation === 'neither'
                    ? `💡 AI 倾向：两者均需修正，建议自定`
                    : `💡 AI 推荐：以 ${q.conflict_detail.recommendation === 'side_a' ? q.conflict_detail.side_a.location : q.conflict_detail.side_b.location} 为准 — ${q.conflict_detail.recommendation_reason}`}
                </div>
                <Radio.Group
                  value={choices[q.id] || undefined}
                  onChange={(e) => setChoices((prev) => ({ ...prev, [q.id]: e.target.value }))}
                >
                  <Radio value="side_a">以 {q.conflict_detail.side_a.location || '方 A'} 为准</Radio>
                  <Radio value="side_b">以 {q.conflict_detail.side_b.location || '方 B'} 为准</Radio>
                  <Radio value="custom">都不对，我来定</Radio>
                </Radio.Group>
                {choices[q.id] === 'custom' && (
                  <TextArea
                    rows={2}
                    style={{ marginTop: 8 }}
                    placeholder="请给出明确结论"
                    value={clarifyAnswers[q.id] || ''}
                    onChange={(e) =>
                      setClarifyAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                    }
                  />
                )}
              </>
            ) : (
              /* 盲区类 / 冲突但无 detail（降级）→ 纯文字 + 输入框 */
              <TextArea
                rows={2}
                placeholder={q.question_type === 'conflict'
                  ? '请给出明确结论，例：以 ≤50 字为准'
                  : '请输入回答'}
                value={clarifyAnswers[q.id] || ''}
                onChange={(e) =>
                  setClarifyAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                }
              />
            )}
          </div>
        ))}
      </Modal>

    </PageShell>
  );
};

export default Workbench;
