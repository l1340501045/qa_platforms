/**
 * 用例库 — /case-library
 * 三级树形浏览：文档 → 模块(source_section) → 用例
 * 对接 GET /api/v1/systems/:id/case-tree
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tree,
  Typography,
} from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  FileTextOutlined,
  FolderOutlined,
} from '@ant-design/icons';
import type { DataNode } from 'antd/es/tree';
import type { ColumnsType } from 'antd/es/table';

import { getCaseTree, listSystemBatches, listSystemOptions } from '../../services/systemApi';
import type { SystemBatchItem } from '../../services/systemApi';
import CaseDetailDrawer from '../../components/CaseDetailDrawer';
import type {
  CaseTreeCase,
  CaseTreeDocument,
  Priority,
  ReviewStatus,
} from '../../types';

const { Title, Text } = Typography;

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

/**
 * trust_level 配色（契约 §6：数字越小越可信）
 * 1-2 = 高可信/绿，3 = 中可信/黄，4-5 = 低可信/红
 */
function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

/** 从树数据中提取所有用例 */
function allCasesFromTree(tree: CaseTreeDocument[]): CaseTreeCase[] {
  return tree.flatMap((doc) => doc.modules.flatMap((m) => m.cases));
}

/** 从单个文档中提取所有用例 */
function casesFromDoc(doc: CaseTreeDocument): CaseTreeCase[] {
  return doc.modules.flatMap((m) => m.cases);
}

/** 选中节点可以是文档或模块，用 key 前缀区分 */
type SelectedNode =
  | { type: 'all' }
  | { type: 'doc'; docId: string }
  | { type: 'module'; docId: string; moduleName: string };

