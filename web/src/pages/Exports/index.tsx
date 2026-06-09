/**
 * 导出中心 — /exports
 * 创建导出任务 + 任务列表 + processing 状态自动轮询
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Input,
  Modal,
  Radio,
  Spin,
  Table,
  message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import { createExport, listExports } from '../../services/exportApi';
import type {
  CreateExportRequest,
  ExportFormat,
  ExportScope,
  ExportStatus,
  ExportTask,
  PaginatedData,
} from '../../types';

// ─── 状态 Badge 映射 ───
const STATUS_MAP: Record<ExportStatus, { status: 'processing' | 'success' | 'error'; text: string }> = {
  processing: { status: 'processing', text: '处理中' },
  completed: { status: 'success', text: '已完成' },
  failed: { status: 'error', text: '失败' },
};

const POLL_INTERVAL = 3000;

const Exports: React.FC = () => {
  // ─── 列表状态 ───
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PaginatedData<ExportTask>>({
    items: [],
    total: 0,
    page: 1,
    per_page: 20,
    total_pages: 0,
  });

  // ─── Modal 状态 ───
  const [modalOpen, setModalOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [formScope, setFormScope] = useState<ExportScope>('batch');
  const [formFormat, setFormFormat] = useState<ExportFormat>('markdown');
  const [formBatchId, setFormBatchId] = useState('');
  const [formSystemId, setFormSystemId] = useState('');

  // ─── 轮询 ───
  const pollTimerRef = useRef<number | null>(null);

  // ─── 加载列表 ───
  const fetchList = useCallback(async (page = 1, perPage = 20) => {
    setLoading(true);
    try {
      const result = await listExports({ page, per_page: perPage });
      setData(result);
    } catch {
      message.error('加载导出列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // ─── 轮询逻辑：有 processing 任务时轮询 ───
  const dataRef = useRef(data);
  dataRef.current = data;

  const startPollIfNeeded = useCallback(
    (items: ExportTask[]) => {
      const hasProcessing = items.some((t) => t.status === 'processing');

      if (hasProcessing && pollTimerRef.current === null) {
        pollTimerRef.current = window.setInterval(async () => {
          try {
            const current = dataRef.current;
            const result = await listExports({ page: current.page, per_page: current.per_page });
            setData(result);
            // 如果没有 processing 任务了，停止轮询
            if (!result.items.some((t) => t.status === 'processing')) {
              if (pollTimerRef.current !== null) {
                window.clearInterval(pollTimerRef.current);
                pollTimerRef.current = null;
              }
            }
          } catch {
            // 静默失败，不中断轮询
          }
        }, POLL_INTERVAL);
      }

      if (!hasProcessing && pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    },
    [],
  );

  // ─── 数据变化时检查是否需要轮询 ───
  useEffect(() => {
    startPollIfNeeded(data.items);
  }, [data.items, startPollIfNeeded]);

  // ─── 初始化 ───
  useEffect(() => {
    fetchList();
    return () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── 分页变化 ───
  const handlePageChange = useCallback(
    (page: number, pageSize: number) => {
      fetchList(page, pageSize);
    },
    [fetchList],
  );

  // ─── 创建导出 ───
  const handleCreate = useCallback(async () => {
    if (formScope === 'batch' && !formBatchId.trim()) {
      message.warning('请输入 Batch ID');
      return;
    }
    if (formScope === 'system' && !formSystemId.trim()) {
      message.warning('请输入 System ID');
      return;
    }

    const body: CreateExportRequest = {
      scope: formScope,
      format: formFormat,
      ...(formScope === 'batch' ? { batch_id: formBatchId.trim() } : { system_id: formSystemId.trim() }),
    };

    setCreateLoading(true);
    try {
      await createExport(body);
      message.success('导出任务已创建');
      setModalOpen(false);
      resetForm();
      // 刷新列表
      await fetchList(1, data.per_page);
    } catch {
      message.error('创建导出任务失败');
    } finally {
      setCreateLoading(false);
    }
  }, [formScope, formFormat, formBatchId, formSystemId, fetchList, data.per_page]);

  const resetForm = () => {
    setFormScope('batch');
    setFormFormat('markdown');
    setFormBatchId('');
    setFormSystemId('');
  };

  // ─── 表格列 ───
  const columns: ColumnsType<ExportTask> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 100,
      render: (val: string) => val.slice(0, 8),
    },
    {
      title: '范围',
      dataIndex: 'export_scope',
      key: 'export_scope',
      width: 80,
      render: (val: ExportScope) => (val === 'batch' ? '批次' : '系统'),
    },
    {
      title: '格式',
      dataIndex: 'format',
      key: 'format',
      width: 100,
      render: (val: ExportFormat) => (val === 'markdown' ? 'Markdown' : 'Excel'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (val: ExportStatus) => {
        const cfg = STATUS_MAP[val];
        return <Badge status={cfg.status} text={cfg.text} />;
      },
    },
    {
      title: '文件',
      dataIndex: 'file_url',
      key: 'file_url',
      width: 100,
      render: (val: string | null, record: ExportTask) => {
        if (record.status === 'completed' && val) {
          return (
            <a href={val} target="_blank" rel="noopener noreferrer">
              下载
            </a>
          );
        }
        return '-';
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (val: string) => new Date(val).toLocaleString('zh-CN'),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* ─── 顶部 ─── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>导出中心</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          新建导出
        </Button>
      </div>

      {/* ─── 列表 ─── */}
      <Spin spinning={loading}>
        <Table<ExportTask>
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
      </Spin>

      {/* ─── 新建导出 Modal ─── */}
      <Modal
        title="新建导出任务"
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          resetForm();
        }}
        onOk={handleCreate}
        confirmLoading={createLoading}
        okText="创建"
        cancelText="取消"
      >
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8 }}>范围：</div>
          <Radio.Group value={formScope} onChange={(e) => setFormScope(e.target.value)}>
            <Radio value="batch">批次</Radio>
            <Radio value="system">系统</Radio>
          </Radio.Group>
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8 }}>格式：</div>
          <Radio.Group value={formFormat} onChange={(e) => setFormFormat(e.target.value)}>
            <Radio value="markdown">Markdown</Radio>
            <Radio value="excel">Excel</Radio>
          </Radio.Group>
        </div>

        <div style={{ marginBottom: 16 }}>
          {formScope === 'batch' ? (
            <>
              <div style={{ marginBottom: 8 }}>Batch ID：</div>
              <Input
                placeholder="请输入批次 ID"
                value={formBatchId}
                onChange={(e) => setFormBatchId(e.target.value)}
              />
            </>
          ) : (
            <>
              <div style={{ marginBottom: 8 }}>System ID：</div>
              <Input
                placeholder="请输入系统 ID"
                value={formSystemId}
                onChange={(e) => setFormSystemId(e.target.value)}
              />
            </>
          )}
        </div>
      </Modal>
    </div>
  );
};

export default Exports;
