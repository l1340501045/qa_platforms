/**
 * 用例库 — /case-library
 * 树形浏览：文档 → 业务模块 → 分支 → 用例
 * 对接 GET /api/v1/systems/:id/case-tree
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Select,
  Segmented,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { ApartmentOutlined, FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import { getCaseTree, listSystemBatches, listSystemOptions } from '../../services/systemApi';
import type { SystemBatchItem } from '../../services/systemApi';
import CaseDetailDrawer from '../../components/CaseDetailDrawer';
import EmptyState from '../../components/common/EmptyState';
import {
  type CaseAssetNode,
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
import { layoutTokens } from '../../components/layout/tokens';
import { getErrorMessage } from '../../utils/errorMessage';

const { Text } = Typography;

const VIEW_COPY: Record<CaseTreeView, { label: string; message: string; description: string }> = {
  stable: {
    label: '稳定主集',
    message: '当前展示可复用、可落库的稳定资产',
    description: '适合回归选择、导出复用和查看已沉淀的主集用例；需要排查重复或异常时切到全部资产。',
  },
  all: {
    label: '全部资产',
    message: '当前展示完整资产池',
    description: '包含重复、待处理和稳定资产，适合做全量追溯、质量排查或核对生成结果。',
  },
  review_required: {
    label: '待处理资产',
    message: '当前聚焦需要 QA 处理的资产',
    description: '优先处理待审、需修改、待澄清或核验不确定的用例，再进入落库和复用。',
  },
};

const NODE_TYPE_LABEL: Record<CaseAssetNode['type'], string> = {
  root: '系统',
  document: '文档',
  module: '模块',
  branch: '分支',
};

function countBranchNodes(nodes: CaseAssetNode[]): number {
  return nodes.reduce((sum, node) => {
    const self = node.type === 'branch' ? 1 : 0;
    return sum + self + countBranchNodes(node.children);
  }, 0);
}

function formatBatchStatus(status: string): string {
  if (status === 'pending_review') return '待审阅';
  if (status === 'completed') return '已完成';
  if (status === 'archived') return '已落库';
  return status;
}

const CaseLibraryPage: React.FC = () => {
  const navigate = useNavigate();

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
  const [treeError, setTreeError] = useState<string | null>(null);
  const [systemLoading, setSystemLoading] = useState(false);
  const [systemError, setSystemError] = useState<string | null>(null);

  const [selectedNodeKey, setSelectedNodeKey] = useState('root');
  const [detailCaseId, setDetailCaseId] = useState<string | null>(null);

  // 可见批次列表（用于批次切换器）
  const [viewableBatches, setViewableBatches] = useState<SystemBatchItem[]>([]);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);

  const loadSystems = useCallback(async () => {
    setSystemLoading(true);
    setSystemError(null);
    try {
      const opts = await listSystemOptions();
      setSystemOptions(opts);
      if (opts.length > 0) {
        setSelectedSystemId((current) => current || opts[0].id);
      } else {
        setSelectedSystemId(undefined);
        setTreeData([]);
        setViewableBatches([]);
        setBatchError(null);
      }
    } catch (err) {
      setSystemError(getErrorMessage(err, '系统列表暂时无法加载，请重试。'));
      setSystemOptions([]);
      setSelectedSystemId(undefined);
      setTreeData([]);
      setViewableBatches([]);
      setBatchError(null);
    } finally {
      setSystemLoading(false);
    }
  }, []);

  // 加载系统选项
  useEffect(() => {
    loadSystems();
  }, [loadSystems]);

  const loadViewableBatches = useCallback(async () => {
    if (!selectedSystemId) {
      setViewableBatches([]);
      setBatchError(null);
      return;
    }
    setBatchLoading(true);
    setBatchError(null);
    try {
      const res = await listSystemBatches(selectedSystemId, { per_page: 100 });
      // 只保留可见状态的批次
      const visible = res.items.filter((b) =>
        ['pending_review', 'completed', 'archived'].includes(b.status),
      );
      setViewableBatches(visible);
    } catch (err) {
      setBatchError(getErrorMessage(err, '批次范围暂时无法加载，请重试。'));
      setViewableBatches([]);
      setSelectedBatchId(undefined);
    } finally {
      setBatchLoading(false);
    }
  }, [selectedSystemId]);

  // 当系统变更时，加载该系统的可见批次列表
  useEffect(() => {
    loadViewableBatches();
  }, [loadViewableBatches]);

  // 加载用例树
  const loadTree = useCallback(async () => {
    if (!selectedSystemId) return;
    setTreeLoading(true);
    setTreeError(null);
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
    } catch (err) {
      setTreeError(getErrorMessage(err, '用例资产暂时无法加载，请重试。'));
      setTreeData([]);
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

  const selectedNode = useMemo(
    () => findCaseAssetNode(caseAssetTree.root, selectedNodeKey),
    [caseAssetTree, selectedNodeKey],
  );

  // ─── 统计 ───
  const stats = useMemo(() => {
    const all = getCasesForNode(caseAssetTree.root.key, caseAssetTree);
    return {
      total: all.length,
      p0: all.filter((c) => c.priority === 'P0').length,
      confirmed: all.filter((c) => c.review_status === 'confirmed').length,
      pending: all.filter((c) => c.review_status === 'pending').length,
      needsModification: all.filter((c) => c.review_status === 'needs_modification').length,
      duplicate: all.filter((c) => c.is_duplicate || c.duplicate_of).length,
      docCount: caseAssetTree.root.children.length,
      moduleCount: caseAssetTree.root.children.reduce((sum, doc) => sum + doc.children.length, 0),
      branchCount: countBranchNodes(caseAssetTree.root.children),
    };
  }, [caseAssetTree]);

  const selectedBatch = useMemo(
    () => viewableBatches.find((b) => b.id === selectedBatchId),
    [selectedBatchId, viewableBatches],
  );
  const selectedBatchLabel = selectedBatch
    ? `${selectedBatch.document_title} · ${formatBatchStatus(selectedBatch.status)}`
    : batchError
      ? '默认最新可见批次（批次列表未加载）'
      : '默认最新可见批次';
  const activeView = VIEW_COPY[caseTreeView];
  const hasFilters = Boolean(
    selectedBatchId || priority || reviewStatus || bucket || verdict || reviewIssueType || caseTreeView !== 'stable',
  );
  const hasSystem = Boolean(selectedSystemId);
  const assetMetricUnavailable = Boolean(treeError && !treeLoading);

  const clearFilters = () => {
    setCaseTreeView('stable');
    setSelectedBatchId(undefined);
    setPriority(undefined);
    setReviewStatus(undefined);
    setBucket(undefined);
    setVerdict(undefined);
    setReviewIssueType(undefined);
  };

  const openKnowledgeBase = () => {
    if (selectedSystemId) {
      navigate(`/systems/${selectedSystemId}/documents`);
    }
  };

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
        description="先选系统，再按稳定主集、全部资产或待处理资产浏览沉淀用例；树用于定位文档、模块和分支，表格用于审查与追溯。"
        actions={
          <>
            <Button
              icon={<ReloadOutlined />}
              loading={treeLoading || systemLoading}
              disabled={!hasSystem && !systemError}
              onClick={hasSystem ? loadTree : loadSystems}
            >
              刷新资产
            </Button>
            <Button type="primary" icon={<FolderOpenOutlined />} disabled={!hasSystem} onClick={openKnowledgeBase}>
              上传/生成
            </Button>
          </>
        }
      />

      {systemError && !systemLoading ? (
        <EmptyState
          role="alert"
          title="系统列表加载失败"
          description={`无法确认有哪些系统和用例资产。${systemError}`}
          action={<Button onClick={loadSystems}>重试加载</Button>}
        />
      ) : (
        <>
      <Alert
        type={hasSystem && !treeError ? 'info' : 'warning'}
        showIcon
        style={{ marginBottom: 16 }}
        message={
          treeError
            ? '用例资产暂时无法加载'
            : hasSystem
              ? activeView.message
              : '先选择一个系统，再查看它沉淀下来的用例资产'
        }
        description={
          treeError
            ? '不能据此判断当前系统没有资产；可点击刷新资产或在下方重试加载。'
            : hasSystem
            ? `${activeView.description} 当前批次范围：${selectedBatchLabel}。`
            : '系统列表为空或尚未选中系统时，用例树不会加载；可以先去系统管理创建系统并上传 PRD。'
        }
        action={
          treeError ? (
            <Button size="small" onClick={loadTree}>
              重试加载
            </Button>
          ) : hasSystem ? (
            <Button size="small" onClick={openKnowledgeBase}>
              去知识库
            </Button>
          ) : (
            <Button size="small" onClick={() => navigate('/systems')}>
              去系统管理
            </Button>
          )
        }
      />

      <FilterBar align="start">
        <Space direction="vertical" size={6}>
          <Text type="secondary">系统</Text>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择系统"
            style={{ width: 220 }}
            value={selectedSystemId}
            loading={systemLoading}
            onChange={(val) => {
              setSelectedSystemId(val);
              setSelectedBatchId(undefined);
              setSelectedNodeKey('root');
              setTreeData([]);
              setTreeError(null);
              setViewableBatches([]);
              setBatchError(null);
            }}
            options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">资产视图</Text>
          <Segmented
            value={caseTreeView}
            onChange={(value) => {
              const next = value as CaseTreeView;
              setCaseTreeView(next);
              if (next === 'stable') {
                setBucket(undefined);
              }
            }}
            options={[
              { value: 'stable', label: '稳定主集' },
              { value: 'all', label: '全部资产' },
              { value: 'review_required', label: '待处理资产' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">批次范围</Text>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="默认最新可见批次"
            style={{ width: 340 }}
            value={selectedBatchId}
            onChange={setSelectedBatchId}
            loading={batchLoading}
            status={batchError ? 'warning' : undefined}
            notFoundContent={batchError ? '批次范围加载失败' : undefined}
            options={viewableBatches.map((b) => {
              const date = new Date(b.created_at).toLocaleDateString('zh-CN');
              return {
                value: b.id,
                label: `${b.document_title} · ${date} · ${b.total_cases ?? 0}例 · ${formatBatchStatus(b.status)}`,
              };
            })}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">优先级</Text>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部"
            style={{ width: 110 }}
            value={priority}
            onChange={setPriority}
            options={[
              { value: 'P0', label: 'P0' },
              { value: 'P1', label: 'P1' },
              { value: 'P2', label: 'P2' },
              { value: 'P3', label: 'P3' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">审查状态</Text>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部"
            style={{ width: 130 }}
            value={reviewStatus}
            onChange={setReviewStatus}
            options={[
              { value: 'pending', label: '待审' },
              { value: 'confirmed', label: '已确认' },
              { value: 'needs_modification', label: '需修改' },
              { value: 'deleted', label: '已删除' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">质量桶</Text>
          <Select
            allowClear
            placeholder="全部"
            style={{ width: 120 }}
            value={bucket}
            onChange={setBucket}
            disabled={caseTreeView === 'stable'}
            options={[
              { value: 'main', label: '主集' },
              { value: 'needs_spec', label: '待澄清' },
              { value: 'to_fix', label: '待修正' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">核验结论</Text>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部"
            style={{ width: 140 }}
            value={verdict}
            onChange={setVerdict}
            options={[
              { value: 'grounded', label: 'grounded' },
              { value: 'ungrounded', label: 'ungrounded' },
              { value: 'undefined', label: 'undefined' },
              { value: 'conflict', label: 'conflict' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">审查诊断</Text>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="全部"
            style={{ width: 130 }}
            value={reviewIssueType}
            onChange={setReviewIssueType}
            options={[
              { value: 'case_wrong', label: '用例错' },
              { value: 'prd_conflict', label: 'PRD冲突' },
              { value: 'verify_uncertain', label: '核验不确定' },
            ]}
          />
        </Space>
        <Space direction="vertical" size={6}>
          <Text type="secondary">筛选</Text>
          <Button disabled={!hasFilters} onClick={clearFilters}>
            重置
          </Button>
        </Space>
      </FilterBar>

      {batchError && !batchLoading && !treeError && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="批次范围暂时无法加载"
          description={`当前仍按默认最新可见批次展示资产；不能据此判断该系统没有历史批次。${batchError}`}
          action={
            <Button size="small" onClick={loadViewableBatches}>
              重试批次
            </Button>
          }
        />
      )}

      {/* ─── 统计卡片 ─── */}
      <MetricStrip
        items={[
          {
            key: 'total',
            label: '当前视图用例',
            value: assetMetricUnavailable ? '-' : stats.total,
            tone: assetMetricUnavailable ? 'warning' : 'primary',
            hint: assetMetricUnavailable ? '加载失败' : activeView.label,
          },
          { key: 'selected', label: '选中范围', value: assetMetricUnavailable ? '-' : selectedCases.length },
          { key: 'docs', label: '文档数', value: assetMetricUnavailable ? '-' : stats.docCount },
          { key: 'modules', label: '模块数', value: assetMetricUnavailable ? '-' : stats.moduleCount },
          { key: 'branches', label: '分支节点', value: assetMetricUnavailable ? '-' : stats.branchCount },
          { key: 'p0', label: 'P0 用例', value: assetMetricUnavailable ? '-' : stats.p0, tone: 'danger' },
          { key: 'confirmed', label: '已确认', value: assetMetricUnavailable ? '-' : stats.confirmed, tone: 'success' },
          {
            key: 'pending',
            label: '待处理',
            value: assetMetricUnavailable ? '-' : stats.pending + stats.needsModification,
            tone: 'warning',
          },
          { key: 'duplicates', label: '重复标记', value: assetMetricUnavailable ? '-' : stats.duplicate },
        ]}
      />

      {/* ─── 主体：左树右表 ─── */}
      <SplitPane
        left={
          <div
            style={{
              height: '100%',
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: 8,
                padding: '12px 14px',
                borderBottom: `1px solid ${layoutTokens.borderSubtle}`,
              }}
            >
              <Text strong>文档 / 模块结构</Text>
              <Tag color="blue">{stats.total} 条</Tag>
            </div>
            <div style={{ padding: 12 }}>
              <Spin spinning={treeLoading}>
                {treeError && !treeLoading ? (
                  <Alert
                    type="warning"
                    showIcon
                    message="结构加载失败"
                    description="用例树暂时无法加载，不能据此判断当前系统没有资产。"
                    action={
                      <Button size="small" onClick={loadTree}>
                        重试
                      </Button>
                    }
                  />
                ) : (
                  <CaseAssetTree
                    tree={caseAssetTree}
                    selectedKey={selectedNodeKey}
                    onSelect={setSelectedNodeKey}
                    emptyDescription={hasSystem ? '当前视图暂无资产' : '请选择系统'}
                    height={500}
                    maxHeight="calc(100vh - 440px)"
                  />
                )}
              </Spin>
            </div>
          </div>
        }
        right={
          <div
            style={{
              minWidth: 0,
              border: `1px solid ${layoutTokens.border}`,
              borderRadius: layoutTokens.radius,
              background: layoutTokens.surface,
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: 12,
                alignItems: 'flex-start',
                padding: '12px 14px',
                borderBottom: `1px solid ${layoutTokens.borderSubtle}`,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <Space size={8} wrap>
                  <Text strong>{selectedTitle}</Text>
                  <Tag>{NODE_TYPE_LABEL[selectedNode?.type || 'root'] || '范围'}</Tag>
                </Space>
                <Text
                  style={{
                    display: 'block',
                    marginTop: 4,
                    color: layoutTokens.textSecondary,
                    fontSize: 13,
                  }}
                >
                  {selectedCases.length} 条用例 · {selectedBatchLabel}
                </Text>
              </div>
              <Tag color={caseTreeView === 'review_required' ? 'orange' : 'green'}>{activeView.label}</Tag>
            </div>
            <div style={{ padding: 12, minWidth: 0 }}>
              {!hasSystem ? (
                <EmptyState
                  title="请选择系统"
                  description="选择系统后会加载该系统已沉淀的用例资产。"
                  action={<Button onClick={() => navigate('/systems')}>去系统管理</Button>}
                />
              ) : treeError && !treeLoading ? (
                <EmptyState
                  role="alert"
                  title="用例资产加载失败"
                  description={`无法确认当前系统是否已有资产。${treeError}`}
                  action={<Button onClick={loadTree}>重试加载</Button>}
                />
              ) : selectedCases.length === 0 && !treeLoading ? (
                <EmptyState
                  title="当前范围暂无用例资产"
                  description="可以切换资产视图或批次；如果系统还没有资产，先去知识库上传资料并发起生成。"
                  action={
                    <Space wrap>
                      <Button onClick={clearFilters} disabled={!hasFilters}>
                        重置筛选
                      </Button>
                      <Button type="primary" onClick={openKnowledgeBase}>
                        上传/生成
                      </Button>
                    </Space>
                  }
                />
              ) : (
                <CaseAssetTable
                  cases={selectedCases}
                  pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
                  rowClickToOpen
                  titleAsLink
                  showIterationTag
                  onOpenCase={setDetailCaseId}
                />
              )}
            </div>
          </div>
        }
        leftWidth={360}
        rightMinWidth={640}
      />

      {/* ─── 用例详情 Drawer ─── */}
      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
      />
        </>
      )}
    </PageShell>
  );
};

export default CaseLibraryPage;
