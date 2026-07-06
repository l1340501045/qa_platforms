import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Card, Select, Spin, Table, Typography } from 'antd';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
import { getErrorMessage } from '../../utils/errorMessage';

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

const VALID_STATUS_VALUES = new Set(STATUS_OPTIONS.map((item) => item.value));
const LANE_COLLAPSED_LIMIT = 3;
const LANE_FETCH_LIMIT = 8;

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
    status: 'pending_review',
    title: '待审核',
    description: '用例已生成，等待 QA 审查确认。',
    emptyText: '暂无待审核批次',
    tone: 'warning',
  },
  {
    status: 'running',
    title: '生成中',
    description: '流水线正在执行，可进入查看阶段进度。',
    emptyText: '暂无运行中批次',
    tone: 'processing',
  },
];

function createEmptyBatchPage(): PaginatedData<ReviewBatch> {
  return {
    items: [],
    total: 0,
    page: 1,
    per_page: LANE_FETCH_LIMIT,
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

function normalizeStatusParam(value: string | null): string {
  return value && VALID_STATUS_VALUES.has(value) ? value : '';
}

function getStatusLabel(status: string): string {
  return STATUS_OPTIONS.find((item) => item.value === status)?.label || '全部';
}

function formatBatchCreatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN');
}

const ReviewCenter: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [laneLoading, setLaneLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [laneError, setLaneError] = useState<string | null>(null);
  const [status, setStatus] = useState<string>(() => normalizeStatusParam(searchParams.get('status')));
  const [laneData, setLaneData] = useState<Record<WorkbenchLaneStatus, PaginatedData<ReviewBatch>>>(
    () => createInitialLaneData(),
  );
  const [expandedLanes, setExpandedLanes] = useState<Partial<Record<WorkbenchLaneStatus, boolean>>>({});
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
            per_page: LANE_FETCH_LIMIT,
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
    const nextStatus = normalizeStatusParam(searchParams.get('status'));
    setStatus((current) => (current === nextStatus ? current : nextStatus));
  }, [searchParams]);

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

  const applyStatusFilter = useCallback(
    (nextStatus: string) => {
      const normalized = normalizeStatusParam(nextStatus);
      setStatus(normalized);
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        if (normalized) {
          next.set('status', normalized);
        } else {
          next.delete('status');
        }
        return next;
      }, { replace: true });
    },
    [setSearchParams],
  );

  const toggleLaneExpanded = useCallback((laneStatus: WorkbenchLaneStatus) => {
    setExpandedLanes((current) => ({
      ...current,
      [laneStatus]: !current[laneStatus],
    }));
  }, []);

  const buildBatchUrl = useCallback(
    (batchId: string, sourceStatus = status) => {
      const params = new URLSearchParams({ from: 'review' });
      const normalized = normalizeStatusParam(sourceStatus);
      if (normalized) params.set('status', normalized);
      return `/batches/${batchId}?${params.toString()}`;
    },
    [status],
  );

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
      render: formatBatchCreatedAt,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => navigate(buildBatchUrl(record.id))}>
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

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="推荐处理顺序：待澄清 -> 失败 -> 待审核 -> 生成中"
        description="每个队列按创建时间倒序展示最近批次；默认露出 3 条，展开可看最近 8 条，完整列表用下方状态筛选分页查看。"
      />

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
            const expanded = Boolean(expandedLanes[lane.status]);
            const visibleLimit = expanded ? LANE_FETCH_LIMIT : LANE_COLLAPSED_LIMIT;
            const visibleItems = lanePage.items.slice(0, visibleLimit);
            const canExpand = lanePage.items.length > LANE_COLLAPSED_LIMIT;
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
                    onClick={() => applyStatusFilter(lane.status)}
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
                    {visibleItems.map((batch) => (
                      <button
                        key={batch.id}
                        type="button"
                        onClick={() => navigate(buildBatchUrl(batch.id, lane.status))}
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
                        <div style={{ marginTop: 4, color: layoutTokens.textMuted, fontSize: 12 }}>
                          创建：{formatBatchCreatedAt(batch.created_at)}
                        </div>
                      </button>
                    ))}
                    {(canExpand || lanePage.total > visibleItems.length) && (
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          gap: 8,
                          paddingTop: 4,
                        }}
                      >
                        {canExpand ? (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => toggleLaneExpanded(lane.status)}
                            style={{ paddingInline: 0 }}
                          >
                            {expanded ? '收起' : `展开最近 ${Math.min(lanePage.items.length, LANE_FETCH_LIMIT)} 条`}
                          </Button>
                        ) : (
                          <span />
                        )}
                        {lanePage.total > visibleItems.length && (
                          <Button
                            type="link"
                            size="small"
                            onClick={() => applyStatusFilter(lane.status)}
                            style={{ paddingInline: 0 }}
                          >
                            查看全部 {lanePage.total} 条
                          </Button>
                        )}
                      </div>
                    )}
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
          onChange={(val) => applyStatusFilter(val || '')}
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
            description={`当前状态：${getStatusLabel(status)}。可切换状态查看审核中、已完成或已落库的批次。`}
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
