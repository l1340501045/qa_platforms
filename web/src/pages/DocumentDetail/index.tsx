import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Form,
  message,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ArrowLeftOutlined,
  EditOutlined,
  FileSearchOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  ProfileOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams, Link, useSearchParams } from 'react-router-dom';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import { triggerGeneration } from '../../services/batchApi';
import { createDocAssociation, getDocAssociations, listDocuments } from '../../services/documentApi';
import { listSystemOptions } from '../../services/systemApi';
import CheatSheetDrawer from '../../components/CheatSheetDrawer';
import ParseResultDrawer from '../../components/ParseResultDrawer';
import EmptyState from '../../components/common/EmptyState';
import StatusTag, { type StatusTone } from '../../components/common/StatusTag';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';
import type { DocAssociations, DocRelationType, DocType, Document } from '../../types';
import type { ColumnsType } from 'antd/es/table';
import { buildDocumentBatchUrl, buildKnowledgeReturnUrl } from '../../utils/batchReturn';
import { getErrorMessage } from '../../utils/errorMessage';
import { buildSearchReturnUrl } from '../../utils/searchReturn';

const { Text } = Typography;

const docTypeColorMap: Record<string, string> = {
  prd: 'blue',
  tech_doc: 'green',
  test_rule: 'orange',
  test_case: 'purple',
  bug_record: 'red',
  prototype: 'cyan',
  other: 'default',
};

const docTypeLabelMap: Record<string, string> = {
  prd: 'PRD',
  tech_doc: '技术文档',
  test_rule: '测试规则',
  test_case: '测试用例',
  bug_record: '缺陷记录',
  prototype: '原型/图片',
  other: '其他',
};

const docTypeHelpMap: Record<DocType, string> = {
  prd: '产品需求、用户故事、业务规则，通常作为生成测试用例的主资料。',
  tech_doc: '接口、架构、状态机、缓存、权限等技术实现资料，用于补充测试依据。',
  test_rule: '团队测试规范、通用准入规则、专项 checklist，用于约束生成质量。',
  test_case: '已有测试用例或回归资产，用于迁移、比对和沉淀。',
  bug_record: '历史缺陷、线上问题或复盘记录，用于补充风险场景。',
  prototype: '原型截图、流程图、交互图片或含图片的 PRD 目录。',
  other: '无法归类的资料。系统不会把它当作主 PRD、技术文档或测试规则使用。',
};

const docTypeOptions: Array<{ label: string; value: DocType; description: string }> = [
  { label: docTypeLabelMap.prd, value: 'prd', description: docTypeHelpMap.prd },
  { label: docTypeLabelMap.tech_doc, value: 'tech_doc', description: docTypeHelpMap.tech_doc },
  { label: docTypeLabelMap.test_rule, value: 'test_rule', description: docTypeHelpMap.test_rule },
  { label: docTypeLabelMap.prototype, value: 'prototype', description: docTypeHelpMap.prototype },
  { label: docTypeLabelMap.bug_record, value: 'bug_record', description: docTypeHelpMap.bug_record },
  { label: docTypeLabelMap.test_case, value: 'test_case', description: docTypeHelpMap.test_case },
  { label: docTypeLabelMap.other, value: 'other', description: docTypeHelpMap.other },
];

const docStatusMap: Record<string, { label: string; tone: StatusTone }> = {
  uploading: { label: '上传中', tone: 'processing' },
  uploaded: { label: '已上传', tone: 'success' },
  importing: { label: '导入中', tone: 'processing' },
  imported: { label: '已导入', tone: 'success' },
  import_failed: { label: '导入失败', tone: 'danger' },
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

const EMBEDDING_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  pending: { label: '待嵌入', tone: 'default' },
  processing: { label: '嵌入中', tone: 'processing' },
  completed: { label: '已完成', tone: 'success' },
  failed: { label: '嵌入失败', tone: 'danger' },
};

const sectionStyle: React.CSSProperties = {
  border: `1px solid ${layoutTokens.border}`,
  borderRadius: layoutTokens.radius,
  background: layoutTokens.surface,
  padding: 16,
  marginBottom: 16,
};

const sectionTitleStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  gap: 12,
  marginBottom: 14,
};

const fieldGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
  gap: 14,
};

const metricToneFromStatus = (
  tone: StatusTone,
): 'default' | 'primary' | 'success' | 'warning' | 'danger' => {
  if (tone === 'processing' || tone === 'info') return 'primary';
  if (tone === 'success' || tone === 'warning' || tone === 'danger') return tone;
  return 'default';
};

const DocumentDetailPage: React.FC = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const { currentDocument, fetchDocument, updateDocumentType } = useKnowledgeStore();

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [associations, setAssociations] = useState<DocAssociations | null>(null);
  const [assocLoading, setAssocLoading] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm] = Form.useForm();
  const [addSubmitting, setAddSubmitting] = useState(false);
  const [typeForm] = Form.useForm<{ doc_type: DocType }>();
  const [typeModalOpen, setTypeModalOpen] = useState(false);
  const [typeSubmitting, setTypeSubmitting] = useState(false);
  const [systemOptions, setSystemOptions] = useState<Array<{ id: string; name: string }>>([]);
  const [systemOptionsLoading, setSystemOptionsLoading] = useState(false);
  const [systemOptionsError, setSystemOptionsError] = useState<string | null>(null);
  const [docOptions, setDocOptions] = useState<Document[]>([]);
  const [docLoading, setDocLoading] = useState(false);
  const [docOptionsError, setDocOptionsError] = useState<string | null>(null);
  const [assocSystemId, setAssocSystemId] = useState<string | undefined>();
  const [cheatSheetOpen, setCheatSheetOpen] = useState(false);
  const [parseOpen, setParseOpen] = useState(false);

  const fromKnowledge = searchParams.get('from') === 'knowledge';
  const fromSearch = searchParams.get('from') === 'search';
  const knowledgeSystemId = fromKnowledge ? searchParams.get('system_id') : null;
  const searchReturnUrl = buildSearchReturnUrl(searchParams);
  const returnUrl = fromSearch ? searchReturnUrl : buildKnowledgeReturnUrl(knowledgeSystemId);
  const returnLabel = fromSearch ? '返回搜索结果' : knowledgeSystemId ? '返回知识库' : '返回项目/系统';

  const loadDocument = useCallback(async () => {
    if (!documentId) return;
    setLoading(true);
    setLoadError(false);
    try {
      await fetchDocument(documentId);
    } catch (err: any) {
      setLoadError(true);
      message.error(err?.message || '加载文档失败');
    } finally {
      setLoading(false);
    }
  }, [documentId, fetchDocument]);

  const loadAssociations = useCallback(async () => {
    if (!documentId) return;
    setAssocLoading(true);
    setAssociations(null);
    try {
      const data = await getDocAssociations(documentId);
      setAssociations(data);
    } catch (err: any) {
      message.error(err?.message || '加载关联失败');
    } finally {
      setAssocLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    loadDocument();
    loadAssociations();
  }, [loadAssociations, loadDocument]);

  const handleGenerate = () => {
    if (!documentId) return;
    Modal.confirm({
      title: '生成测试用例',
      content: `将基于「${currentDocument?.title ?? '当前文档'}」创建新的生成批次。生成开始后会进入批次工作台查看进度。`,
      okText: '开始生成',
      cancelText: '取消',
      onOk: async () => {
        setGenerating(true);
        try {
          const res = await triggerGeneration(documentId);
          message.success('生成任务已创建');
          navigate(buildDocumentBatchUrl(res.batch_id, documentId, searchParams));
        } catch (err: any) {
          message.error(err?.message || '生成失败');
        } finally {
          setGenerating(false);
        }
      },
    });
  };

  const openAddModal = () => {
    addForm.resetFields();
    setDocOptions([]);
    setDocOptionsError(null);
    setAssocSystemId(undefined);
    setAddModalOpen(true);
    if (systemOptions.length === 0) {
      loadSystemOptions();
    }
  };

  const openTypeModal = () => {
    if (!currentDocument) return;
    typeForm.setFieldsValue({ doc_type: currentDocument.doc_type });
    setTypeModalOpen(true);
  };

  const handleUpdateDocumentType = async () => {
    if (!documentId) return;
    try {
      const values = await typeForm.validateFields();
      setTypeSubmitting(true);
      await updateDocumentType(documentId, values.doc_type);
      message.success('文档类型已更新');
      setTypeModalOpen(false);
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error(err?.message || '更新文档类型失败');
    } finally {
      setTypeSubmitting(false);
    }
  };

  const loadSystemOptions = async () => {
    setSystemOptionsLoading(true);
    setSystemOptionsError(null);
    try {
      const options = await listSystemOptions();
      setSystemOptions(options);
    } catch (err) {
      setSystemOptionsError(getErrorMessage(err, '系统列表暂时无法加载，请重试。'));
      setSystemOptions([]);
    } finally {
      setSystemOptionsLoading(false);
    }
  };

  // 选目标系统后加载该系统文档（排除当前文档）
  const handleAssocSystemChange = (sysId: string) => {
    setAssocSystemId(sysId || undefined);
    addForm.setFieldsValue({ target_document_id: undefined });
    setDocOptions([]);
    setDocOptionsError(null);
    if (!sysId) return;
    setDocLoading(true);
    listDocuments(sysId, { per_page: 100 })
      .then((res) => setDocOptions(res.items.filter((d) => d.id !== documentId)))
      .catch((err) => {
        setDocOptionsError(getErrorMessage(err, '目标文档列表暂时无法加载，请重试。'));
        setDocOptions([]);
      })
      .finally(() => setDocLoading(false));
  };

  const retryDocOptions = () => {
    if (assocSystemId) handleAssocSystemChange(assocSystemId);
  };

  const docOptionsHelp = (() => {
    if (!assocSystemId) return '先选择目标系统，再选择需要补充为上下文的目标文档。';
    if (docLoading) return '正在加载该系统下可关联文档。';
    if (docOptionsError) return '目标文档列表加载失败，不能据此判断该系统没有可关联文档。';
    if (docOptions.length === 0) return '该系统当前没有其他可关联文档。';
    return `当前可选择 ${docOptions.length} 篇可关联文档。`;
  })();

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
        <Tag color={docTypeColorMap[type] || 'default'}>
          {docTypeLabelMap[type] || type}
        </Tag>
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
      render: (dir: string) => (dir === 'outgoing' ? '出站' : '入站'),
    },
  ];

  if (loading) {
    return (
      <PageShell>
        <div style={{ padding: 48, textAlign: 'center' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16, color: layoutTokens.textSecondary }}>加载中...</div>
        </div>
      </PageShell>
    );
  }

  if (loadError || !currentDocument) {
    return (
      <PageShell>
        <EmptyState
          title="文档不可用"
          description="当前文档可能已被删除，或暂时无法加载。"
          action={
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(returnUrl)}>
              {returnLabel}
            </Button>
          }
        />
      </PageShell>
    );
  }

  const docStatus = docStatusMap[currentDocument.status] || {
    label: currentDocument.status || '-',
    tone: 'default' as StatusTone,
  };
  const embeddingStatus = EMBEDDING_STATUS[currentDocument.embedding_status ?? ''] || {
    label: currentDocument.embedding_status || '-',
    tone: 'default' as StatusTone,
  };
  const directAssociations = associations?.direct ?? [];
  const indirectAssociations = associations?.indirect ?? [];
  const directAssociationCount = associations
    ? directAssociations.length
    : currentDocument.association_count ?? 0;
  const indirectAssociationCount = indirectAssociations.length;

  return (
    <PageShell>
      <PageHeader
        eyebrow="文档详情"
        title={currentDocument.title}
        description="确认资料类型、解析状态和关联上下游后，再发起用例生成。"
        meta={
          <Space size={8} wrap>
            <Link to="/systems">项目/系统</Link>
            <Text type="secondary">/</Text>
            {fromSearch ? (
              <>
                <Link to={searchReturnUrl}>全局搜索</Link>
                <Text type="secondary">/</Text>
              </>
            ) : knowledgeSystemId && (
              <>
                <Link to={returnUrl}>知识库</Link>
                <Text type="secondary">/</Text>
              </>
            )}
            <Text type="secondary">文档详情</Text>
            <StatusTag tone={docStatus.tone}>{docStatus.label}</StatusTag>
            <StatusTag tone={embeddingStatus.tone}>{embeddingStatus.label}</StatusTag>
          </Space>
        }
        actions={
          [
            <Button key="back" icon={<ArrowLeftOutlined />} onClick={() => navigate(returnUrl)}>
              {returnLabel}
            </Button>,
            <Button key="parse" icon={<FileSearchOutlined />} onClick={() => setParseOpen(true)}>
              解析详情
            </Button>,
            <Button key="type" icon={<EditOutlined />} onClick={openTypeModal}>
              修改类型
            </Button>,
            <Button key="cheat-sheet" icon={<ProfileOutlined />} onClick={() => setCheatSheetOpen(true)}>
              知识速查表
            </Button>,
            <Button
              key="generate"
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleGenerate}
              loading={generating}
            >
              生成测试用例
            </Button>,
          ]
        }
      />

      <MetricStrip
        items={[
          {
            key: 'type',
            label: '文档类型',
            value: docTypeLabelMap[currentDocument.doc_type] || currentDocument.doc_type,
            tone: 'primary',
          },
          {
            key: 'status',
            label: '导入状态',
            value: docStatus.label,
            tone: metricToneFromStatus(docStatus.tone),
          },
          {
            key: 'embedding',
            label: '嵌入状态',
            value: embeddingStatus.label,
            tone: metricToneFromStatus(embeddingStatus.tone),
          },
          {
            key: 'direct',
            label: '直接关联',
            value: directAssociationCount,
            tone: directAssociationCount > 0 ? 'success' : 'warning',
          },
          { key: 'indirect', label: '间接关联', value: indirectAssociationCount },
        ]}
      />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 12,
          marginBottom: 16,
          padding: 12,
          border: `1px solid ${layoutTokens.border}`,
          borderRadius: layoutTokens.radius,
          background: layoutTokens.surface,
        }}
      >
        {[
          ['1', '确认资料状态', '检查文档类型、导入状态和嵌入状态。'],
          ['2', '补齐关联资产', '关联技术文档、原型或测试规则，提升生成上下文。'],
          ['3', '生成并审查', '发起生成后进入批次工作台处理澄清、审核与落库。'],
        ].map(([step, title, desc]) => (
          <div key={step} style={{ display: 'flex', gap: 10, minWidth: 0 }}>
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 14,
                flexShrink: 0,
                display: 'grid',
                placeItems: 'center',
                background: layoutTokens.primarySoft,
                color: layoutTokens.primary,
                fontWeight: 700,
              }}
            >
              {step}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 650 }}>{title}</div>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {desc}
              </Text>
            </div>
          </div>
        ))}
      </div>

      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <div>
            <div style={{ fontWeight: 650 }}>文档概览</div>
            <Text type="secondary">用于判断这份资料是否已经具备生成用例的基础上下文。</Text>
          </div>
        </div>
        {currentDocument.doc_type === 'other' && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="这份历史资料仍标记为「其他」"
            description="如果它是 PRD、技术文档、测试规则或原型资料，请先修改类型，再用于生成或关联。"
            action={
              <Button size="small" icon={<EditOutlined />} onClick={openTypeModal}>
                标注类型
              </Button>
            }
          />
        )}
        <div style={fieldGridStyle}>
          <div>
            <Text type="secondary">标题</Text>
            <div style={{ marginTop: 4, fontWeight: 600, wordBreak: 'break-word' }}>
              {currentDocument.title}
            </div>
          </div>
          <div>
            <Text type="secondary">文档类型</Text>
            <div style={{ marginTop: 4 }}>
              <Tag color={docTypeColorMap[currentDocument.doc_type]}>
                {docTypeLabelMap[currentDocument.doc_type] || currentDocument.doc_type}
              </Tag>
              <Button type="link" size="small" onClick={openTypeModal} style={{ paddingInline: 8 }}>
                修改
              </Button>
            </div>
          </div>
          <div>
            <Text type="secondary">目录路径</Text>
            <div style={{ marginTop: 4, wordBreak: 'break-word' }}>
              {currentDocument.folder_path || '根目录'}
            </div>
          </div>
          <div>
            <Text type="secondary">更新时间</Text>
            <div style={{ marginTop: 4 }}>
              {new Date(currentDocument.updated_at).toLocaleString()}
            </div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <Text type="secondary">存储路径</Text>
            <div style={{ marginTop: 4, wordBreak: 'break-all' }}>
              <Text code>{currentDocument.storage_path}</Text>
            </div>
          </div>
        </div>
      </div>

      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>
          <div>
            <div style={{ fontWeight: 650 }}>关联文档</div>
            <Text type="secondary">直接关联会参与资料追溯；缺少技术文档、原型或测试规则时，先补关联再生成更稳。</Text>
          </div>
          <Button icon={<LinkOutlined />} onClick={openAddModal}>
            添加关联
          </Button>
        </div>
        <Spin spinning={assocLoading}>
          <Table
            columns={assocColumns}
            dataSource={directAssociations}
            rowKey="id"
            pagination={false}
            scroll={{ x: 520 }}
            locale={{
              emptyText: '暂无关联文档。可先关联技术文档、原型或测试规则，再发起生成。',
            }}
          />
        </Spin>
      </div>

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
            name="system_id"
            label="目标系统"
            rules={[{ required: true, message: '请选择系统' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择目标文档所属系统"
              onChange={handleAssocSystemChange}
              loading={systemOptionsLoading}
              status={systemOptionsError ? 'warning' : undefined}
              notFoundContent={systemOptionsError ? '系统列表加载失败' : '暂无系统'}
              options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
            />
          </Form.Item>
          {systemOptionsError && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="系统列表加载失败"
              description={`不能据此判断没有系统可关联。${systemOptionsError}`}
              action={
                <Button size="small" loading={systemOptionsLoading} onClick={loadSystemOptions}>
                  重试系统
                </Button>
              }
            />
          )}
          <Form.Item
            name="target_document_id"
            label="目标文档"
            rules={[{ required: true, message: '请选择目标文档' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="选择要关联的文档"
              loading={docLoading}
              disabled={!assocSystemId || Boolean(docOptionsError && !docLoading)}
              status={docOptionsError ? 'warning' : undefined}
              notFoundContent={docOptionsError ? '目标文档列表加载失败' : '暂无可关联文档'}
              options={docOptions.map((d) => ({ value: d.id, label: d.title }))}
            />
          </Form.Item>
          {docOptionsError ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="目标文档列表加载失败"
              description={`${docOptionsHelp} ${docOptionsError}`}
              action={
                <Button size="small" loading={docLoading} onClick={retryDocOptions}>
                  重试文档
                </Button>
              }
            />
          ) : (
            <Text type="secondary" style={{ display: 'block', marginTop: -12, marginBottom: 16, fontSize: 12 }}>
              {docOptionsHelp}
            </Text>
          )}
          <Form.Item
            name="relation_type"
            label="关联类型"
            rules={[{ required: true, message: '请选择关联类型' }]}
          >
            <Select showSearch optionFilterProp="children" placeholder="请选择关联类型">
              {Object.entries(relationTypeLabels).map(([value, label]) => (
                <Select.Option key={value} value={value}>
                  {label}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="修改文档类型"
        open={typeModalOpen}
        onCancel={() => setTypeModalOpen(false)}
        onOk={handleUpdateDocumentType}
        confirmLoading={typeSubmitting}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="文档类型会影响资料追溯和生成前判断"
          description="这里只修改类型标注，不会重新解析文档，也不会自动重新生成用例。"
        />
        <Form form={typeForm} layout="vertical">
          <Form.Item name="doc_type" label="文档类型" rules={[{ required: true, message: '请选择文档类型' }]}>
            <Select
              optionLabelProp="label"
              options={docTypeOptions.map((option) => ({
                value: option.value,
                label: option.label,
                title: option.description,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <CheatSheetDrawer
        documentId={documentId ?? null}
        open={cheatSheetOpen}
        onClose={() => setCheatSheetOpen(false)}
      />

      <ParseResultDrawer
        documentId={documentId ?? null}
        open={parseOpen}
        onClose={() => setParseOpen(false)}
      />
    </PageShell>
  );
};

export default DocumentDetailPage;
