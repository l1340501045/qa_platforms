/**
 * 导出中心 — /exports
 * 创建导出任务 + 任务列表 + processing 状态自动轮询
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { DownloadOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import { createExport, listExports } from '../../services/exportApi';
import { listSystemOptions, listSystemBatches } from '../../services/systemApi';
import type { SystemBatchItem } from '../../services/systemApi';
import EmptyState from '../../components/common/EmptyState';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';
import type {
  CreateExportRequest,
  ExportFormat,
  ExportScope,
  ExportStatus,
  ExportTask,
  PaginatedData,
} from '../../types';

const { Text } = Typography;

// ─── 状态 Badge 映射 ───
const STATUS_MAP: Record<ExportStatus, { status: 'processing' | 'success' | 'error'; text: string }> = {
  processing: { status: 'processing', text: '处理中' },
  completed: { status: 'success', text: '已完成' },
  failed: { status: 'error', text: '失败' },
};

const SCOPE_LABEL: Record<ExportScope, string> = {
  batch: '批次',
  system: '系统',
};

const FORMAT_LABEL: Record<ExportFormat, string> = {
  markdown: 'Markdown',
  excel: 'Excel',
};

const FORMAT_HELP: Record<ExportFormat, string> = {
  markdown: '适合评审、归档和人工阅读。',
  excel: '适合导入外部测试管理工具或继续二次处理。',
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
  const [systemOptions, setSystemOptions] = useState<Array<{ id: string; name: string }>>([]);
  const [batchOptions, setBatchOptions] = useState<SystemBatchItem[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ExportStatus | undefined>();

  // ─── 轮询 ───
  const pollTimerRef = useRef<number | null>(null);
  const statusFilterRef = useRef<ExportStatus | undefined>(statusFilter);
  statusFilterRef.current = statusFilter;

  // ─── 加载列表 ───
  const fetchList = useCallback(async (page = 1, perPage = 20, status?: ExportStatus) => {
    setLoading(true);
    try {
      const result = await listExports({ page, per_page: perPage, status });
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
            const result = await listExports({
              page: current.page,
              per_page: current.per_page,
              status: statusFilterRef.current,
            });
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
      fetchList(page, pageSize, statusFilter);
    },
    [fetchList, statusFilter],
  );

  const handleStatusFilterChange = (value?: ExportStatus) => {
    setStatusFilter(value);
    fetchList(1, data.per_page, value);
  };

  // ─── 创建导出 ───
  const handleCreate = useCallback(async () => {
    if (formScope === 'batch' && !formBatchId) {
      message.warning('请选择批次');
      return;
    }
    if (formScope === 'system' && !formSystemId) {
      message.warning('请选择系统');
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
      await fetchList(1, data.per_page, statusFilter);
    } catch {
      message.error('创建导出任务失败');
    } finally {
      setCreateLoading(false);
    }
  }, [formScope, formFormat, formBatchId, formSystemId, fetchList, data.per_page, statusFilter]);

  const resetForm = () => {
    setFormScope('batch');
    setFormFormat('markdown');
    setFormBatchId('');
    setFormSystemId('');
    setBatchOptions([]);
  };

  // 打开新建弹窗时懒加载系统选项
  const openCreateModal = () => {
    setModalOpen(true);
    if (systemOptions.length === 0) {
      listSystemOptions().then(setSystemOptions).catch(() => {});
    }
  };

  // 选中系统后加载该系统可见批次（batch scope 联动）
  const handleSystemChange = (sysId: string) => {
    setFormSystemId(sysId);
    setFormBatchId('');
    setBatchOptions([]);
    if (sysId) {
      setBatchLoading(true);
      listSystemBatches(sysId, { per_page: 100 })
        .then((res) =>
          setBatchOptions(
            res.items.filter((b) =>
              ['pending_review', 'completed', 'archived'].includes(b.status),
            ),
          ),
        )
        .catch(() => setBatchOptions([]))
        .finally(() => setBatchLoading(false));
    }
  };

  // ─── 表格列 ───
  const columns: ColumnsType<ExportTask> = [
    {
      title: '导出任务',
      key: 'task',
      width: 360,
      render: (_, record) => (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space size={8} wrap>
            <Text strong>{SCOPE_LABEL[record.export_scope]}导出</Text>
            <Tag>{FORMAT_LABEL[record.format]}</Tag>
            <Text type="secondary">#{record.id.slice(0, 8)}</Text>
          </Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            创建于 {new Date(record.created_at).toLocaleString('zh-CN')}
            {record.total_cases != null ? ` · ${record.total_cases} 条用例` : ''}
          </Text>
          <Space size={8} wrap>
            {record.status === 'completed' && record.file_url ? (
              <Button
                type="link"
                size="small"
                icon={<DownloadOutlined />}
                href={record.file_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ paddingInline: 0 }}
              >
                下载文件
              </Button>
            ) : null}
            {record.status === 'failed' && (
              <Text type="danger" style={{ fontSize: 13 }}>
                {record.error_message || '导出失败，可重新创建任务'}
              </Text>
            )}
          </Space>
        </Space>
      ),
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
      title: '范围',
      dataIndex: 'export_scope',
      key: 'export_scope',
      width: 90,
      render: (val: ExportScope) => SCOPE_LABEL[val],
    },
    {
      title: '格式',
      dataIndex: 'format',
      key: 'format',
      width: 120,
      render: (val: ExportFormat) => FORMAT_LABEL[val],
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      key: 'completed_at',
      width: 170,
      render: (val: string | null) => (val ? new Date(val).toLocaleString('zh-CN') : '-'),
    },
  ];

  const processingCount = data.items.filter((item) => item.status === 'processing').length;
  const completedCount = data.items.filter((item) => item.status === 'completed').length;
  const failedCount = data.items.filter((item) => item.status === 'failed').length;
  const downloadableCount = data.items.filter((item) => item.status === 'completed' && item.file_url).length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="导出中心"
        title="用例交付导出"
        description="从已审查批次或系统资产生成交付文件；Markdown 适合评审归档，Excel 适合同步外部测试管理工具。"
        actions={
          <>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => fetchList(data.page, data.per_page, statusFilter)}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
              新建导出
            </Button>
          </>
        }
      />

      <Alert
        type={processingCount > 0 ? 'info' : 'success'}
        showIcon
        style={{ marginBottom: 16 }}
        message={processingCount > 0 ? '导出任务正在生成，页面会自动刷新状态' : '导出中心用于拿到可交付文件'}
        description="建议先完成批次审查或落库，再从这里导出批次结果或系统资产快照。完成后直接下载文件；失败任务可按相同范围重新创建。"
      />

      <MetricStrip
        items={[
          { key: 'total', label: '任务总数', value: data.total },
          { key: 'processing', label: '本页处理中', value: processingCount, tone: 'primary' },
          { key: 'completed', label: '本页已完成', value: completedCount, tone: 'success' },
          { key: 'downloadable', label: '可下载文件', value: downloadableCount, tone: 'success' },
          { key: 'failed', label: '本页失败', value: failedCount, tone: 'danger' },
        ]}
      />

      <FilterBar>
        <Text strong>任务状态</Text>
        <Select<ExportStatus | undefined>
          allowClear
          placeholder="全部状态"
          style={{ width: 160 }}
          value={statusFilter}
          onChange={handleStatusFilterChange}
          options={[
            { value: 'processing', label: '处理中' },
            { value: 'completed', label: '已完成' },
            { value: 'failed', label: '失败' },
          ]}
        />
        <Text type="secondary">筛选会请求后端导出列表，不只是当前页过滤。</Text>
      </FilterBar>

      {/* ─── 列表 ─── */}
      <Spin spinning={loading}>
        {data.items.length === 0 ? (
          <EmptyState
            title={statusFilter ? '当前状态下没有导出任务' : '还没有导出任务'}
            description={statusFilter ? '可以切换状态筛选，或新建一个导出任务。' : '从已审查批次或系统资产创建一个导出任务，完成后可下载交付文件。'}
            action={
              <Space wrap>
                {statusFilter && <Button onClick={() => handleStatusFilterChange(undefined)}>查看全部</Button>}
                <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
                  新建导出
                </Button>
              </Space>
            }
          />
        ) : (
          <div
            style={{
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              overflow: 'hidden',
            }}
          >
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
              scroll={{ x: 760 }}
            />
          </div>
        )}
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
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="选择导出范围和交付格式"
          description="批次导出适合交付单次生成和审查结果；系统导出适合拿到当前系统的资产快照。"
        />
        <div style={{ marginBottom: 16 }}>
          <div style={{ marginBottom: 8 }}>范围：</div>
          <Radio.Group
            value={formScope}
            onChange={(e) => {
              const v = e.target.value as ExportScope;
              setFormScope(v);
              setFormBatchId('');
              if (v === 'batch' && formSystemId) handleSystemChange(formSystemId);
            }}
          >
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
          <div style={{ marginTop: 8, color: layoutTokens.textSecondary }}>
            {FORMAT_HELP[formFormat]}
          </div>
        </div>

        {formScope === 'batch' ? (
          <>
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>系统：</div>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择系统"
                style={{ width: '100%' }}
                value={formSystemId || undefined}
                onChange={handleSystemChange}
                options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>批次：</div>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder={formSystemId ? '选择批次' : '请先选择系统'}
                style={{ width: '100%' }}
                value={formBatchId || undefined}
                onChange={setFormBatchId}
                loading={batchLoading}
                disabled={!formSystemId}
                options={batchOptions.map((b) => {
                  const statusLabel =
                    b.status === 'pending_review' ? '待审阅' :
                    b.status === 'completed' ? '已完成' :
                    b.status === 'archived' ? '已落库' : b.status;
                  const date = new Date(b.created_at).toLocaleDateString('zh-CN');
                  return {
                    value: b.id,
                    label: `${b.document_title} · ${date} · ${b.total_cases ?? 0}例 · ${statusLabel}`,
                  };
                })}
              />
            </div>
          </>
        ) : (
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>系统：</div>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择系统"
              style={{ width: '100%' }}
              value={formSystemId || undefined}
              onChange={setFormSystemId}
              options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
            />
          </div>
        )}
      </Modal>
    </PageShell>
  );
};

export default Exports;
