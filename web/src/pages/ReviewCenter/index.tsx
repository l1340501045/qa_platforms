import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Select, Spin, Table, Typography } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';

import { listBatches } from '../../services/batchApi';
import type { BatchStatus, PaginatedData, ReviewBatch } from '../../types';
import EmptyState from '../../components/common/EmptyState';
import StatusTag from '../../components/common/StatusTag';
import type { StatusTone } from '../../components/common/StatusTag';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';

const { Text } = Typography;

type WorkbenchLaneStatus = Extract<BatchStatus, 'suspended' | 'failed' | 'running' | 'pending_review'>;

const STATUS_OPTIONS = [
  { value: 'pending', label: '排队中' },
  { value: 'running', label: '生成中' },
  { value: 'suspended', label: '待澄清' },
  { value: 'failed', label: '失败' },
  { value: 'pending_review', label: '待审核' },
  { value: 'reviewing', label: '审核中' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已落库' },
];

const STATUS_TAG: Record<string, { tone: StatusTone; text: string }> = {
  pending_review: { tone: 'warning', text: '待审核' },
  reviewing: { tone: 'processing', text: '审核中' },
  completed: { tone: 'success', text: '已完成' },
  archived: { tone: 'default', text: '已落库' },
  running: { tone: 'processing', text: '生成中' },
  failed: { tone: 'danger', text: '失败' },
  pending: { tone: 'default', text: '排队中' },
  suspended: { tone: 'warning', text: '待澄清' },
};

const WORKBENCH_LANES: Array<{
  status: WorkbenchLaneStatus;
  title: string;
  description: string;
  emptyText: string;
  tone: StatusTone;
}> = [
  {
    status: 'suspended',
    title: '待澄清',
    description: '质量门需要人工明确规则或冲突结论。',
    emptyText: '暂无待澄清批次',
    tone: 'warning',
  },
  {
    status: 'failed',
    title: '失败',
    description: '生成链路失败，需要查看原因后重试。',
    emptyText: '暂无失败批次',
    tone: 'danger',
  },
  {
    status: 'running',
    title: '生成中',
    description: '流水线正在执行，可进入查看阶段进度。',
    emptyText: '暂无运行中批次',
    tone: 'processing',
  },
  {
    status: 'pending_review',
    title: '待审核',
    description: '用例已生成，等待 QA 审查确认。',
    emptyText: '暂无待审核批次',
    tone: 'info',
  },
];

function createEmptyBatchPage(): PaginatedData<ReviewBatch> {
  return {
    items: [],
    total: 0,
    page: 1,
    per_page: 3,
    total_pages: 0,
  };
}

function createInitialLaneData(): Record<WorkbenchLaneStatus, PaginatedData<ReviewBatch>> {
  return {
    suspended: createEmptyBatchPage(),
    failed: createEmptyBatchPage(),
    running: createEmptyBatchPage(),
    pending_review: createEmptyBatchPage(),
  };
}

function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) {
      return message;
    }
  }
  return fallback;
}

function getBatchActionLabel(status: BatchStatus): string {
  switch (status) {
    case 'suspended':
      return '处理澄清';
    case 'failed':
      return '查看失败';
    case 'pending':
    case 'running':
      return '查看进度';
    case 'pending_review':
    case 'reviewing':
      return '去审核';
    case 'completed':
      return '查看结果';
    case 'archived':
      return '查看资产';
    default:
      return '打开批次';
  }
}

