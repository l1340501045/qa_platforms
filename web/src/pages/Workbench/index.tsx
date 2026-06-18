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
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import { useTestcaseStore } from '../../stores/testcaseStore';
import CaseDetailDrawer from '../../components/CaseDetailDrawer';
import type {
  BatchStatus,
  ClarifyAnswer,
  OpenQuestion,
  ReviewStatus,
  TestCase,
} from '../../types';

const { TextArea } = Input;

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

// ─── 优先级颜色 ───
const PRIORITY_COLOR: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
};

// ─── 可信度（契约 §6：1=最可信/绿，5=最不可信/红） ───
function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

// ─── Review 状态 Tag ───
const REVIEW_TAG: Record<ReviewStatus, { color: string; label: string }> = {
  pending: { color: 'default', label: '待审' },
  confirmed: { color: 'green', label: '已确认' },
  needs_modification: { color: 'orange', label: '需修改' },
  deleted: { color: 'red', label: '已删除' },
};

const Workbench: React.FC = () => {
  const { batchId } = useParams<{ batchId: string }>();

  // Store
  const {
    batch,
    stages,
    openQuestions,
    batchLoading,
    cases,
    casesTotal,
    casesPage,
    casesPerPage,
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
  const [clarifySubmitting, setClarifySubmitting] = useState(false);
  const [modifyModalOpen, setModifyModalOpen] = useState(false);
  const [modifyCaseId, setModifyCaseId] = useState<string | null>(null);
  const [modifyComment, setModifyComment] = useState('');
  const [modifySubmitting, setModifySubmitting] = useState(false);
  const [detailCaseId, setDetailCaseId] = useState<string | null>(null);
  const [retrySubmitting, setRetrySubmitting] = useState(false);

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

  // ─── 分页/筛选变化 ───
  const handlePageChange = useCallback(
    (page: number, pageSize: number) => {
      if (!batchId) return;
      fetchBatchDetail(batchId, {
        page,
        per_page: pageSize,
        review_status: reviewFilter,
      }).catch(() => message.error('加载用例列表失败'));
    },
    [batchId, fetchBatchDetail, reviewFilter],
  );

  const handleFilterChange = useCallback(
    (value: ReviewStatus | undefined) => {
      setReviewFilter(value);
      if (!batchId) return;
      fetchBatchDetail(batchId, {
        page: 1,
        per_page: casesPerPage,
        review_status: value,
      }).catch(() => message.error('加载用例列表失败'));
    },
    [batchId, casesPerPage, fetchBatchDetail],
  );

  // ─── 澄清提交 ───
  const handleClarifySubmit = useCallback(async () => {
    if (!batchId || !openQuestions) return;

    const answers: ClarifyAnswer[] = openQuestions.map((q) => ({
      question_id: q.id,
      answer: clarifyAnswers[q.id] || '',
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
    } catch {
      // 错误 toast 已由全局拦截器处理
    } finally {
      setClarifySubmitting(false);
    }
  }, [batchId, openQuestions, clarifyAnswers, submitClarification]);

  // ─── Review 操作 ───
  const handleConfirm = useCallback(
    async (caseId: string) => {
      try {
        await reviewCase(caseId, 'confirmed');
        message.success('已确认');
      } catch {
        // 错误 toast 已由全局拦截器处理
      }
    },
    [reviewCase],
  );

  const handleDelete = useCallback(
    async (caseId: string) => {
      try {
        await reviewCase(caseId, 'deleted');
        message.success('已删除');
      } catch {
        // 错误 toast 已由全局拦截器处理
      }
    },
    [reviewCase],
  );

  const handleNeedsModification = useCallback((caseId: string) => {
    setModifyCaseId(caseId);
    setModifyComment('');
    setModifyModalOpen(true);
  }, []);

  const handleModifySubmit = useCallback(async () => {
    if (!modifyCaseId) return;
    if (!modifyComment.trim()) {
      message.warning('请输入修改意见');
      return;
    }
    setModifySubmitting(true);
    try {
      await reviewCase(modifyCaseId, 'needs_modification', modifyComment.trim());
      message.success('已标记需修改');
      setModifyModalOpen(false);
    } catch {
      // 错误 toast 已由全局拦截器处理
    } finally {
      setModifySubmitting(false);
    }
  }, [modifyCaseId, modifyComment, reviewCase]);

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
    const modifiedIds = cases
      .filter((c) => c.review_status === 'needs_modification')
      .map((c) => c.id);

    if (modifiedIds.length === 0) {
      message.warning('没有标记为「需修改」的用例');
      return;
    }

    try {
      await triggerIterate(batchId, modifiedIds);
      message.success(`已触发迭代，${modifiedIds.length} 条用例将重新生成`);
    } catch {
      // 错误 toast 已由全局拦截器处理
    }
  }, [batchId, cases, triggerIterate]);

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

  // ─── Table Columns ───
  const columns: ColumnsType<TestCase> = useMemo(
    () => [
      {
        title: '标题',
        dataIndex: 'title',
        key: 'title',
        ellipsis: true,
        width: '30%',
        render: (text: string, record: TestCase) => (
          <a onClick={() => setDetailCaseId(record.id)}>{text}</a>
        ),
      },
      {
        title: '优先级',
        dataIndex: 'priority',
        key: 'priority',
        width: 80,
        render: (val: string) => <Tag color={PRIORITY_COLOR[val] || 'default'}>{val}</Tag>,
      },
      {
        title: '可信度',
        dataIndex: 'trust_level',
        key: 'trust_level',
        width: 80,
        render: (val: number) => {
          const { color, label } = getTrustDisplay(val);
          return <span style={{ color, fontWeight: 600 }}>{label}</span>;
        },
      },
      {
        title: 'Review 状态',
        dataIndex: 'review_status',
        key: 'review_status',
        width: 100,
        render: (val: ReviewStatus) => {
          const cfg = REVIEW_TAG[val];
          return <Tag color={cfg.color}>{cfg.label}</Tag>;
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 220,
        render: (_: unknown, record: TestCase) => (
          <Space size="small">
            <Button
              size="small"
              type="link"
              disabled={record.review_status === 'confirmed'}
              onClick={() => handleConfirm(record.id)}
            >
              确认
            </Button>
            <Button
              size="small"
              type="link"
              disabled={record.review_status === 'needs_modification'}
              onClick={() => handleNeedsModification(record.id)}
            >
              需修改
            </Button>
            <Button
              size="small"
              type="link"
              danger
              disabled={record.review_status === 'deleted'}
              onClick={() => handleDelete(record.id)}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ],
    [handleConfirm, handleDelete, handleNeedsModification],
  );

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
      <div style={{ marginBottom: 16 }}>
        <Select
          allowClear
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
      </div>

      {/* ─── 用例列表 ─── */}
      <Table<TestCase>
        rowKey="id"
        columns={columns}
        dataSource={cases}
        pagination={{
          current: casesPage,
          pageSize: casesPerPage,
          total: casesTotal,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: handlePageChange,
        }}
        loading={batchLoading}
        size="middle"
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
        onCancel={() => setGateModalOpen(false)}
        onOk={handleClarifySubmit}
        confirmLoading={clarifySubmitting}
        okText="提交澄清"
        cancelText="取消"
        width={640}
        maskClosable={false}
      >
        {openQuestions?.map((q: OpenQuestion) => (
          <div key={q.id} style={{ marginBottom: 20 }}>
            <div style={{ marginBottom: 4 }}>
              <Tag color={q.priority === 'high' ? 'red' : q.priority === 'medium' ? 'orange' : 'blue'}>
                {q.priority}
              </Tag>
              <strong>{q.question}</strong>
            </div>
            {q.context && (
              <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>{q.context}</div>
            )}
            <TextArea
              rows={2}
              placeholder="请输入回答"
              value={clarifyAnswers[q.id] || ''}
              onChange={(e) =>
                setClarifyAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
              }
            />
          </div>
        ))}
      </Modal>

      {/* ─── 需修改意见 Modal ─── */}
      <Modal
        title="修改意见"
        open={modifyModalOpen}
        onCancel={() => setModifyModalOpen(false)}
        onOk={handleModifySubmit}
        confirmLoading={modifySubmitting}
        okText="提交"
        cancelText="取消"
      >
        <TextArea
          rows={4}
          placeholder="请输入修改意见（必填）"
          value={modifyComment}
          onChange={(e) => setModifyComment(e.target.value)}
        />
      </Modal>

      {/* ─── 用例详情 Drawer ─── */}
      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
      />
    </div>
  );
};

export default Workbench;
