import React, { useCallback, useEffect, useState } from 'react';
import { Select, Spin, Table } from 'antd';
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

const ReviewCenter: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>('');
  const [data, setData] = useState<PaginatedData<ReviewBatch>>({
    items: [],
    total: 0,
    page: 1,
    per_page: 20,
    total_pages: 0,
  });

  const fetchList = useCallback(async (page = 1, perPage = 20, filterStatus?: string) => {
    setLoading(true);
    try {
      const result = await listBatches({
        status: filterStatus,
        page,
        per_page: perPage,
      });
      setData(result);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList(1, 20, status || undefined);
  }, [fetchList, status]);

  const handlePageChange = useCallback(
    (page: number, pageSize: number) => {
      fetchList(page, pageSize, status || undefined);
    },
    [fetchList, status],
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
      render: (val: string) => new Date(val).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <a onClick={() => navigate(`/batches/${record.id}`)}>去审核</a>
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
          { key: 'page', label: '本页可处理', value: data.items.length },
          {
            key: 'cases',
            label: '本页用例数',
            value: data.items.reduce((sum, item) => sum + (item.total_cases ?? 0), 0),
          },
          {
            key: 'filter',
            label: '当前状态',
            value: STATUS_OPTIONS.find((item) => item.value === status)?.label || '全部',
          },
        ]}
      />

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
        {data.items.length === 0 && !loading ? (
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
          />
        )}
      </Spin>
    </PageShell>
  );
};

export default ReviewCenter;
