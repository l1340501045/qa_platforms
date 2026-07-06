import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
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
  Tree,
  Typography,
  Upload,
} from 'antd';
import { FolderOpenOutlined, InboxOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { useKnowledgeStore } from '../../stores/knowledgeStore';
import { triggerGeneration } from '../../services/batchApi';
import type { Document, DocType, DocStatus } from '../../types';
import type { ColumnsType } from 'antd/es/table';
import type { DataNode } from 'antd/es/tree';
import {
  collectTreeKeys,
  collectTreeKeysByDepth,
  filterTreeDataByKeyword,
} from '../../components/treeUtils';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import SplitPane from '../../components/layout/SplitPane';
import { layoutTokens } from '../../components/layout/tokens';
import { buildKnowledgeBatchUrl } from '../../utils/batchReturn';

const { Dragger } = Upload;
const { Title, Text } = Typography;

const docTypeColorMap: Record<DocType, string> = {
  prd: 'blue',
  tech_doc: 'green',
  test_rule: 'orange',
  test_case: 'purple',
  bug_record: 'red',
  prototype: 'cyan',
  other: 'default',
};

const docTypeLabelMap: Record<DocType, string> = {
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

const docStatusMap: Record<DocStatus, { status: 'processing' | 'success' | 'error' | 'default'; text: string }> = {
  uploading: { status: 'processing', text: '上传中' },
  uploaded: { status: 'success', text: '已上传' },
  importing: { status: 'processing', text: '导入中' },
  imported: { status: 'success', text: '已导入' },
  import_failed: { status: 'error', text: '导入失败' },
};

/** 根据 folder_path 构建树结构 */
function buildFolderTree(documents: Document[]): DataNode[] {
  const folderSet = new Set<string>();
  documents.forEach((doc) => {
    if (doc.folder_path) {
      const parts = doc.folder_path.split('/').filter(Boolean);
      let current = '';
      parts.forEach((part) => {
        current = current ? `${current}/${part}` : part;
        folderSet.add(current);
      });
    }
  });

  const root: DataNode[] = [];
  const nodeMap: Record<string, DataNode> = {};

  // 添加根节点
  root.push({ title: '全部文档', key: '__all__', children: [] });

  const sortedFolders = Array.from(folderSet).sort();
  sortedFolders.forEach((folder) => {
    const parts = folder.split('/');
    const node: DataNode = {
      title: parts[parts.length - 1],
      key: folder,
      children: [],
    };
    nodeMap[folder] = node;

    if (parts.length === 1) {
      root[0].children!.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join('/');
      if (nodeMap[parentPath]) {
        nodeMap[parentPath].children!.push(node);
      }
    }
  });

  return root;
}

function buildKnowledgeDocumentUrl(documentId: string, systemId?: string): string {
  const params = new URLSearchParams({ from: 'knowledge' });
  if (systemId) params.set('system_id', systemId);
  return `/documents/${documentId}?${params.toString()}`;
}

const KnowledgePage: React.FC = () => {
  const { systemId } = useParams<{ systemId: string }>();
  const navigate = useNavigate();

  const {
    documents,
    documentsTotal,
    documentsPage,
    documentsPerPage,
    documentsLoading,
    fetchDocuments,
    uploadDocuments,
    updateDocumentType,
    uploadResult,
    isUploading,
    clearUploadResult,
    fetchCurrentSystem,
    currentSystem,
  } = useKnowledgeStore();

  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [resultModalOpen, setResultModalOpen] = useState(false);
  const [typeForm] = Form.useForm<{ doc_type: DocType }>();
  const [relabelDoc, setRelabelDoc] = useState<Document | null>(null);
  const [relabelSubmitting, setRelabelSubmitting] = useState(false);
  const [selectedDocType, setSelectedDocType] = useState<DocType>('prd');
  const [folderKeyword, setFolderKeyword] = useState('');
  const [expandedFolderKeys, setExpandedFolderKeys] = useState<React.Key[]>(['__all__']);
  const [generatingDocId, setGeneratingDocId] = useState<string | null>(null);

  // 累积一次选择/拖拽的多个文件（文件夹会触发多次 beforeUpload），合并为一个上传请求
  const pendingFilesRef = useRef<File[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadInitialKnowledge = useCallback(() => {
    if (!systemId) return;
    fetchCurrentSystem(systemId);
    fetchDocuments(systemId, { page: 1, per_page: documentsPerPage });
  }, [documentsPerPage, fetchCurrentSystem, fetchDocuments, systemId]);

  useEffect(() => {
    loadInitialKnowledge();
  }, [loadInitialKnowledge]);

  useEffect(() => {
    if (uploadResult) {
      setResultModalOpen(true);
    }
  }, [uploadResult]);

  const treeData = useMemo(() => buildFolderTree(documents), [documents]);
  const visibleTreeData = useMemo(
    () => filterTreeDataByKeyword(treeData, folderKeyword),
    [treeData, folderKeyword],
  );
  const allFolderKeys = useMemo(() => collectTreeKeys(treeData), [treeData]);
  const defaultFolderKeys = useMemo(() => collectTreeKeysByDepth(treeData, 0), [treeData]);

  useEffect(() => {
    if (folderKeyword.trim()) {
      setExpandedFolderKeys(collectTreeKeys(visibleTreeData));
      return;
    }
    setExpandedFolderKeys(defaultFolderKeys);
  }, [folderKeyword, visibleTreeData, defaultFolderKeys]);

  const filteredDocuments = useMemo(() => {
    if (!selectedFolder || selectedFolder === '__all__') return documents;
    return documents.filter(
      (doc) => doc.folder_path && doc.folder_path.startsWith(selectedFolder),
    );
  }, [documents, selectedFolder]);

  const handlePageChange = (page: number, pageSize: number) => {
    if (!systemId) return;
    fetchDocuments(systemId, { page, per_page: pageSize });
  };

  const selectedDocTypeHelp = docTypeHelpMap[selectedDocType];

  const performUpload = async (files: File[], docType: DocType) => {
    if (!systemId || files.length === 0) return;
    try {
      await uploadDocuments(systemId, files, docType);
      // 上传成功后刷新文档列表
      fetchDocuments(systemId, { page: 1, per_page: documentsPerPage });
    } catch (err: any) {
      message.error(err?.message || '上传失败');
    }
  };

  const handleUpload = async (files: File[]) => {
    if (!systemId || files.length === 0) return;
    const uploadDocType = selectedDocType;
    if (uploadDocType === 'other') {
      Modal.confirm({
        title: '确认以「其他」类型入库？',
        content: '「其他」类型不会作为 PRD、技术文档或测试规则参与自动关联。若这份资料会用于生成测试用例，建议先选择更准确的类型。',
        okText: '继续上传',
        cancelText: '返回选择类型',
        onOk: () => performUpload(files, uploadDocType),
      });
      return;
    }
    await performUpload(files, uploadDocType);
  };

  // beforeUpload 收集文件并防止 antd 自动上传；短暂去抖后合并为一个请求
  const collectFile = (file: File): boolean => {
    pendingFilesRef.current.push(file);
    if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
    flushTimerRef.current = setTimeout(() => {
      const batch = pendingFilesRef.current;
      pendingFilesRef.current = [];
      handleUpload(batch);
    }, 150);
    return false;
  };

  const handleCloseResultModal = () => {
    setResultModalOpen(false);
    clearUploadResult();
  };

  const confirmGenerateDocument = (documentId: string, title: string) => {
    Modal.confirm({
      title: '生成测试用例',
      content: `将基于「${title}」创建一个新的生成批次。生成开始后会进入批次工作台查看进度。`,
      okText: '开始生成',
      cancelText: '取消',
      onOk: async () => {
        setGeneratingDocId(documentId);
        try {
          const res = await triggerGeneration(documentId);
          message.success('生成任务已创建');
          handleCloseResultModal();
          navigate(buildKnowledgeBatchUrl(res.batch_id, systemId));
        } catch (err: any) {
          message.error(err?.message || '生成失败');
        } finally {
          setGeneratingDocId(null);
        }
      },
    });
  };

  const openRelabelModal = (doc: Document, event?: React.MouseEvent) => {
    event?.stopPropagation();
    setRelabelDoc(doc);
  };

  const handleRelabelDocument = async () => {
    if (!relabelDoc) return;
    try {
      const values = await typeForm.validateFields();
      setRelabelSubmitting(true);
      await updateDocumentType(relabelDoc.id, values.doc_type);
      message.success('文档类型已更新');
      setRelabelDoc(null);
    } catch (err: any) {
      if (err?.errorFields) return;
      message.error(err?.message || '更新文档类型失败');
    } finally {
      setRelabelSubmitting(false);
    }
  };

  const handleGenerateDocument = (doc: Document, event?: React.MouseEvent) => {
    event?.stopPropagation();
    confirmGenerateDocument(doc.id, doc.title);
  };

  const handleOpenUploadedDocument = (documentId: string) => {
    handleCloseResultModal();
    navigate(buildKnowledgeDocumentUrl(documentId, systemId));
  };

  const columns: ColumnsType<Document> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 320,
      render: (title: string, record) => (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Text strong style={{ lineHeight: 1.5 }}>
            {title}
          </Text>
          <Space size={8} wrap>
            <Button
              type="link"
              size="small"
              loading={generatingDocId === record.id}
              onClick={(event) => handleGenerateDocument(record, event)}
              style={{ paddingInline: 0 }}
            >
              生成用例
            </Button>
            {record.doc_type === 'other' && (
              <Button
                type="link"
                size="small"
                onClick={(event) => openRelabelModal(record, event)}
                style={{ paddingInline: 0 }}
              >
                标注类型
              </Button>
            )}
            <Button
              type="link"
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                navigate(buildKnowledgeDocumentUrl(record.id, systemId));
              }}
              style={{ paddingInline: 0 }}
            >
              查看详情
            </Button>
          </Space>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'doc_type',
      key: 'doc_type',
      width: 100,
      render: (type: DocType) => (
        <Tag color={docTypeColorMap[type]}>{docTypeLabelMap[type] || type}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: DocStatus) => {
        const info = docStatusMap[status] || { status: 'default', text: status };
        return <Badge status={info.status} text={info.text} />;
      },
    },
    {
      title: '关联数',
      dataIndex: 'association_count',
      key: 'association_count',
      width: 80,
      render: (count?: number) => count ?? 0,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (val: string) => new Date(val).toLocaleString(),
    },
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow="知识库"
        title={currentSystem?.name || '系统'}
        description="上传 PRD、技术文档、测试规则和原型图片资产。生成前请先确认资料类型和目录结构。"
      />

      <MetricStrip
        items={[
          { key: 'docs', label: '文档总数', value: documentsTotal },
          { key: 'visible', label: '当前筛选可见', value: filteredDocuments.length, tone: 'primary' },
          { key: 'folders', label: '文件夹节点', value: Math.max(allFolderKeys.length - 1, 0) },
          { key: 'type', label: '本次上传类型', value: docTypeLabelMap[selectedDocType] },
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
          ['1', '上传资料', '选择文档类型后上传 PRD、技术文档或规则资料。'],
          ['2', '生成批次', '在文档列表点击“生成用例”，系统会创建批次。'],
          ['3', '进入审查', '生成后进入批次工作台，处理澄清、审核与落库。'],
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

      <div
        style={{
          marginBottom: 16,
          padding: 16,
          border: `1px solid ${layoutTokens.border}`,
          borderRadius: layoutTokens.radius,
          background: layoutTokens.surface,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            gap: 12,
            alignItems: 'flex-start',
            marginBottom: 12,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <Text strong>上传前先选择资料类型</Text>
            <Text
              style={{
                display: 'block',
                marginTop: 4,
                color: layoutTokens.textSecondary,
              }}
            >
              类型会影响后续自动关联、生成依据和资产追溯；同一批上传文件会统一按当前类型入库。
            </Text>
          </div>
          <Tag color={docTypeColorMap[selectedDocType]} style={{ marginInlineEnd: 0 }}>
            本次上传：{docTypeLabelMap[selectedDocType]}
          </Tag>
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(220px, 280px) minmax(260px, 1fr)',
            gap: 12,
            alignItems: 'stretch',
          }}
        >
          <Select<DocType>
            value={selectedDocType}
            onChange={setSelectedDocType}
            optionFilterProp="label"
            options={docTypeOptions}
            disabled={isUploading}
            aria-label="上传文档类型"
          />
          <div
            style={{
              minHeight: 40,
              padding: '8px 12px',
              border: `1px solid ${layoutTokens.borderSubtle}`,
              borderRadius: layoutTokens.radius,
              background: selectedDocType === 'other' ? layoutTokens.warningSoft : layoutTokens.surfaceMuted,
              color: selectedDocType === 'other' ? layoutTokens.warning : layoutTokens.textSecondary,
            }}
          >
            {selectedDocTypeHelp}
          </div>
        </div>
        {selectedDocType === 'other' && (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 12 }}
            message="仅在无法归类时使用「其他」"
            description="如果资料是需求、技术说明、测试规则、原型或历史缺陷，请选择对应类型；错误归类会降低后续生成和追溯质量。"
          />
        )}
      </div>

      <Dragger
        accept=".zip,.md,.png,.jpg,.jpeg,.gif,.webp,.bmp,.svg"
        multiple
        showUploadList={false}
        beforeUpload={collectFile}
        disabled={isUploading}
        style={{ marginBottom: 12 }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">
          {isUploading ? '上传中...' : '点击或拖拽文件到此区域上传'}
        </p>
        <p className="ant-upload-hint">
          支持 .zip 压缩包、单个/多个 .md 文件，以及图片文件（可多选）
        </p>
        <p className="ant-upload-hint">
          本次将以「{docTypeLabelMap[selectedDocType]}」入库：{selectedDocTypeHelp}
        </p>
      </Dragger>

      <Space style={{ marginBottom: 20 }} wrap>
        <Upload
          directory
          showUploadList={false}
          beforeUpload={collectFile}
          disabled={isUploading}
        >
          <Button icon={<FolderOpenOutlined />} disabled={isUploading}>
            上传文件夹（按「{docTypeLabelMap[selectedDocType]}」入库）
          </Button>
        </Upload>
        <Text type="secondary">
          文件夹内的 .md 与图片会按相对路径一并上传，图片引用可正常解析
        </Text>
      </Space>

      <SplitPane
        left={
          <div
            style={{
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              padding: 12,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 10 }}>文档目录</div>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Input.Search
              allowClear
              placeholder="搜索文件夹"
              value={folderKeyword}
              onChange={(e) => setFolderKeyword(e.target.value)}
            />
            <Space size={8} wrap>
              <Button size="small" onClick={() => setExpandedFolderKeys(allFolderKeys)}>
                展开全部
              </Button>
              <Button size="small" onClick={() => setExpandedFolderKeys([])}>
                收起全部
              </Button>
            </Space>
            <div style={{ maxHeight: 520, overflow: 'auto', paddingRight: 4 }}>
              <Tree
                treeData={visibleTreeData}
                expandedKeys={expandedFolderKeys}
                selectedKeys={selectedFolder ? [selectedFolder] : []}
                onExpand={(keys) => setExpandedFolderKeys(keys)}
                onSelect={(keys) => {
                  setSelectedFolder(keys.length > 0 ? (keys[0] as string) : null);
                }}
              />
            </div>
          </Space>
          </div>
        }
        right={
          <div
            style={{
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              padding: 12,
            }}
          >
          <div style={{ fontWeight: 600, marginBottom: 10 }}>文档列表</div>
          <Spin spinning={documentsLoading}>
            <Table<Document>
              columns={columns}
              dataSource={filteredDocuments}
              rowKey="id"
              pagination={false}
              scroll={{ x: 760 }}
              onRow={(record) => ({
                onClick: () => navigate(buildKnowledgeDocumentUrl(record.id, systemId)),
                style: { cursor: 'pointer' },
              })}
            />
          </Spin>

          {documentsTotal > 0 && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
              <Pagination
                current={documentsPage}
                pageSize={documentsPerPage}
                total={documentsTotal}
                onChange={handlePageChange}
                showSizeChanger
                showTotal={(total) => `共 ${total} 篇文档`}
              />
            </div>
          )}
          </div>
        }
      />

      {/* 上传结果 Modal */}
      <Modal
        title="上传结果"
        open={resultModalOpen}
        onCancel={handleCloseResultModal}
        onOk={handleCloseResultModal}
        footer={null}
      >
        {uploadResult && (
          <div>
            <p>
              <Text strong>总文件数：</Text>{uploadResult.summary.total_files}
            </p>
            <p>
              <Tag color="green">成功上传：{uploadResult.summary.uploaded_count}</Tag>
              <Tag color="orange">跳过：{uploadResult.summary.skipped_count}</Tag>
              <Tag color="red">失败：{uploadResult.summary.failed_count}</Tag>
              {(uploadResult.summary.image_count ?? 0) > 0 && (
                <Tag color="blue">图片资产：{uploadResult.summary.image_count}</Tag>
              )}
            </p>

            {uploadResult.uploaded.length > 0 && (
              <>
                <Title level={5}>已上传</Title>
                <ul style={{ paddingLeft: 18 }}>
                  {uploadResult.uploaded.map((item) => (
                    <li key={item.id} style={{ marginBottom: 8 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: 12,
                          alignItems: 'center',
                          flexWrap: 'wrap',
                        }}
                      >
                        <span style={{ flex: '1 1 260px', minWidth: 0, wordBreak: 'break-word' }}>
                          {item.title}{' '}
                          <Tag color={docTypeColorMap[item.doc_type]}>{docTypeLabelMap[item.doc_type]}</Tag>
                        </span>
                        <Space size={8} wrap>
                          <Button type="link" size="small" onClick={() => handleOpenUploadedDocument(item.id)}>
                            查看详情
                          </Button>
                          <Button
                            type="link"
                            size="small"
                            loading={generatingDocId === item.id}
                            onClick={() => confirmGenerateDocument(item.id, item.title)}
                          >
                            生成用例
                          </Button>
                        </Space>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {uploadResult.skipped.length > 0 && (
              <>
                <Title level={5}>已跳过</Title>
                <ul>
                  {uploadResult.skipped.map((item, idx) => (
                    <li key={idx}>
                      {item.filename} - {item.reason}
                    </li>
                  ))}
                </ul>
              </>
            )}

            {uploadResult.failed.length > 0 && (
              <>
                <Title level={5}>失败</Title>
                <ul>
                  {uploadResult.failed.map((item, idx) => (
                    <li key={idx}>
                      {item.filename} - {item.error}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </Modal>

      <Modal
        title="标注文档类型"
        open={Boolean(relabelDoc)}
        onCancel={() => setRelabelDoc(null)}
        onOk={handleRelabelDocument}
        confirmLoading={relabelSubmitting}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="历史文档仍标记为「其他」"
          description="请选择更准确的资料类型。这里只修改类型标注，不会重新解析文档，也不会自动重新生成用例。"
        />
        <Form
          key={relabelDoc ? `${relabelDoc.id}-${relabelDoc.doc_type}` : 'relabel-doc-type'}
          form={typeForm}
          initialValues={{ doc_type: relabelDoc?.doc_type === 'other' ? 'prd' : relabelDoc?.doc_type }}
          layout="vertical"
        >
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
    </PageShell>
  );
};

export default KnowledgePage;