const ReviewCenter: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [laneLoading, setLaneLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [laneError, setLaneError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('');
  const [laneData, setLaneData] = useState<Record<WorkbenchLaneStatus, PaginatedData<ReviewBatch>>>(
    () => createInitialLaneData(),
  );
  const [data, setData] = useState<PaginatedData<ReviewBatch>>({
    items: [],
    total: 0,
    page: 1,
    per_page: 20,
    total_pages: 0,
  });

  const fetchList = useCallback(async (page = 1, perPage = 20, filterStatus?: string) => {
    setLoading(true);
    setListError(null);
    try {
      const result = await listBatches({
        status: filterStatus,
        page,
        per_page: perPage,
      });
      setData(result);
    } catch (err) {
      setListError(getErrorMessage(err, '批次列表暂时无法加载，请重试。'));
      setData({
        items: [],
        total: 0,
        page,
        per_page: perPage,
        total_pages: 0,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchWorkbenchLanes = useCallback(async () => {
    setLaneLoading(true);
    setLaneError(null);
    try {
      const results = await Promise.all(
        WORKBENCH_LANES.map(async (lane) => ({
          status: lane.status,
          data: await listBatches({
            status: lane.status,
            page: 1,
            per_page: 3,
          }),
        })),
      );
      const next = createInitialLaneData();
      results.forEach((result) => {
        next[result.status] = result.data;
      });
      setLaneData(next);
    } catch (err) {
      setLaneError(getErrorMessage(err, '待办队列暂时无法加载，请重试。'));
      setLaneData(createInitialLaneData());
    } finally {
      setLaneLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList(1, 20, status || undefined);
  }, [fetchList, status]);

  useEffect(() => {
    fetchWorkbenchLanes();
  }, [fetchWorkbenchLanes]);

  const handlePageChange = useCallback(
    (page: number, pageSize: number) => {
      fetchList(page, pageSize, status || undefined);
    },
    [fetchList, status],
  );

  const retryList = useCallback(() => {
    fetchList(data.page || 1, data.per_page || 20, status || undefined);
  }, [data.page, data.per_page, fetchList, status]);

  const columns: ColumnsType<ReviewBatch> = [
    {
      title: '文档标题',
      dataIndex: 'document_title',
      key: 'document_title',
      ellipsis: true,
    },
    {
      title: '所属系统',
      dataIndex: 'system_name',
      key: 'system_name',
      width: 160,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (val: BatchStatus) => {
        const cfg = STATUS_TAG[val] || { tone: 'default', text: val };
        return <StatusTag tone={cfg.tone}>{cfg.text}</StatusTag>;
      },
    },
    {
      title: '用例数',
      dataIndex: 'total_cases',
      key: 'total_cases',
      width: 80,
      render: (val: number | null) => val ?? '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (val: string) => new Date(val).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => navigate(`/batches/${record.id}`)}>
          {getBatchActionLabel(record.status)}
        </Button>
      ),
    },
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow="工作台"
        title="待处理批次"
        description="优先处理待澄清、失败和待审核批次；从这里进入批次详情完成审查、迭代和落库。"
      />

      <MetricStrip
        items={[
          { key: 'total', label: '当前筛选批次', value: data.total, tone: 'primary' },
          {
            key: 'todo',
            label: '待澄清/失败/待审',
            value:
              laneData.suspended.total +
              laneData.failed.total +
              laneData.pending_review.total,
            tone: 'warning',
          },
          {
            key: 'running',
            label: '运行中批次',
            value: laneData.running.total,
            tone: 'primary',
          },
          {
            key: 'filter',
            label: '当前状态',
            value: STATUS_OPTIONS.find((item) => item.value === status)?.label || '全部',
          },
        ]}
      />

      {laneError && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="待办队列加载失败"
          description={laneError}
          action={
            <Button size="small" onClick={fetchWorkbenchLanes}>
              重试队列
            </Button>
          }
        />
      )}

      <Spin spinning={laneLoading}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: 12,
            marginBottom: 16,
          }}
        >
          {WORKBENCH_LANES.map((lane) => {
            const lanePage = laneData[lane.status];
            return (
              <Card
                key={lane.status}
                size="small"
                title={
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <StatusTag tone={lane.tone}>{lane.title}</StatusTag>
                    <span style={{ fontVariantNumeric: 'tabular-nums' }}>{lanePage.total}</span>
                  </span>
                }
                extra={
                  <Button
                    type="link"
                    size="small"
                    onClick={() => setStatus(lane.status)}
                    style={{ paddingInline: 0 }}
                  >
                    筛选
                  </Button>
                }
                styles={{ body: { minHeight: 168 } }}
              >
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  {lane.description}
                </Text>
                {lanePage.items.length === 0 ? (
                  <div
                    style={{
                      padding: '18px 0',
                      color: layoutTokens.textMuted,
                      fontSize: 13,
                    }}
                  >
                    {lane.emptyText}
                  </div>
                ) : (
                  <div style={{ display: 'grid', gap: 8 }}>
                    {lanePage.items.map((batch) => (
                      <button
                        key={batch.id}
                        type="button"
                        onClick={() => navigate(`/batches/${batch.id}`)}
                        style={{
                          width: '100%',
                          minHeight: 52,
                          padding: '8px 10px',
                          border: `1px solid ${layoutTokens.borderSubtle}`,
                          borderRadius: layoutTokens.radius,
                          background: layoutTokens.surfaceMuted,
                          cursor: 'pointer',
                          textAlign: 'left',
                        }}
                      >
                        <div
                          style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            color: layoutTokens.text,
                            fontWeight: 600,
                          }}
                          title={batch.document_title}
                        >
                          {batch.document_title}
                        </div>
                        <div
                          style={{
                            marginTop: 4,
                            color: layoutTokens.textSecondary,
                            fontSize: 12,
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: 8,
                          }}
                        >
                          <span
                            style={{
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={batch.system_name}
                          >
                            {batch.system_name}
                          </span>
                          <span style={{ flexShrink: 0 }}>
                            {batch.total_cases ?? 0} 例
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      </Spin>

      <FilterBar>
        <span style={{ fontWeight: 600 }}>批次状态</span>
        <Select
          showSearch
          optionFilterProp="label"
          allowClear
          placeholder="按状态筛选"
          style={{ width: 160 }}
          value={status || undefined}
          onChange={(val) => setStatus(val || '')}
          options={STATUS_OPTIONS}
        />
      </FilterBar>

      <Spin spinning={loading}>
        {listError && !loading ? (
          <EmptyState
            role="alert"
            title="批次列表加载失败"
            description={`无法确认当前是否有待处理批次。${listError}`}
            action={<Button onClick={retryList}>重试加载</Button>}
          />
        ) : data.items.length === 0 && !loading ? (
          <EmptyState
            title="当前筛选下没有批次"
            description="可切换状态查看审核中、已完成或已落库的批次。"
          />
        ) : (
          <Table<ReviewBatch>
            rowKey="id"
            columns={columns}
            dataSource={data.items}
            pagination={{
              current: data.page,
              pageSize: data.per_page,
              total: data.total,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
              onChange: handlePageChange,
            }}
            size="middle"
            scroll={{ x: 720 }}
          />
        )}
      </Spin>
    </PageShell>
  );
};

export default ReviewCenter;
