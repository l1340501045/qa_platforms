import React, { useEffect, useState } from 'react';
import {
  Breadcrumb,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  message,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
} from 'antd';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import { triggerGeneration } from '../../services/batchApi';
import { createDocAssociation, getDocAssociations } from '../../services/documentApi';
import type { DocAssociations, DocRelationType } from '../../types';
import type { ColumnsType } from 'antd/es/table';

const docTypeColorMap: Record<string, string> = {
  prd: 'blue',
  tech_doc: 'green',
  test_rule: 'orange',
  test_case: 'purple',
  bug_record: 'red',
  prototype: 'cyan',
  other: 'default',
};

const relationTypeLabels: Record<DocRelationType, string> = {
  req_to_tech: '需求→技术',
  req_to_case: '需求→用例',
  req_to_bug: '需求→缺陷',
  req_to_proto: '需求→原型',
  tech_to_case: '技术→用例',
  case_to_bug: '用例→缺陷',
  general: '通用关联',
};

const DocumentDetailPage: React.FC = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();

  const { currentDocument, fetchDocument } = useKnowledgeStore();

  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [associations, setAssociations] = useState<DocAssociations | null>(null);
  const [assocLoading, setAssocLoading] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm] = Form.useForm();
  const [addSubmitting, setAddSubmitting] = useState(false);

  useEffect(() => {
    if (!documentId) return;
    loadDocument();
    loadAssociations();
  }, [documentId]);

  const loadDocument = async () => {
    if (!documentId) return;
    setLoading(true);
    try {
      await fetchDocument(documentId);
    } catch (err: any) {
      message.error(err?.message || '加载文档失败');
    } finally {
      setLoading(false);
    }
  };

  const loadAssociations = async () => {
    if (!documentId) return;
    setAssocLoading(true);
    try {
      const data = await getDocAssociations(documentId);
      setAssociations(data);
    } catch (err: any) {
      message.error(err?.message || '加载关联失败');
    } finally {
      setAssocLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!documentId) return;
    setGenerating(true);
    try {
      const res = await triggerGeneration(documentId);
      message.success('生成任务已创建');
      navigate(`/batches/${res.batch_id}`);
    } catch (err: any) {
      message.error(err?.message || '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleAddAssociation = async () => {
    if (!documentId) return;
    try {
      const values = await addForm.validateFields();
      setAddSubmitting(true);
      await createDocAssociation(documentId, {
        target_document_id: values.target_document_id,
        relation_type: values.relation_type,
      });
      message.success('关联添加成功');
      setAddModalOpen(false);
      addForm.resetFields();
      loadAssociations();
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error(err?.message || '添加关联失败');
    } finally {
      setAddSubmitting(false);
    }
  };

  const assocColumns: ColumnsType<DocAssociations['direct'][number]> = [
    {
      title: '文档标题',
      dataIndex: ['document', 'title'],
      key: 'title',
      render: (text: string, record) => (
        <Link to={`/documents/${record.document.id}`}>{text}</Link>
      ),
    },
    {
      title: '文档类型',
      dataIndex: ['document', 'doc_type'],
      key: 'doc_type',
      width: 100,
      render: (type: string) => (
        <Tag color={docTypeColorMap[type] || 'default'}>{type}</Tag>
      ),
    },
    {
      title: '关联类型',
      dataIndex: 'relation_type',
      key: 'relation_type',
      width: 120,
      render: (type: DocRelationType) => (
        <Tag>{relationTypeLabels[type] || type}</Tag>
      ),
    },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 80,
      render: (dir: string) => (dir === 'outgoing' ? '出' : '入'),
    },
  ];

  if (loading || !currentDocument) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <Link to="/systems">系统列表</Link> },
          { title: '文档详情' },
        ]}
      />

      <Card style={{ marginBottom: 24 }}>
        <Descriptions title="文档基本信息" column={2}>
          <Descriptions.Item label="标题">{currentDocument.title}</Descriptions.Item>
          <Descriptions.Item label="类型">
            <Tag color={docTypeColorMap[currentDocument.doc_type]}>
              {currentDocument.doc_type}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">{currentDocument.status}</Descriptions.Item>
          <Descriptions.Item label="存储路径">
            {currentDocument.storage_path}
          </Descriptions.Item>
        </Descriptions>

        <Space style={{ marginTop: 16 }}>
          <Button type="primary" onClick={handleGenerate} loading={generating}>
            生成测试用例
          </Button>
          <Button onClick={() => setAddModalOpen(true)}>添加关联</Button>
        </Space>
      </Card>

      <Card title="关联文档">
        <Spin spinning={assocLoading}>
          <Table
            columns={assocColumns}
            dataSource={associations?.direct || []}
            rowKey="id"
            pagination={false}
          />
        </Spin>
      </Card>

      {/* 添加关联 Modal */}
      <Modal
        title="添加文档关联"
        open={addModalOpen}
        onCancel={() => setAddModalOpen(false)}
        onOk={handleAddAssociation}
        confirmLoading={addSubmitting}
        okText="添加"
        cancelText="取消"
      >
        <Form form={addForm} layout="vertical">
          <Form.Item
            name="target_document_id"
            label="目标文档 ID"
            rules={[{ required: true, message: '请输入目标文档 ID' }]}
          >
            <Input placeholder="请输入要关联的文档 ID" />
          </Form.Item>
          <Form.Item
            name="relation_type"
            label="关联类型"
            rules={[{ required: true, message: '请选择关联类型' }]}
          >
            <Select placeholder="请选择关联类型">
              {Object.entries(relationTypeLabels).map(([value, label]) => (
                <Select.Option key={value} value={value}>
                  {label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default DocumentDetailPage;
