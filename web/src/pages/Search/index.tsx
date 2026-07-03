/**
 * 全局用例搜索 — /search
 * 对接 GET /api/v1/cases/search (word_similarity)
 * 支持关键词搜索 + system/priority/review_status 筛选 + 分页
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Input,
  Pagination,
  Select,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { ColumnsType } from 'antd/es/table';

import { searchCases } from '../../services/searchApi';
import { listSystemOptions } from '../../services/systemApi';
import CaseDetailDrawer from '../../components/CaseDetailDrawer';
import EmptyState from '../../components/common/EmptyState';
import FilterBar from '../../components/layout/FilterBar';
import MetricStrip from '../../components/layout/MetricStrip';
import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import type { Priority, ReviewStatus, SearchResultItem } from '../../types';

const { Text } = Typography;

// ─── 常量 ───
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

const SearchPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // 从 URL 恢复搜索状态
  const initialQuery = searchParams.get('q') || '';
  const initialSystemId = searchParams.get('system_id') || undefined;
  const initialPriority = (searchParams.get('priority') as Priority) || undefined;
  const initialReviewStatus = (searchParams.get('review_status') as ReviewStatus) || undefined;
  const initialPage = parseInt(searchParams.get('page') || '1', 10);

  // State
  const [query, setQuery] = useState(initialQuery);
  const [systemId, setSystemId] = useState<string | undefined>(initialSystemId);
  const [priority, setPriority] = useState<Priority | undefined>(initialPriority);
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus | undefined>(initialReviewStatus);
  const [page, setPage] = useState(initialPage);
  const [perPage] = useState(20);

  const [items, setItems] = useState<SearchResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(!!initialQuery);

  // 系统选项
  const [systemOptions, setSystemOptions] = useState<Array<{ id: string; name: string }>>([]);
  const [detailCaseId, setDetailCaseId] = useState<string | null>(null);

  // 加载系统选项
  useEffect(() => {
    listSystemOptions().then(setSystemOptions).catch(() => {});
  }, []);

  // 搜索逻辑
  const doSearch = useCallback(
    async (q: string, opts?: { systemId?: string; priority?: Priority; reviewStatus?: ReviewStatus; page?: number }) => {
      if (!q.trim()) return;
      const p = opts?.page ?? 1;

      setLoading(true);
      setSearched(true);
      try {
        const res = await searchCases({
          q: q.trim(),
          system_id: opts?.systemId,
          priority: opts?.priority,
          review_status: opts?.reviewStatus,
          page: p,
          per_page: perPage,
        });
        setItems(res.items);
        setTotal(res.total);
        setPage(res.page);

        // 同步 URL
        const params: Record<string, string> = { q: q.trim() };
        if (opts?.systemId) params.system_id = opts.systemId;
        if (opts?.priority) params.priority = opts.priority;
        if (opts?.reviewStatus) params.review_status = opts.reviewStatus;
        if (p > 1) params.page = String(p);
        setSearchParams(params, { replace: true });
      } finally {
        setLoading(false);
      }
    },
    [perPage, setSearchParams],
  );

  // 初始加载（URL 带 query 时自动搜索）
  useEffect(() => {
    if (initialQuery) {
      doSearch(initialQuery, {
        systemId: initialSystemId,
        priority: initialPriority,
        reviewStatus: initialReviewStatus,
        page: initialPage,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── 事件处理 ───
  const handleSearch = () => {
    doSearch(query, { systemId, priority, reviewStatus, page: 1 });
  };

  const handlePageChange = (newPage: number) => {
    doSearch(query, { systemId, priority, reviewStatus, page: newPage });
  };

  const handleFilterChange = (
    newSystemId?: string,
    newPriority?: Priority,
    newReviewStatus?: ReviewStatus,
  ) => {
    setSystemId(newSystemId);
    setPriority(newPriority);
    setReviewStatus(newReviewStatus);
    if (query.trim()) {
      doSearch(query, { systemId: newSystemId, priority: newPriority, reviewStatus: newReviewStatus, page: 1 });
    }
  };

  // ─── 表格列 ───
  const columns: ColumnsType<SearchResultItem> = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      width: '30%',
      render: (text: string, record) => (
        <a onClick={() => setDetailCaseId(record.id)}>{text}</a>
      ),
    },
    {
      title: '所属系统',
      dataIndex: 'system_name',
      key: 'system_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '文档',
      dataIndex: 'document_title',
      key: 'document_title',
      width: 160,
      ellipsis: true,
      render: (text: string, record) => (
        <a onClick={() => navigate(`/documents/${record.document_id}`)}>{text}</a>
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
      title: '状态',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 90,
      render: (val: ReviewStatus) => {
        const cfg = REVIEW_TAG[val];
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '匹配度',
      dataIndex: 'score',
      key: 'score',
      width: 80,
      render: (val: number) => (
        <Badge
          color={val >= 0.6 ? '#52c41a' : val >= 0.4 ? '#faad14' : '#f5222d'}
          text={`${(val * 100).toFixed(0)}%`}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (val: string) => new Date(val).toLocaleString('zh-CN'),
    },
  ];

  return (
    <PageShell>
      <PageHeader
        eyebrow="全局搜索"
        title="用例搜索"
        description="按关键词跨系统检索用例，可继续用系统、优先级和审核状态缩小范围。"
      />

      {searched && (
        <MetricStrip
          items={[
            { key: 'total', label: '匹配结果', value: total, tone: 'primary' },
            { key: 'page', label: '本页展示', value: items.length },
            { key: 'query', label: '当前关键词', value: query || '-' },
          ]}
        />
      )}

      {/* ─── 搜索栏 ─── */}
      <div style={{ marginBottom: 16 }}>
        <Input.Search
          size="large"
          placeholder="输入关键词搜索用例（支持中文模糊匹配）"
          enterButton={<><SearchOutlined /> 搜索</>}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onSearch={handleSearch}
          allowClear
          style={{ maxWidth: 600 }}
        />
      </div>

      {/* ─── 筛选栏 ─── */}
      <FilterBar>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="系统筛选"
          style={{ width: 180 }}
          value={systemId}
          onChange={(val) => handleFilterChange(val, priority, reviewStatus)}
          options={systemOptions.map((s) => ({ value: s.id, label: s.name }))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="优先级"
          style={{ width: 120 }}
          value={priority}
          onChange={(val) => handleFilterChange(systemId, val, reviewStatus)}
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
          onChange={(val) => handleFilterChange(systemId, priority, val)}
          options={[
            { value: 'pending', label: '待审' },
            { value: 'confirmed', label: '已确认' },
            { value: 'needs_modification', label: '需修改' },
          ]}
        />
        {searched && (
          <Text type="secondary">
            共找到 {total} 条结果
          </Text>
        )}
      </FilterBar>

      {/* ─── 搜索结果 ─── */}
      <Spin spinning={loading}>
        {searched && items.length === 0 && !loading ? (
          <EmptyState
            title="没有找到匹配的用例"
            description="可以换一个业务关键词，或放宽系统、优先级和审核状态筛选。"
          />
        ) : (
          <Table<SearchResultItem>
            rowKey="id"
            columns={columns}
            dataSource={items}
            pagination={false}
            size="middle"
          />
        )}
      </Spin>

      {/* ─── 分页 ─── */}
      {total > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
          <Pagination
            current={page}
            pageSize={perPage}
            total={total}
            onChange={handlePageChange}
            showTotal={(t) => `共 ${t} 条`}
            showSizeChanger={false}
          />
        </div>
      )}

      {/* ─── 用例详情 Drawer ─── */}
      <CaseDetailDrawer
        caseId={detailCaseId}
        open={!!detailCaseId}
        onClose={() => setDetailCaseId(null)}
      />
    </PageShell>
  );
};

export default SearchPage;
