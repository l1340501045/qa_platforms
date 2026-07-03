/**
 * 用例库 — /case-library
 * 树形浏览：文档 → 业务模块 → 分支 → 用例
 * 对接 GET /api/v1/systems/:id/case-tree
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Card,
  Select,
  Spin,
  Typography,
} from 'antd';
import { ApartmentOutlined } from '@ant-design/icons';

import { getCaseTree, listSystemBatches, listSystemOptions } from '../../services/systemApi';
import type { SystemBatchItem } from '../../services/systemApi';
import CaseDetailDrawer from '../../components/CaseDetailDrawer';
import {
  findCaseAssetNode,
  getCasesForNode,
  normalizeCaseTreeDocuments,
} from '../../components/case-assets/caseAssetModel';
import CaseAssetTree from '../../components/case-assets/CaseAssetTree';
import CaseAssetTable from '../../components/case-assets/CaseAssetTable';
import type {
  CaseBucket,
  CaseTreeDocument,
  CaseTreeView,
  CaseVerdict,
  Priority,
  ReviewIssueType,
  ReviewStatus,
} from '../../types';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import SplitPane from '../../components/layout/SplitPane';

const { Text } = Typography;

const CaseLibraryPage: React.FC = () => {
  // ─── State ───
  const [systemOptions, setSystemOptions] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedSystemId, setSelectedSystemId] = useState<string | undefined>();
  const [priority, setPriority] = useState<Priority | undefined>();
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | undefined>();
  const [bucket, setBucket] = useState<CaseBucket | undefined>();
  const [verdict, setVerdict] = useState<CaseVerdict | undefined>();
  const [reviewIssueType, setReviewIssueType] = useState<ReviewIssueType | undefined>();
  const [caseTreeView, setCaseTreeView] = useState<CaseTreeView>('stable');
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>();

  const [treeData, setTreeData] = useState<CaseTreeDocument[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);

  const [selectedNodeKey, setSelectedNodeKey] = useState('root');
  const [detailCaseId, setDetailCaseId] = useState<string | null>(null);

  // 可见批次列表（用于批次切换器）
  const [viewableBatches, setViewableBatches] = useState<SystemBatchItem[]>([]);

  // 加载系统选项
  useEffect(() => {
    listSystemOptions()
      .then((opts) => {
        setSystemOptions(opts);
        if (opts.length > 0) {
          setSelectedSystemId(opts[0].id);
        }
      })
      .catch(() => {});
  }, []);

  // 当系统变更时，加载该系统的可见批次列表
  useEffect(() => {
    if (!selectedSystemId) {
      setViewableBatches([]);
      return;
    }
    listSystemBatches(selectedSystemId, { per_page: 100 })
      .then((res) => {
        // 只保留可见状态的批次
        const visible = res.items.filter((b) =>
          ['pending_review', 'completed', 'archived'].includes(b.status),
        );
        setViewableBatches(visible);
      })
      .catch(() => setViewableBatches([]));
  }, [selectedSystemId]);

  // 加载用例树
  const loadTree = useCallback(async () => {
    if (!selectedSystemId) return;
    setTreeLoading(true);
    try {
      const data = await getCaseTree(selectedSystemId, {
        batch_id: selectedBatchId,
        priority,
        review_status: reviewStatus,
        bucket: caseTreeView === 'stable' ? undefined : bucket,
        verdict,
        review_issue_type: reviewIssueType,
        view: caseTreeView,
        include_duplicates: caseTreeView === 'all',
      });
      setTreeData(data);
      setSelectedNodeKey('root');
    } finally {
      setTreeLoading(false);
    }
  }, [selectedSystemId, selectedBatchId, priority, reviewStatus, bucket, verdict, reviewIssueType, caseTreeView]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  const systemName = useMemo(
    () => systemOptions.find((s) => s.id === selectedSystemId)?.name || '系统',
    [systemOptions, selectedSystemId],
  );
  const caseAssetTree = useMemo(
    () => normalizeCaseTreeDocuments(treeData, { rootTitle: systemName }),
    [treeData, systemName],
  );

  useEffect(() => {
    if (!findCaseAssetNode(caseAssetTree.root, selectedNodeKey)) {
      setSelectedNodeKey(caseAssetTree.root.key);
    }
  }, [caseAssetTree, selectedNodeKey]);

  // ─── 选中节点对应的用例 ───
  const selectedCases = useMemo(
    () => getCasesForNode(selectedNodeKey, caseAssetTree),
    [caseAssetTree, selectedNodeKey],
  );

  // ─── 当前选中的标题 ───
  const selectedTitle: string = useMemo(() => {
    const selectedNode = findCaseAssetNode(caseAssetTree.root, selectedNodeKey);
    return selectedNode?.title || '全部用例';
  }, [caseAssetTree, selectedNodeKey]);

  // ─── 统计 ───
  const stats = useMemo(() => {
    const all = getCasesForNode(caseAssetTree.root.key, caseAssetTree);
    return {
      total: all.length,
      p0: all.filter((c) => c.priority === 'P0').length,
      confirmed: all.filter((c) => c.review_status === 'confirmed').length,
      pending: all.filter((c) => c.review_status === 'pending').length,
      docCount: caseAssetTree.root.children.length,
      moduleCount: caseAssetTree.root.children.reduce((sum, doc) => sum + doc.children.length, 0),
    };
  }, [caseAssetTree]);

  return (
    <PageShell>
      <PageHeader
        eyebrow="用例资产"
        title={
          <>
            <ApartmentOutlined style={{ marginRight: 8 }} />
            用例资产
          </>
        }
        description="按系统、批次、资产视图和质量状态浏览沉淀后的用例，模块树支持多级分支。"
      />

      {/* ─── 筛选栏 ─── */}
      <FilterBar>
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="选择系统"
          style={{ width: 200 }}
          value={selectedSystemId}
          onChange={(val) => {
            setSelectedSystemId(val);
            setSelectedBatchId(undefined); // 切系统时重置批次
          }}
          options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
        />
        <Select
          placeholder="资产视图"
          style={{ width: 160 }}
          value={caseTreeView}
          onChange={(value: CaseTreeView) => {
            setCaseTreeView(value);
            if (value === 'stable') {
              setBucket(undefined);
            }
          }}
          options={[
            { value: 'stable', label: '稳定主集' },
            { value: 'all', label: '全部资产' },
            { value: 'review_required', label: '待分类' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="批次（默认=最新）"
          style={{ width: 340 }}
          value={selectedBatchId}
          onChange={setSelectedBatchId}
          options={viewableBatches.map((b) => {
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
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="优先级"
          style={{ width: 120 }}
          value={priority}
          onChange={setPriority}
          options={[
            { value: 'P0', label: 'P0' },
            { value: 'P1', label: 'P1' },
            { value: 'P2', label: 'P2' },
            { value: 'P3', label: 'P3' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Review 状态"
          style={{ width: 140 }}
          value={reviewStatus}
          onChange={setReviewStatus}
          options={[
            { value: 'pending', label: '待审' },
            { value: 'confirmed', label: '已确认' },
            { value: 'needs_modification', label: '需修改' },
          ]}
        />
        <Select
          allowClear
          placeholder="质量桶"
          style={{ width: 140 }}
          value={bucket}
          onChange={setBucket}
          disabled={caseTreeView === 'stable'}
          options={[
            { value: 'main', label: '主集' },
            { value: 'needs_spec', label: '待澄清' },
            { value: 'to_fix', label: '待修正' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="核验结论"
          style={{ width: 160 }}
          value={verdict}
          onChange={setVerdict}
          options={[
            { value: 'grounded', label: 'grounded' },
            { value: 'ungrounded', label: 'ungrounded' },
            { value: 'undefined', label: 'undefined' },
            { value: 'conflict', label: 'conflict' },
          ]}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="审查诊断"
          style={{ width: 160 }}
          value={reviewIssueType}
          onChange={setReviewIssueType}
          options={[
            { value: 'case_wrong', label: '用例错' },
            { value: 'prd_conflict', label: 'PRD冲突' },
            { value: 'verify_uncertain', label: '核验不确定' },
          ]}
        />
      </FilterBar>

      {/* ─── 统计卡片 ─── */}
      <MetricStrip
        items={[
          { key: 'total', label: '总用例', value: stats.total, tone: 'primary' },
          { key: 'docs', label: '文档数', value: stats.docCount },
          { key: 'modules', label: '模块数', value: stats.moduleCount },
          { key: 'p0', label: 'P0 用例', value: stats.p0, tone: 'danger' },
          { key: 'confirmed', label: '已确认', value: stats.confirmed, tone: 'success' },
          { key: 'pending', label: '待审', value: stats.pending, tone: 'warning' },
        ]}
      />

      {/* ─── 主体：左树右表 ─── */}
      <SplitPane
        left={
          <Card title="文档 / 模块结构" size="small" style={{ height: '100%' }}>
            <Spin spinning={treeLoading}>
              <CaseAssetTree
                tree={caseAssetTree}
                selectedKey={selectedNodeKey}
                onSelect={setSelectedNodeKey}
                emptyDescription="暂无数据"
              />
            </Spin>
          </Card>
        }
        right={
          <Card
            title={selectedTitle}
            size="small"
            extra={<Text type="secondary">{selectedCases.length} 条</Text>}
          >
            <CaseAssetTable
              cases={selectedCases}
              pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
              rowClickToOpen
              onOpenCase={setDetailCaseId}
            />
          </Card>
        }
        leftWidth={340}
      />

      {/* ─── 用例详情 Drawer ─── */}
      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
      />
    </PageShell>
  );
};

export default CaseLibraryPage;