const CaseLibraryPage: React.FC = () => {
  // ─── State ───
  const [systemOptions, setSystemOptions] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedSystemId, setSelectedSystemId] = useState<string | undefined>();
  const [priority, setPriority] = useState<Priority | undefined>();
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | undefined>();
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>();

  const [treeData, setTreeData] = useState<CaseTreeDocument[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);

  const [selectedNode, setSelectedNode] = useState<SelectedNode>({ type: 'all' });
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
      });
      setTreeData(data);
      setSelectedNode({ type: 'all' });
    } finally {
      setTreeLoading(false);
    }
  }, [selectedSystemId, selectedBatchId, priority, reviewStatus]);

  useEffect(() => {
    loadTree();
  }, [loadTree]);

  // ─── 构建 Ant Design Tree 数据（三级：文档 → 模块 → 用例数） ───
  const antTreeData: DataNode[] = useMemo(() => {
    if (treeData.length === 0) return [];

    const systemName = systemOptions.find((s) => s.id === selectedSystemId)?.name || '系统';
    const totalCases = allCasesFromTree(treeData).length;

    const docNodes: DataNode[] = treeData.map((doc) => {
      const docCaseCount = casesFromDoc(doc).length;

      const moduleNodes: DataNode[] = doc.modules.map((mod) => ({
        key: `module::${doc.document_id}::${mod.module_name}`,
        title: (
          <span>
            <AppstoreOutlined style={{ marginRight: 4, color: '#8c8c8c' }} />
            {mod.module_name}
            <Tag style={{ marginLeft: 8 }} color="default">
              {mod.case_count}
            </Tag>
          </span>
        ),
        isLeaf: true,
      }));

      return {
        key: `doc::${doc.document_id}`,
        title: (
          <span>
            <FileTextOutlined style={{ marginRight: 4 }} />
            {doc.document_title}
            <Tag style={{ marginLeft: 8 }} color="blue">
              {docCaseCount}
            </Tag>
          </span>
        ),
        children: moduleNodes,
      };
    });

    return [
      {
        key: '__root__',
        title: (
          <span>
            <FolderOutlined style={{ marginRight: 4 }} />
            {systemName}
            <Tag style={{ marginLeft: 8 }}>
              {totalCases} 用例
            </Tag>
          </span>
        ),
        children: docNodes,
      },
    ];
  }, [treeData, systemOptions, selectedSystemId]);

  // ─── 选中节点对应的用例 ───
  const selectedCases: CaseTreeCase[] = useMemo(() => {
    switch (selectedNode.type) {
      case 'all':
        return allCasesFromTree(treeData);
      case 'doc': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        return doc ? casesFromDoc(doc) : [];
      }
      case 'module': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        if (!doc) return [];
        const mod = doc.modules.find((m) => m.module_name === selectedNode.moduleName);
        return mod?.cases || [];
      }
    }
  }, [treeData, selectedNode]);

  // ─── 当前选中的标题 ───
  const selectedTitle: string = useMemo(() => {
    switch (selectedNode.type) {
      case 'all':
        return '全部用例';
      case 'doc': {
        const doc = treeData.find((d) => String(d.document_id) === selectedNode.docId);
        return doc?.document_title || '文档用例';
      }
      case 'module':
        return selectedNode.moduleName;
    }
  }, [treeData, selectedNode]);

  // ─── 统计 ───
  const stats = useMemo(() => {
    const all = allCasesFromTree(treeData);
    return {
      total: all.length,
      p0: all.filter((c) => c.priority === 'P0').length,
      confirmed: all.filter((c) => c.review_status === 'confirmed').length,
      pending: all.filter((c) => c.review_status === 'pending').length,
      docCount: treeData.length,
      moduleCount: treeData.reduce((sum, d) => sum + d.modules.length, 0),
    };
  }, [treeData]);

  // ─── 表格列 ───
  const columns: ColumnsType<CaseTreeCase> = [
    {
      title: '用例标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (val: string) => <Tag color={PRIORITY_COLOR[val] || 'default'}>{val}</Tag>,
    },
    {
      title: '可信度',
      dataIndex: 'trust_level',
      key: 'trust_level',
      width: 90,
      render: (val: number) => {
        const { color, label } = getTrustDisplay(val);
        return <span style={{ color, fontWeight: 600 }}>{label}</span>;
      },
    },
    {
      title: '状态',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 90,
      render: (val: ReviewStatus) => {
        const cfg = REVIEW_TAG[val];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
  ];

  // ─── 树节点选择 ───
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
      setSelectedNode({ type: 'module', docId: parts[0], moduleName: parts[1] });
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Title level={3} style={{ marginBottom: 24 }}>
        <ApartmentOutlined style={{ marginRight: 8 }} />
        用例库
      </Title>

      {/* ─── 筛选栏 ─── */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
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
          allowClear
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
      </Space>

      {/* ─── 统计卡片 ─── */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card size="small">
            <Statistic title="总用例" value={stats.total} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="文档数" value={stats.docCount} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="模块数" value={stats.moduleCount} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="P0 用例" value={stats.p0} valueStyle={{ color: '#cf1322' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="已确认" value={stats.confirmed} valueStyle={{ color: '#3f8600' }} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic title="待审" value={stats.pending} valueStyle={{ color: '#8c8c8c' }} />
          </Card>
        </Col>
      </Row>

      {/* ─── 主体：左树右表 ─── */}
      <Row gutter={24}>
        <Col span={8}>
          <Card title="文档 / 模块结构" size="small" style={{ height: '100%' }}>
            <Spin spinning={treeLoading}>
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
                <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Spin>
          </Card>
        </Col>
        <Col span={16}>
          <Card
            title={selectedTitle}
            size="small"
            extra={<Text type="secondary">{selectedCases.length} 条</Text>}
          >
            <Table<CaseTreeCase>
              rowKey="id"
              columns={columns}
              dataSource={selectedCases}
              pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
              size="small"
              onRow={(record) => ({
                onClick: () => setDetailCaseId(record.id),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>
        </Col>
      </Row>

      {/* ─── 用例详情 Drawer ─── */}
      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
      />
    </div>
  );
};

export default CaseLibraryPage;
