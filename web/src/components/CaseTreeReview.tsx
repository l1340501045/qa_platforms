/**
 * 用例审核树 — 工作台用例区
 * 左侧「文档 → 业务模块 → 分支」树，右侧选中节点的用例表（带审核操作）。
 * 复用系统级 case-tree 接口（按 batch_id 取当前批次），支持：
 *  - 行内/抽屉审核（确认 / 需修改 / 删除）
 *  - 审核或编辑完自动跳「当前列表内下一条」
 *  - iteration>1 的「已重写」标记
 *  - 标题模糊搜索（前端跨模块过滤）
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Spin,
  Table,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd';
import { AppstoreOutlined, FileTextOutlined, FolderOutlined } from '@ant-design/icons';
import type { DataNode } from 'antd/es/tree';
import type { ColumnsType } from 'antd/es/table';

import { getCaseTree } from '../services/systemApi';
import CaseDetailDrawer from './CaseDetailDrawer';
import type {
  CaseBucket,
  CaseTreeCase,
  CaseTreeDocument,
  CaseVerdict,
  ReviewIssueType,
  ReviewStatus,
} from '../types';

const { Text } = Typography;
const { TextArea } = Input;

type ReviewAction = 'confirmed' | 'needs_modification' | 'deleted';

const PRIORITY_COLOR: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
};

const REVIEW_TAG: Record<ReviewStatus, { color: string; label: string }> = {
  pending: { color: 'default', label: '待审' },
  confirmed: { color: 'green', label: '已确认' },
  needs_modification: { color: 'orange', label: '需修改' },
  deleted: { color: 'red', label: '已删除' },
};

const BUCKET_TAG: Record<string, { color: string; label: string }> = {
  main: { color: 'green', label: '主集' },
  needs_spec: { color: 'gold', label: '待澄清' },
  to_fix: { color: 'red', label: '待修正' },
};

const VERDICT_COLOR: Record<string, string> = {
  grounded: 'green',
  ungrounded: 'orange',
  undefined: 'gold',
  conflict: 'red',
};

const REVIEW_ISSUE_TAG: Record<ReviewIssueType, { color: string; label: string }> = {
  case_wrong: { color: 'red', label: '用例错' },
  prd_conflict: { color: 'purple', label: 'PRD冲突' },
  verify_uncertain: { color: 'blue', label: '核验不确定' },
};

function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

function allCasesFromTree(tree: CaseTreeDocument[]): CaseTreeCase[] {
  return tree.flatMap((doc) => doc.modules.flatMap((m) => m.cases));
}

function casesFromDoc(doc: CaseTreeDocument): CaseTreeCase[] {
  return doc.modules.flatMap((m) => m.cases);
}

/** 局部更新树中某条用例（审核后改 review_status，不重新拉树，保持列表稳定） */
function patchCaseInTree(
  tree: CaseTreeDocument[],
  caseId: string,
  patch: Partial<CaseTreeCase>,
): CaseTreeDocument[] {
  return tree.map((doc) => ({
    ...doc,
    modules: doc.modules.map((m) => ({
      ...m,
      cases: m.cases.map((c) => (c.id === caseId ? { ...c, ...patch } : c)),
      branches: m.branches?.map((b) => ({
        ...b,
        cases: b.cases.map((c) => (c.id === caseId ? { ...c, ...patch } : c)),
      })),
    })),
  }));
}

function branchPathKey(branchPath: string[]): string {
  return branchPath.join('/');
}

function encodeTreePart(value: string): string {
  return encodeURIComponent(value);
}

function decodeTreePart(value: string): string {
  return decodeURIComponent(value);
}

type SelectedNode =
  | { type: 'all' }
  | { type: 'doc'; docId: string }
  | { type: 'module'; docId: string; moduleName: string }
  | { type: 'branch'; docId: string; moduleName: string; branchPathKey: string };

