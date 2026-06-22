import React, { useCallback, useEffect, useState } from 'react';
import { Empty, Select, Spin, Table, Tag } from 'antd';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';

import { listBatches } from '../../services/batchApi';
import type { BatchStatus, PaginatedData, ReviewBatch } from '../../types';

const STATUS_OPTIONS = [
  { value: 'pending_review', label: '待审核' },
  { value: 'reviewing', label: '审核中' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已落库' },
];

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending_review: { color: 'orange', text: '待审核' },
  reviewing: { color: 'processing', text: '审核中' },
  completed: { color: 'green', text: '已完成' },
  archived: { color: 'default', text: '已落库' },
  running: { color: 'blue', text: '生成中' },
  failed: { color: 'red', text: '失败' },
  pending: { color: 'default', text: '排队中' },
  suspended: { color: 'purple', text: '待澄清' },
};

const ReviewCenter: React.FC = () => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string>('pending_review');
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
        const cfg = STATUS_TAG[val] || { color: 'default', text: val };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
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
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>审核中心</h2>
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
      </div>

      <Spin spinning={loading}>
        {data.items.length === 0 && !loading ? (
          <Empty description="暂无待审批次" />
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
    </div>
  );
};

export default ReviewCenter;
