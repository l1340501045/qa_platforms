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

const { Meta } = Card;
const { Text } = Typography;

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
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          系统列表
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          新建系统
        </Button>
      </div>

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
                <div style={{ marginTop: 12 }}>
                  <Text type="secondary">文档数：{system.document_count ?? 0}</Text>
                  <br />
                  <Text type="secondary">批次数：{system.batch_count ?? 0}</Text>
                  <br />
                  <Text type="secondary">
                    创建时间：{new Date(system.created_at).toLocaleDateString()}
                  </Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>

        {systems.length === 0 && !systemsLoading && (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Text type="secondary">暂无系统，请点击右上角「新建系统」</Text>
          </div>
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
    </div>
  );
};

export default SystemsPage;
