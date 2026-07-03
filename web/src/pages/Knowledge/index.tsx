import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Button,
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
import type { Document, DocType, DocStatus } from '../../types';
import type { ColumnsType } from 'antd/es/table';
import type { DataNode } from 'antd/es/tree';
import {
  collectTreeKeys,
  collectTreeKeysByDepth,
  filterTreeDataByKeyword,
} from '../../components/treeUtils';

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

const docTypeOptions: Array<{ label: string; value: DocType }> = [
  { label: docTypeLabelMap.prd, value: 'prd' },
  { label: docTypeLabelMap.tech_doc, value: 'tech_doc' },
  { label: docTypeLabelMap.test_rule, value: 'test_rule' },
  { label: docTypeLabelMap.prototype, value: 'prototype' },
  { label: docTypeLabelMap.bug_record, value: 'bug_record' },
  { label: docTypeLabelMap.test_case, value: 'test_case' },
  { label: docTypeLabelMap.other, value: 'other' },
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
    uploadResult,
    isUploading,
    clearUploadResult,
    fetchCurrentSystem,
    currentSystem,
  } = useKnowledgeStore();

  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [resultModalOpen, setResultModalOpen] = useState(false);
  const [selectedDocType, setSelectedDocType] = useState<DocType>('prd');
  const [folderKeyword, setFolderKeyword] = useState('');
  const [expandedFolderKeys, setExpandedFolderKeys] = useState<React.Key[]>(['__all__']);

  // 累积一次选择/拖拽的多个文件（文件夹会触发多次 beforeUpload），合并为一个上传请求
  const pendingFilesRef = useRef<File[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!systemId) return;
    fetchCurrentSystem(systemId);
    fetchDocuments(systemId, { page: 1, per_page: documentsPerPage });
  }, [systemId]);

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

  const handleUpload = async (files: File[]) => {
    if (!systemId || files.length === 0) return;
    try {
      await uploadDocuments(systemId, files, selectedDocType);
      // 上传成功后刷新文档列表
      fetchDocuments(systemId, { page: 1, per_page: documentsPerPage });
    } catch (err: any) {
      message.error(err?.message || '上传失败');
    }
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

  const columns: ColumnsType<Document> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
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
    <div style={{ padding: 24 }}>
      <Title level={3}>{currentSystem?.name || '系统'} - 知识库</Title>

      <Space align="center" style={{ marginBottom: 12 }} wrap>
        <Text strong>上传文档类型</Text>
        <Select<DocType>
          value={selectedDocType}
          onChange={setSelectedDocType}
          options={docTypeOptions}
          style={{ width: 160 }}
          disabled={isUploading}
        />
        <Text type="secondary">本次上传会按所选类型入库，默认 PRD。</Text>
      </Space>

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
          当前类型：{docTypeLabelMap[selectedDocType]}
        </p>
      </Dragger>

      <Space style={{ marginBottom: 24 }}>
        <Upload
          directory
          showUploadList={false}
          beforeUpload={collectFile}
          disabled={isUploading}
        >
          <Button icon={<FolderOpenOutlined />} disabled={isUploading}>
            上传文件夹（含图片的 PRD 目录）
          </Button>
        </Upload>
        <Text type="secondary">
          文件夹内的 .md 与图片会按相对路径一并上传，图片引用可正常解析
        </Text>
      </Space>

      <div style={{ display: 'flex', gap: 24 }}>
        {/* 左侧文档树 */}
        <div style={{ width: 240, flexShrink: 0 }}>
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

        {/* 右侧文档列表 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <Spin spinning={documentsLoading}>
            <Table<Document>
              columns={columns}
              dataSource={filteredDocuments}
              rowKey="id"
              pagination={false}
              onRow={(record) => ({
                onClick: () => navigate(`/documents/${record.id}`),
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
      </div>

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
                <ul>
                  {uploadResult.uploaded.map((item) => (
                    <li key={item.id}>
                      {item.title} <Tag color={docTypeColorMap[item.doc_type]}>{docTypeLabelMap[item.doc_type]}</Tag>
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
    </div>
  );
};

export default KnowledgePage;