interface CaseTreeReviewProps {
  batchId: string;
  systemId?: string;
  /** Review 状态筛选（传给后端 case-tree） */
  reviewFilter?: ReviewStatus;
  /** 质量桶筛选（传给后端 case-tree） */
  bucketFilter?: CaseBucket;
  /** Verdict 筛选（传给后端 case-tree） */
  verdictFilter?: CaseVerdict;
  /** 审查诊断类型筛选（传给后端 case-tree） */
  reviewIssueTypeFilter?: ReviewIssueType;
  /** 标题关键词（前端跨模块过滤） */
  searchKeyword?: string;
  /** 是否启用审核/编辑/重写（pending_review / reviewing 时为 true） */
  editable?: boolean;
  /** 审核回调（父级调 store.reviewCase 落库） */
  onReview: (caseId: string, status: ReviewAction, comment?: string) => Promise<void>;
  /** 全部用例变化（供父级「触发迭代」统计 needs_modification） */
  onAllCasesChange?: (cases: CaseTreeCase[]) => void;
  /** 父级触发重新拉树（如迭代后） */
  reloadSignal?: number;
}

const CaseTreeReview: React.FC<CaseTreeReviewProps> = ({
  batchId,
  systemId,
  reviewFilter,
  bucketFilter,
  verdictFilter,
  reviewIssueTypeFilter,
  searchKeyword,
  editable = false,
  onReview,
  onAllCasesChange,
  reloadSignal,
}) => {
  const [treeData, setTreeData] = useState<CaseTreeDocument[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<SelectedNode>({ type: 'all' });
  const [detailCaseId, setDetailCaseId] = useState<string | null>(null);

  const [modifyOpen, setModifyOpen] = useState(false);
  const [modifyCaseId, setModifyCaseId] = useState<string | null>(null);
  const [modifyComment, setModifyComment] = useState('');

  // ─── 加载树 ───
  const loadTree = useCallback(async () => {
    if (!systemId || !batchId) return;
    setTreeLoading(true);
    try {
      const data = await getCaseTree(systemId, {
        batch_id: batchId,
        review_status: reviewFilter,
        bucket: bucketFilter,
        verdict: verdictFilter,
        review_issue_type: reviewIssueTypeFilter,
      });
      setTreeData(data);
    } catch {
      message.error('加载用例树失败');
    } finally {
      setTreeLoading(false);
    }
  }, [systemId, batchId, reviewFilter, bucketFilter, verdictFilter, reviewIssueTypeFilter]);

  useEffect(() => {
    loadTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadTree, reloadSignal]);

  useEffect(() => {
    onAllCasesChange?.(allCasesFromTree(treeData));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [treeData]);

  // ─── Ant Tree 数据（文档 → 业务模块 → 分支） ───
  const antTreeData: DataNode[] = useMemo(() => {
    if (treeData.length === 0) return [];
    const total = allCasesFromTree(treeData).length;
    const docNodes: DataNode[] = treeData.map((doc) => ({
      key: `doc::${doc.document_id}`,
      title: (
        <span>
          <FileTextOutlined style={{ marginRight: 4 }} />
          {doc.document_title}
          <Tag style={{ marginLeft: 8 }} color="blue">
            {casesFromDoc(doc).length}
          </Tag>
        </span>
      ),
      children: doc.modules.map((mod) => {
        const branchNodes: DataNode[] = (mod.branches || []).map((branch) => {
          const key = branchPathKey(branch.branch_path);
          return {
            key: `branch::${doc.document_id}::${encodeTreePart(mod.module_name)}::${encodeTreePart(key)}`,
            title: (
              <span>
                <FolderOutlined style={{ marginRight: 4, color: '#8c8c8c' }} />
                {branch.branch_name}
                <Tag style={{ marginLeft: 8 }}>{branch.case_count}</Tag>
              </span>
            ),
            isLeaf: true,
          };
        });
        return {
          key: `module::${doc.document_id}::${encodeTreePart(mod.module_name)}`,
          title: (
            <span>
              <AppstoreOutlined style={{ marginRight: 4, color: '#8c8c8c' }} />
              {mod.module_name}
              <Tag style={{ marginLeft: 8 }}>{mod.case_count}</Tag>
            </span>
          ),
          children: branchNodes.length > 0 ? branchNodes : undefined,
          isLeaf: branchNodes.length === 0,
        };
      }),
    }));
    return [
      {
        key: '__root__',
        title: (
          <span>
            <FolderOutlined style={{ marginRight: 4 }} />
            全部模块
            <Tag style={{ marginLeft: 8 }}>{total}</Tag>
          </span>
        ),
        children: docNodes,
      },
    ];
  }, [treeData]);

  // ─── 当前列表（选中节点 + 标题搜索） ───
  const selectedCases: CaseTreeCase[] = useMemo(() => {
    const kw = (searchKeyword || '').trim();
    if (kw) {
      // 搜索时跨全部模块过滤
      return allCasesFromTree(treeData).filter((c) => c.title.includes(kw));
    }
    switch (selectedNode.type) {
      case 'all':
        return allCasesFromTree(treeData);
      case 'doc': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        return doc ? casesFromDoc(doc) : [];
      }
      case 'module': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        const mod = doc?.modules.find((m) => m.module_name === selectedNode.moduleName);
        return mod?.cases || [];
      }
      case 'branch': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        const mod = doc?.modules.find((m) => m.module_name === selectedNode.moduleName);
        const branch = mod?.branches?.find((b) => branchPathKey(b.branch_path) === selectedNode.branchPathKey);
        return branch?.cases || [];
      }
    }
  }, [treeData, selectedNode, searchKeyword]);

  const listTitle = useMemo(() => {
    if ((searchKeyword || '').trim()) return `搜索「${searchKeyword!.trim()}」`;
    switch (selectedNode.type) {
      case 'all':
        return '全部用例';
      case 'doc':
        return treeData.find((d) => String(d.document_id) === selectedNode.docId)?.document_title || '文档用例';
      case 'module':
        return selectedNode.moduleName;
      case 'branch':
        return selectedNode.branchPathKey;
    }
  }, [selectedNode, searchKeyword, treeData]);

  // ─── 审核（落库 + 局部更新树） ───
  const applyReview = useCallback(
    async (caseId: string, status: ReviewAction, comment?: string) => {
      await onReview(caseId, status, comment);
      setTreeData((prev) => patchCaseInTree(prev, caseId, { review_status: status }));
    },
    [onReview],
  );

  // ─── 跳到当前列表内下一条 ───
  const handleRequestNext = useCallback(() => {
    const idx = selectedCases.findIndex((c) => c.id === detailCaseId);
    if (idx >= 0 && idx < selectedCases.length - 1) {
      setDetailCaseId(selectedCases[idx + 1].id);
    } else {
      setDetailCaseId(null);
      message.success('已审完当前列表最后一条');
    }
  }, [selectedCases, detailCaseId]);

  const handleConfirm = useCallback(
    async (id: string) => {
      await applyReview(id, 'confirmed');
      message.success('已确认');
    },
    [applyReview],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      await applyReview(id, 'deleted');
      message.success('已删除');
    },
    [applyReview],
  );

  const openModify = useCallback((id: string) => {
    setModifyCaseId(id);
    setModifyComment('');
    setModifyOpen(true);
  }, []);

  const submitModify = useCallback(async () => {
    if (!modifyCaseId) return;
    if (!modifyComment.trim()) {
      message.warning('请输入修改意见');
      return;
    }
    await applyReview(modifyCaseId, 'needs_modification', modifyComment.trim());
    message.success('已标记需修改');
    setModifyOpen(false);
  }, [modifyCaseId, modifyComment, applyReview]);

  const handleTreeSelect = (keys: React.Key[]) => {
    if (keys.length === 0 || keys[0] === '__root__') {
      setSelectedNode({ type: 'all' });
      return;
    }
    const key = keys[0] as string;
    if (key.startsWith('doc::')) {
      setSelectedNode({ type: 'doc', docId: key.replace('doc::', '') });
    } else if (key.startsWith('module::')) {
      const parts = key.replace('module::', '').split('::');
      setSelectedNode({ type: 'module', docId: parts[0], moduleName: decodeTreePart(parts[1]) });
    } else if (key.startsWith('branch::')) {
      const parts = key.replace('branch::', '').split('::');
      setSelectedNode({
        type: 'branch',
        docId: parts[0],
        moduleName: decodeTreePart(parts[1]),
        branchPathKey: decodeTreePart(parts[2]),
      });
    }
  };

  const columns: ColumnsType<CaseTreeCase> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      render: (text: string, record) => (
        <Space size={4} align="start">
          {record.iteration > 1 && (
            <Tag color="purple" style={{ margin: 0, flexShrink: 0 }}>
              已重写
            </Tag>
          )}
          <a onClick={() => setDetailCaseId(record.id)}>{text}</a>
        </Space>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (val: string) => <Tag color={PRIORITY_COLOR[val] || 'default'}>{val}</Tag>,
    },
    {
      title: '质量',
      key: 'quality',
      width: 150,
      render: (_, record) => {
        const bucket = record.bucket ? BUCKET_TAG[record.bucket] : undefined;
        const reviewIssue = record.review_issue_type ? REVIEW_ISSUE_TAG[record.review_issue_type] : undefined;
        return (
          <Space size={4} wrap>
            {bucket && <Tag color={bucket.color}>{bucket.label}</Tag>}
            {record.verdict && <Tag color={VERDICT_COLOR[record.verdict] || 'default'}>{record.verdict}</Tag>}
            {reviewIssue && <Tag color={reviewIssue.color}>{reviewIssue.label}</Tag>}
          </Space>
        );
      },
    },
    {
      title: '可信度',
      dataIndex: 'trust_level',
      key: 'trust_level',
      width: 80,
      render: (val: number) => {
        const { color, label } = getTrustDisplay(val);
        return <span style={{ color, fontWeight: 600 }}>{label}</span>;
      },
    },
    {
      title: 'Review 状态',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 100,
      render: (val: ReviewStatus) => {
        const cfg = REVIEW_TAG[val];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
  ];

  if (editable) {
    columns.push({
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            disabled={record.review_status === 'confirmed'}
            onClick={() => handleConfirm(record.id)}
          >
            确认
          </Button>
          <Button
            size="small"
            type="link"
            disabled={record.review_status === 'needs_modification'}
            onClick={() => openModify(record.id)}
          >
            需修改
          </Button>
          <Popconfirm
            title="确定删除该用例？"
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(record.id)}
          >
            <Button size="small" type="link" danger disabled={record.review_status === 'deleted'}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    });
  }

  return (
    <Spin spinning={treeLoading}>
      <Row gutter={16}>
        <Col span={7}>
          <Card title="文档 / 模块" size="small">
            {antTreeData.length > 0 ? (
              <Tree
                treeData={antTreeData}
                defaultExpandAll
                onSelect={handleTreeSelect}
                selectedKeys={
                  selectedNode.type === 'all'
                    ? []
                    : selectedNode.type === 'doc'
                      ? [`doc::${selectedNode.docId}`]
                      : [`module::${selectedNode.docId}::${selectedNode.moduleName}`]
                }
              />
            ) : (
              <Empty description="暂无用例" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
        <Col span={17}>
          <Card
            title={listTitle}
            size="small"
            extra={<Text type="secondary">{selectedCases.length} 条</Text>}
          >
            <Table<CaseTreeCase>
              rowKey="id"
              columns={columns}
              dataSource={selectedCases}
              pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true }}
              size="small"
            />
          </Card>
        </Col>
      </Row>

      <Modal
        title="需修改 — 填写修改意见"
        open={modifyOpen}
        onCancel={() => setModifyOpen(false)}
        onOk={submitModify}
        okText="提交"
        cancelText="取消"
      >
        <TextArea
          rows={4}
          value={modifyComment}
          onChange={(e) => setModifyComment(e.target.value)}
          placeholder="请输入修改意见（必填）"
        />
      </Modal>

      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
        editable={editable}
        autoAdvance={editable}
        onRequestNext={handleRequestNext}
        onReview={editable ? applyReview : undefined}
        onUpdated={loadTree}
      />
    </Spin>
  );
};

export default CaseTreeReview;
