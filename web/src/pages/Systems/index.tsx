import React, { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Form,
  Input,
  message,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  DeleteOutlined,
  EditOutlined,
  FolderOpenOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import type { System } from '../../types';
import EmptyState from '../../components/common/EmptyState';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';

const { Text, Link } = Typography;

type SystemStage = 'empty' | 'with_docs' | 'with_batches';
type SystemStageFilter = 'all' | SystemStage;
type SystemSort = 'updated_desc' | 'name_asc' | 'documents_desc' | 'batches_desc';

const SYSTEM_STAGE_META: Record<SystemStage, { label: string; color: string; nextAction: string }> = {
  empty: { label: '待上传资料', color: 'default', nextAction: '上传资料' },
  with_docs: { label: '已有资料', color: 'blue', nextAction: '发起生成' },
  with_batches: { label: '已有批次', color: 'green', nextAction: '进入知识库' },
};

function renderCount(count?: number): number | string {
  return typeof count === 'number' ? count : '--';
}

function numericCount(count?: number): number {
  return typeof count === 'number' ? count : 0;
}

function getSystemStage(system: System): SystemStage {
  if (numericCount(system.batch_count) > 0) return 'with_batches';
  if (numericCount(system.document_count) > 0) return 'with_docs';
  return 'empty';
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleDateString();
}

function nowrapTitle(text: string): React.ReactNode {
  return <span style={{ whiteSpace: 'nowrap' }}>{text}</span>;
}

const SystemsPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    systems,
    systemsTotal,
    systemsPage,
    systemsPerPage,
    systemsLoading,
    fetchSystems,
    createSystem,
    updateSystem,
    deleteSystem,
  } = useKnowledgeStore();

  const [modalOpen, setModalOpen] = useState(false);
  const [editingSystem, setEditingSystem] = useState<System | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [stageFilter, setStageFilter] = useState<SystemStageFilter>('all');
  const [sortBy, setSortBy] = useState<SystemSort>('updated_desc');
  const [form] = Form.useForm();

  const knownDocumentTotal = systems.reduce(
    (sum, system) => sum + (typeof system.document_count === 'number' ? system.document_count : 0),
    0,
  );
  const knownBatchTotal = systems.reduce(
    (sum, system) => sum + (typeof system.batch_count === 'number' ? system.batch_count : 0),
    0,
  );
  const activeSystems = systems.filter(
    (system) => (system.document_count ?? 0) > 0 || (system.batch_count ?? 0) > 0,
  ).length;
  const waitingSystems = systems.filter((system) => getSystemStage(system) === 'empty').length;
  const generatedSystems = systems.filter((system) => getSystemStage(system) === 'with_batches').length;

  const visibleSystems = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLocaleLowerCase();
    const filtered = systems.filter((system) => {
      const stage = getSystemStage(system);
      const matchesStage = stageFilter === 'all' || stage === stageFilter;
      const matchesKeyword =
        !normalizedKeyword ||
        system.name.toLocaleLowerCase().includes(normalizedKeyword) ||
        (system.description || '').toLocaleLowerCase().includes(normalizedKeyword);

      return matchesStage && matchesKeyword;
    });

    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'name_asc':
          return a.name.localeCompare(b.name, 'zh-Hans-CN');
        case 'documents_desc':
          return numericCount(b.document_count) - numericCount(a.document_count);
        case 'batches_desc':
          return numericCount(b.batch_count) - numericCount(a.batch_count);
        case 'updated_desc':
        default:
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      }
    });
  }, [keyword, sortBy, stageFilter, systems]);

  useEffect(() => {
    fetchSystems({ page: 1, per_page: systemsPerPage });
  }, []);

  const handlePageChange = (page: number, pageSize: number) => {
    fetchSystems({ page, per_page: pageSize });
  };

  const openKnowledgeBase = (system: System, e?: React.MouseEvent<HTMLElement>) => {
    e?.stopPropagation();
    navigate(`/systems/${system.id}/documents`);
  };

  const openCreateModal = () => {
    setEditingSystem(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEditModal = (system: System, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSystem(system);
    form.setFieldsValue({ name: system.name, description: system.description || '' });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      if (editingSystem) {
        await updateSystem(editingSystem.id, values);
        message.success('系统更新成功');
      } else {
        await createSystem(values);
        message.success('系统创建成功');
      }
      setModalOpen(false);
      form.resetFields();
    } catch (err: any) {
      if (err?.errorFields) return; // form validation error
      message.error(err?.message || '操作失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = (system: System, e: React.MouseEvent) => {
    e.stopPropagation();
    Modal.confirm({
      title: '确认删除',
      content: `确定删除系统「${system.name}」？此操作不可撤销。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteSystem(system.id);
          message.success('删除成功');
        } catch (err: any) {
          message.error(err?.message || '删除失败');
        }
      },
    });
  };

  const clearFilters = () => {
    setKeyword('');
    setStageFilter('all');
    setSortBy('updated_desc');
  };

  const columns: ColumnsType<System> = [
    {
      title: nowrapTitle('系统'),
      key: 'system',
      render: (_, system) => (
        <div style={{ minWidth: 0 }}>
          <Link strong onClick={(event) => openKnowledgeBase(system, event)}>
            {system.name}
          </Link>
          <Text
            style={{
              display: 'block',
              marginTop: 4,
              color: layoutTokens.textSecondary,
              maxWidth: 420,
            }}
            ellipsis={{ tooltip: system.description || '暂无描述' }}
          >
            {system.description || '暂无描述'}
          </Text>
          <Space size={12} wrap style={{ marginTop: 4 }}>
            <Button
              size="small"
              type="link"
              icon={<FolderOpenOutlined />}
              style={{ padding: 0, height: 24 }}
              onClick={(event) => openKnowledgeBase(system, event)}
            >
              {SYSTEM_STAGE_META[getSystemStage(system)].nextAction}
            </Button>
            <Button
              aria-label={`编辑 ${system.name}`}
              size="small"
              type="link"
              icon={<EditOutlined />}
              style={{ padding: 0, height: 24 }}
              onClick={(event) => openEditModal(system, event)}
            >
              编辑
            </Button>
            <Button
              aria-label={`删除 ${system.name}`}
              size="small"
              type="link"
              danger
              icon={<DeleteOutlined />}
              style={{ padding: 0, height: 24 }}
              onClick={(event) => handleDelete(system, event)}
            >
              删除
            </Button>
          </Space>
        </div>
      ),
    },
    {
      title: nowrapTitle('资料状态'),
      key: 'stage',
      width: 104,
      render: (_, system) => {
        const stage = getSystemStage(system);
        const meta = SYSTEM_STAGE_META[stage];
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: nowrapTitle('文档数'),
      dataIndex: 'document_count',
      key: 'document_count',
      width: 72,
      align: 'right',
      render: (count: number | undefined) => renderCount(count),
    },
    {
      title: nowrapTitle('批次数'),
      dataIndex: 'batch_count',
      key: 'batch_count',
      width: 72,
      align: 'right',
      render: (count: number | undefined) => renderCount(count),
    },
    {
      title: nowrapTitle('最近活动'),
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 104,
      render: (value: string) => formatDate(value),
    },
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow="项目入口"
        title="项目/系统"
        description="先选择业务系统，再进入知识库上传需求资料、发起生成或查看已有批次。"
        actions={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
            新建系统
          </Button>
        }
      />

      <MetricStrip
        items={[
          { key: 'systems', label: '系统总数', value: systemsTotal },
          { key: 'active', label: '当前页有资料/批次', value: activeSystems, tone: 'primary' },
          { key: 'waiting', label: '当前页待上传资料', value: waitingSystems, tone: waitingSystems > 0 ? 'warning' : 'default' },
          { key: 'generated', label: '当前页已有批次', value: generatedSystems, tone: generatedSystems > 0 ? 'success' : 'default' },
          { key: 'documents', label: '当前页文档数', value: knownDocumentTotal },
          { key: 'batches', label: '当前页批次数', value: knownBatchTotal },
        ]}
      />

      <FilterBar>
        <Input.Search
          allowClear
          placeholder="按系统名称或描述筛选当前页"
          style={{ width: 280 }}
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <Select<SystemStageFilter>
          value={stageFilter}
          style={{ width: 170 }}
          onChange={setStageFilter}
          options={[
            { value: 'all', label: '全部资料状态' },
            { value: 'empty', label: '待上传资料' },
            { value: 'with_docs', label: '已有资料' },
            { value: 'with_batches', label: '已有批次' },
          ]}
        />
        <Select<SystemSort>
          value={sortBy}
          style={{ width: 170 }}
          onChange={setSortBy}
          options={[
            { value: 'updated_desc', label: '按最近活动' },
            { value: 'name_asc', label: '按系统名称' },
            { value: 'documents_desc', label: '按文档数' },
            { value: 'batches_desc', label: '按批次数' },
          ]}
        />
        {(keyword || stageFilter !== 'all' || sortBy !== 'updated_desc') && (
          <Button onClick={clearFilters}>重置</Button>
        )}
      </FilterBar>

      <Spin spinning={systemsLoading}>
        {systems.length > 0 && visibleSystems.length > 0 && (
          <div
            style={{
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              overflow: 'hidden',
            }}
          >
            <Table<System>
              rowKey="id"
              columns={columns}
              dataSource={visibleSystems}
              pagination={false}
              size="middle"
              scroll={{ x: 720 }}
              onRow={(system) => ({
                onClick: () => openKnowledgeBase(system),
                style: { cursor: 'pointer' },
              })}
            />
          </div>
        )}

        {systems.length === 0 && !systemsLoading && (
          <EmptyState
            title="还没有项目/系统"
            description="先创建一个业务系统，再上传 PRD、技术文档或测试规则。"
            action={
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
                新建系统
              </Button>
            }
          />
        )}

        {systems.length > 0 && visibleSystems.length === 0 && !systemsLoading && (
          <EmptyState
            title="当前页没有匹配的系统"
            description="筛选只作用于当前分页；可以重置筛选或切换分页继续查找。"
            action={<Button onClick={clearFilters}>重置筛选</Button>}
          />
        )}
      </Spin>

      {systemsTotal > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 24 }}>
          <Pagination
            current={systemsPage}
            pageSize={systemsPerPage}
            total={systemsTotal}
            onChange={handlePageChange}
            showSizeChanger
            showTotal={(total) => `共 ${total} 个系统`}
          />
        </div>
      )}

      <Modal
        title={editingSystem ? '编辑系统' : '新建系统'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={editingSystem ? '保存' : '创建'}
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="系统名称"
            rules={[{ required: true, message: '请输入系统名称' }]}
          >
            <Input placeholder="请输入系统名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={4} placeholder="请输入系统描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>
    </PageShell>
  );
};

export default SystemsPage;
