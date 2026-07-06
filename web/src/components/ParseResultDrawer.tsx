/**
 * 文档解析详情 Drawer — 展示 Stage 1 GraphRAG 产物
 * 统计概览 + Tabs（实体 / 关系 / 图片 AI 理解）
 * 对接 GET /documents/:id/knowledge-graph
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Drawer,
  Empty,
  List,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';

import { getKnowledgeGraph } from '../services/knowledgeGraphApi';
import type { KgEntity, KgRelation, KnowledgeGraph } from '../types';

const { Text } = Typography;

const ENTITY_TYPE: Record<string, { label: string; color: string }> = {
  field: { label: '字段', color: 'blue' },
  section: { label: '章节', color: 'geekblue' },
  rule: { label: '规则', color: 'orange' },
  concept: { label: '概念', color: 'green' },
  ui_element: { label: 'UI 元素', color: 'purple' },
  state: { label: '状态', color: 'cyan' },
};

const RELATION_TYPE: Record<string, string> = {
  section_priority: '章节优先',
  field_defined_in: '定义于',
  rule_constrains: '约束',
  mutually_exclusive: '互斥',
  unreachable: '不可达',
  belongs_to: '属于',
  transitions_to: '流转到',
};

interface Props {
  documentId: string | null;
  open: boolean;
  onClose: () => void;
}

const ParseResultDrawer: React.FC<Props> = ({ documentId, open, onClose }) => {
  const [data, setData] = useState<KnowledgeGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [entityType, setEntityType] = useState<string | undefined>();

  const load = useCallback(async () => {
    if (!documentId || !open) return;
    setLoading(true);
    try {
      const res = await getKnowledgeGraph(documentId);
      setData(res);
    } catch {
      /* 拦截器已统一提示 */
    } finally {
      setLoading(false);
    }
  }, [documentId, open]);

  useEffect(() => {
    load();
  }, [load]);

  // entity id → 实体 映射（关系列显示名称）
  const entityMap = useMemo(() => {
    const m = new Map<string, KgEntity>();
    data?.entities.forEach((e) => m.set(e.id, e));
    return m;
  }, [data]);

  const filteredEntities = useMemo(() => {
    if (!data) return [];
    return entityType ? data.entities.filter((e) => e.entity_type === entityType) : data.entities;
  }, [data, entityType]);

  const entityTypeOptions = useMemo(() => {
    const set = new Set(data?.entities.map((e) => e.entity_type) || []);
    return Array.from(set).map((t) => ({ value: t, label: ENTITY_TYPE[t]?.label || t }));
  }, [data]);

  const entityColumns: ColumnsType<KgEntity> = [
    {
      title: '类型',
      dataIndex: 'entity_type',
      width: 90,
      render: (v: string) => {
        const t = ENTITY_TYPE[v];
        return <Tag color={t?.color}>{t?.label || v}</Tag>;
      },
    },
    { title: '名称', dataIndex: 'name', width: 180, ellipsis: true },
    { title: '章节', dataIndex: 'section_ref', width: 110, ellipsis: true, render: (v: string) => v || '-' },
    { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string) => v || '-' },
  ];

  const relationColumns: ColumnsType<KgRelation> = [
    {
      title: '源实体',
      width: 160,
      ellipsis: true,
      render: (_: unknown, r: KgRelation) =>
        entityMap.get(r.source_entity_id)?.name || r.source_entity_id.slice(0, 8),
    },
    {
      title: '关系',
      dataIndex: 'relation_type',
      width: 100,
      render: (v: string) => <Tag>{RELATION_TYPE[v] || v}</Tag>,
    },
    {
      title: '目标实体',
      width: 160,
      ellipsis: true,
      render: (_: unknown, r: KgRelation) =>
        entityMap.get(r.target_entity_id)?.name || r.target_entity_id.slice(0, 8),
    },
    { title: '备注', dataIndex: 'note', ellipsis: true, render: (v: string) => v || '-' },
  ];

  const captionEntries = data ? Object.entries(data.image_captions || {}) : [];

  return (
    <Drawer title="解析详情（GraphRAG 产物）" open={open} onClose={onClose} width={860} destroyOnHidden>
      <Spin spinning={loading}>
        {data ? (
          <>
            <Space size={48} style={{ marginBottom: 16 }}>
              <Statistic title="实体" value={data.stats.entity_count} />
              <Statistic title="关系" value={data.stats.relation_count} />
              <Statistic title="图片理解" value={data.stats.image_count} />
            </Space>

            <Tabs
              items={[
                {
                  key: 'entities',
                  label: `实体 (${data.stats.entity_count})`,
                  children: (
                    <>
                      <Select
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        placeholder="按类型筛选"
                        style={{ width: 160, marginBottom: 12 }}
                        value={entityType}
                        onChange={setEntityType}
                        options={entityTypeOptions}
                      />
                      <Table<KgEntity>
                        rowKey="id"
                        size="small"
                        columns={entityColumns}
                        dataSource={filteredEntities}
                        pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 个` }}
                      />
                    </>
                  ),
                },
                {
                  key: 'relations',
                  label: `关系 (${data.stats.relation_count})`,
                  children: (
                    <Table<KgRelation>
                      rowKey="id"
                      size="small"
                      columns={relationColumns}
                      dataSource={data.relations}
                      pagination={{ pageSize: 20, showSizeChanger: false, showTotal: (t) => `共 ${t} 条` }}
                    />
                  ),
                },
                {
                  key: 'images',
                  label: `图片理解 (${data.stats.image_count})`,
                  children:
                    captionEntries.length === 0 ? (
                      <Empty description="无图片理解" />
                    ) : (
                      <List
                        dataSource={captionEntries}
                        renderItem={([path, cap]) => {
                          const c = (cap || {}) as Record<string, unknown>;
                          const ui = Array.isArray(c.ui_elements) ? (c.ui_elements as string[]) : [];
                          const flow = Array.isArray(c.flow_steps) ? (c.flow_steps as string[]) : [];
                          return (
                            <List.Item style={{ display: 'block' }}>
                              <Space>
                                <Text strong>{String(c.filename || path)}</Text>
                                {c.kind ? <Tag>{String(c.kind)}</Tag> : null}
                              </Space>
                              {ui.length > 0 && (
                                <div style={{ marginTop: 6 }}>
                                  <Text type="secondary">UI 元素：</Text>
                                  <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                                    {ui.slice(0, 15).map((u, i) => (
                                      <li key={i}>
                                        <Text style={{ fontSize: 13 }}>{u}</Text>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {flow.length > 0 && (
                                <div>
                                  <Text type="secondary">流程：</Text>
                                  <Text style={{ fontSize: 13 }}>{flow.join(' → ')}</Text>
                                </div>
                              )}
                            </List.Item>
                          );
                        }}
                      />
                    ),
                },
              ]}
            />
          </>
        ) : (
          !loading && <Empty description="暂无解析产物（该文档可能未跑过解析）" />
        )}
      </Spin>
    </Drawer>
  );
};

export default ParseResultDrawer;
