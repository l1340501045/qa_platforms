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
  Input,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';

import { getCaseTree } from '../services/systemApi';
import CaseDetailDrawer from './CaseDetailDrawer';
import SplitPane from './layout/SplitPane';
import { layoutTokens } from './layout/tokens';
import {
  findCaseAssetNode,
  getCasesForNode,
  normalizeCaseTreeDocuments,
} from './case-assets/caseAssetModel';
import CaseAssetTree from './case-assets/CaseAssetTree';
import CaseAssetTable from './case-assets/CaseAssetTable';
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

const sectionStyle: React.CSSProperties = {
  minHeight: 360,
  padding: 16,
  border: `1px solid ${layoutTokens.border}`,
  borderRadius: layoutTokens.radius,
  background: layoutTokens.surface,
};

const sectionHeaderStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  alignItems: 'center',
  marginBottom: 12,
};

type ReviewAction = 'confirmed' | 'needs_modification' | 'deleted';

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
  const [selectedNodeKey, setSelectedNodeKey] = useState('root');
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
      setSelectedNodeKey('root');
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

  const caseAssetTree = useMemo(
    () => normalizeCaseTreeDocuments(treeData, { rootTitle: '全部模块' }),
    [treeData],
  );

  useEffect(() => {
    onAllCasesChange?.(getCasesForNode(caseAssetTree.root.key, caseAssetTree));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseAssetTree, onAllCasesChange]);

  useEffect(() => {
    if (!findCaseAssetNode(caseAssetTree.root, selectedNodeKey)) {
      setSelectedNodeKey(caseAssetTree.root.key);
    }
  }, [caseAssetTree, selectedNodeKey]);

  // ─── 当前列表（选中节点 + 标题搜索） ───
  const selectedCases: CaseTreeCase[] = useMemo(() => {
    const kw = (searchKeyword || '').trim();
    const allCases = getCasesForNode(caseAssetTree.root.key, caseAssetTree);
    if (kw) {
      // 搜索时跨全部模块过滤
      return allCases.filter((c) => c.title.includes(kw));
    }
    return getCasesForNode(selectedNodeKey, caseAssetTree);
  }, [caseAssetTree, selectedNodeKey, searchKeyword]);

  const listTitle = useMemo(() => {
    if ((searchKeyword || '').trim()) return `搜索「${searchKeyword!.trim()}」`;
    const selectedNode = findCaseAssetNode(caseAssetTree.root, selectedNodeKey);
    return selectedNode?.title || '全部用例';
  }, [caseAssetTree, selectedNodeKey, searchKeyword]);

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

  const renderReviewActions = useCallback(
    (record: CaseTreeCase) =>
      editable ? (
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
      ) : null,
    [editable, handleConfirm, handleDelete, openModify],
  );

  return (
    <Spin spinning={treeLoading}>
      <SplitPane
        leftWidth={320}
        rightMinWidth={560}
        gap={16}
        left={
          <div style={sectionStyle}>
            <div style={sectionHeaderStyle}>
              <div>
                <Text strong>文档 / 模块</Text>
                <Text style={{ display: 'block', marginTop: 4, color: layoutTokens.textSecondary }}>
                  选择范围后审查右侧用例
                </Text>
              </div>
              <Text type="secondary">{caseAssetTree.root.count} 条</Text>
            </div>
            <CaseAssetTree
              tree={caseAssetTree}
              selectedKey={selectedNodeKey}
              onSelect={setSelectedNodeKey}
              emptyDescription="暂无用例"
              height={480}
              maxHeight="min(560px, calc(100vh - 420px))"
            />
          </div>
        }
        right={
          <div style={sectionStyle}>
            <div style={sectionHeaderStyle}>
              <div style={{ minWidth: 0 }}>
                <Text strong>{listTitle}</Text>
                <Text style={{ display: 'block', marginTop: 4, color: layoutTokens.textSecondary }}>
                  点击标题查看证据、步骤和期望结果
                </Text>
              </div>
              <Text type="secondary" style={{ flexShrink: 0 }}>{selectedCases.length} 条</Text>
            </div>
            <CaseAssetTable
              cases={selectedCases}
              titleColumnLabel="标题"
              titleAsLink
              showIterationTag
              onOpenCase={setDetailCaseId}
              renderActions={editable ? renderReviewActions : undefined}
              pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条`, showSizeChanger: true }}
            />
          </div>
        }
      />

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
