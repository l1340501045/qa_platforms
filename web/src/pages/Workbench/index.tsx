/**
 * 用例工作台 — /batches/:batchId
 * 核心页面：阶段进度 + 用例 Review + Gate 澄清 + 迭代/落库
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Radio,
  Select,
  Spin,
  Steps,
  Tag,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';

import { useTestcaseStore } from '../../stores/testcaseStore';
import CaseTreeReview from '../../components/CaseTreeReview';
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

const Workbench: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>();

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

  // ─── 是否展示底部操作栏 ───
  const showBottomActions = batch?.status === 'pending_review' || batch?.status === 'reviewing';

  // ─── 渲染 ───
  if (batchLoading && !batch) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (!batch) {
    return <div style={{ textAlign: 'center', padding: 80 }}>批次不存在</div>;
  }

  const badgeCfg = STATUS_BADGE_MAP[batch.status];

  return (
    <div style={{ padding: 24 }}>
      {/* ─── 顶部：批次信息 ─── */}
      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', gap: 16 }}>
        <h2 style={{ margin: 0 }}>{batch.document_title || '用例工作台'}</h2>
        <Badge status={badgeCfg.status} text={badgeCfg.text} />
      </div>

      {/* ─── 等待 Worker / 失败提示 ─── */}
      {batch.status === 'pending' && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="任务已创建，等待 Worker 处理"
          description="如长时间无进展，请确认 Redis 与 Celery Worker 已启动，或点击下方按钮重新入队。"
          action={
            <Button size="small" loading={retrySubmitting} onClick={handleRetry}>
              重新触发
            </Button>
          }
        />
      )}
      {batch.status === 'failed' && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="生成任务失败"
          description="可从失败阶段重试，或重新入队整批重跑。"
          action={
            <Button size="small" danger loading={retrySubmitting} onClick={handleRetry}>
              重试
            </Button>
          }
        />
      )}

      {/* ─── 阶段进度条 ─── */}
      <Steps
        size="small"
        items={stepsItems}
        style={{ marginBottom: 24 }}
      />

      {/* ─── 筛选栏 ─── */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
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
      </div>

      {/* ─── 用例审核树（左模块树 + 右用例表） ─── */}
      <CaseTreeReview
        batchId={batchId!}
        systemId={batch.system_id}
        reviewFilter={reviewFilter}
        bucketFilter={bucketFilter}
        verdictFilter={verdictFilter}
        reviewIssueTypeFilter={reviewIssueTypeFilter}
        searchKeyword={searchKeyword}
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
            marginTop: 16,
            padding: '12px 0',
            borderTop: '1px solid #f0f0f0',
            display: 'flex',
            gap: 12,
          }}
        >
          <Button type="primary" onClick={handleIterate}>
            触发迭代
          </Button>
          <Button danger onClick={handleArchive}>
            落库
          </Button>
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

    </div>
  );
};

export default Workbench;
