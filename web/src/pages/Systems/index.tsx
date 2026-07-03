import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  message,
  Modal,
  Pagination,
  Row,
  Spin,
  Tooltip,
  Typography,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import type { System } from '../../types';
import EmptyState from '../../components/common/EmptyState';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';

const { Meta } = Card;
const { Text } = Typography;

function renderCount(count?: number): number | string {
  return typeof count === 'number' ? count : '--';
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

  useEffect(() => {
    fetchSystems({ page: 1, per_page: systemsPerPage });
  }, []);

  const handlePageChange = (page: number, pageSize: number) => {
    fetchSystems({ page, per_page: pageSize });
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
          { key: 'documents', label: '当前页文档数', value: knownDocumentTotal },
          { key: 'batches', label: '当前页批次数', value: knownBatchTotal },
        ]}
      />

      <Spin spinning={systemsLoading}>
        <Row gutter={[16, 16]}>
          {systems.map((system) => (
            <Col key={system.id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                onClick={() => navigate(`/systems/${system.id}/documents`)}
                actions={[
                  <Tooltip title="编辑" key="edit">
                    <EditOutlined onClick={(e) => openEditModal(system, e)} />
                  </Tooltip>,
                  <Tooltip title="删除" key="delete">
                    <DeleteOutlined onClick={(e) => handleDelete(system, e)} />
                  </Tooltip>,
                ]}
              >
                <Meta
                  title={system.name}
                  description={system.description || '暂无描述'}
                />
                <div style={{ marginTop: 14 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <div
                      style={{
                        padding: 10,
                        borderRadius: layoutTokens.radius,
                        background: layoutTokens.surfaceMuted,
                      }}
                    >
                      <Text type="secondary">文档数</Text>
                      <div style={{ fontWeight: 650, fontSize: 18 }}>
                        {renderCount(system.document_count)}
                      </div>
                    </div>
                    <div
                      style={{
                        padding: 10,
                        borderRadius: layoutTokens.radius,
                        background: layoutTokens.surfaceMuted,
                      }}
                    >
                      <Text type="secondary">批次数</Text>
                      <div style={{ fontWeight: 650, fontSize: 18 }}>
                        {renderCount(system.batch_count)}
                      </div>
                    </div>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <Text type="secondary">
                      最近更新：{new Date(system.updated_at).toLocaleDateString()}
                    </Text>
                  </div>
                  <Button type="link" style={{ padding: 0, marginTop: 8 }}>
                    进入知识库
                  </Button>
                </div>
              </Card>
            </Col>
          ))}
        </Row>

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
