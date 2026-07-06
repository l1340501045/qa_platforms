/**
 * 知识速查表 QA 审核台 — Drawer
 * 对接 ②a 后端：列条目 / 通过 / 拒绝 / 编辑 QA 版 / 批量通过 / 重新提取
 * 被 DocumentDetail 调用
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Drawer,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  EditOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

import {
  batchApproveCheatSheets,
  editCheatSheetItem,
  extractCheatSheets,
  listCheatSheetItems,
  reviewCheatSheetItem,
} from '../services/cheatSheetApi';
import type { CheatSheetItem, CheatSheetReviewStatus, CheatSheetType } from '../types';

const { Text, Paragraph } = Typography;

const TYPE_LABEL: Record<CheatSheetType, { label: string; color: string }> = {
  must_test: { label: '必测点', color: 'red' },
  confusion_pair: { label: '防混淆', color: 'orange' },
  section_priority: { label: '章节优先', color: 'blue' },
  prd_status: { label: 'PRD 状态', color: 'purple' },
};

const STATUS_LABEL: Record<CheatSheetReviewStatus, { label: string; color: string }> = {
  pending: { label: '待审', color: 'default' },
  approved: { label: '已通过', color: 'green' },
  rejected: { label: '已拒绝', color: 'red' },
};

/** content 字段中文 label（覆盖 4 类 ai_content 字段） */
const FIELD_LABEL: Record<string, string> = {
  rule_text: '规则',
  category: '类别',
  applies_to: '适用于',
  section_ref: '章节',
  source_quote: '原文摘录',
  test_hint: '测试提示',
  item_a: '项 A',
  item_b: '项 B',
  distinction: '区别',
  local_section: '局部章节',
  global_section: '全局章节',
  applies_when: '适用场景',
  resolution: '处理口径',
  status_kind: '状态类型',
  subject: '主体',
  context: '上下文',
  annotation: '标注',
};

function renderContent(content: Record<string, unknown> | null) {
  if (!content) return null;
  const entries = Object.entries(content).filter(
    ([, v]) => v != null && String(v).trim() !== '',
  );
  if (entries.length === 0) return <Text type="secondary">（无内容）</Text>;
  return (
    <div>
      {entries.map(([k, v]) => (
        <div key={k} style={{ marginBottom: 4 }}>
          <Text type="secondary" style={{ marginRight: 6 }}>
            {FIELD_LABEL[k] || k}：
          </Text>
          <Text>{String(v)}</Text>
        </div>
      ))}
    </div>
  );
}

interface Props {
  documentId: string | null;
  open: boolean;
  onClose: () => void;
}

const CheatSheetDrawer: React.FC<Props> = ({ documentId, open, onClose }) => {
  const [items, setItems] = useState<CheatSheetItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState<CheatSheetType | undefined>();
  const [statusFilter, setStatusFilter] = useState<CheatSheetReviewStatus | undefined>();
  const [extracting, setExtracting] = useState(false);

  const [editItem, setEditItem] = useState<CheatSheetItem | null>(null);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [editSaving, setEditSaving] = useState(false);

  const load = useCallback(async () => {
    if (!documentId || !open) return;
    setLoading(true);
    try {
      const res = await listCheatSheetItems(documentId, {
        per_page: 100,
        type: typeFilter,
        status: statusFilter,
      });
      setItems(res.items);
    } catch {
      /* 拦截器已统一提示 */
    } finally {
      setLoading(false);
    }
  }, [documentId, open, typeFilter, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const handleReview = async (
    item: CheatSheetItem,
    status: 'approved' | 'rejected',
    comment?: string,
  ) => {
    try {
      await reviewCheatSheetItem(item.id, { status, comment });
      message.success(status === 'approved' ? '已通过' : '已拒绝');
      load();
    } catch {
      /* */
    }
  };

  const handleReject = (item: CheatSheetItem) => {
    let reason = '';
    Modal.confirm({
      title: '拒绝该条目',
      content: (
        <Input.TextArea
          rows={3}
          placeholder="拒绝原因（可选）"
          onChange={(e) => {
            reason = e.target.value;
          }}
        />
      ),
      okText: '确认拒绝',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => handleReview(item, 'rejected', reason),
    });
  };

  const openEdit = (item: CheatSheetItem) => {
    const base = (item.qa_content || item.ai_content) as Record<string, unknown>;
    const form: Record<string, string> = {};
    Object.entries(base).forEach(([k, v]) => {
      form[k] = v == null ? '' : String(v);
    });
    setEditForm(form);
    setEditItem(item);
  };

  const saveEdit = async () => {
    if (!editItem) return;
    setEditSaving(true);
    try {
      await editCheatSheetItem(editItem.id, editForm);
      message.success('已保存 QA 版');
      setEditItem(null);
      load();
    } catch {
      /* */
    } finally {
      setEditSaving(false);
    }
  };

  const handleExtract = async () => {
    if (!documentId) return;
    setExtracting(true);
    try {
      const r = await extractCheatSheets(documentId);
      if (r.enabled === false) {
        message.warning(r.message || '提取功能未开启（cheat_sheet_extract_enabled）');
      } else {
        message.success(`已生成新版本 v${r.version ?? '?'}`);
      }
      load();
    } catch {
      /* */
    } finally {
      setExtracting(false);
    }
  };

  const handleBatchApprove = async () => {
    if (!documentId || !typeFilter) {
      message.warning('请先在上方选择一个类型，再批量通过');
      return;
    }
    try {
      const r = await batchApproveCheatSheets(documentId, { sheet_type: typeFilter });
      message.success(`已批量通过 ${r.updated_count} 条`);
      load();
    } catch {
      /* */
    }
  };

  return (
    <Drawer title="知识速查表（QA 审核台）" open={open} onClose={onClose} width={720} destroyOnHidden>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="类型筛选"
          style={{ width: 130 }}
          value={typeFilter}
          onChange={setTypeFilter}
          options={Object.entries(TYPE_LABEL).map(([v, { label }]) => ({ value: v, label }))}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="状态筛选"
          style={{ width: 120 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.entries(STATUS_LABEL).map(([v, { label }]) => ({ value: v, label }))}
        />
        <Button onClick={handleBatchApprove} disabled={!typeFilter}>
          批量通过当前类型
        </Button>
        <Button icon={<ReloadOutlined />} loading={extracting} onClick={handleExtract}>
          重新提取
        </Button>
      </Space>

      <Spin spinning={loading}>
        {items.length === 0 ? (
          <Empty description="暂无速查条目（可点「重新提取」从实体图谱生成）" />
        ) : (
          items.map((item) => {
            const t = TYPE_LABEL[item.sheet_type];
            const s = STATUS_LABEL[item.review_status];
            const hasQa = !!item.qa_content && Object.keys(item.qa_content).length > 0;
            return (
              <div
                key={item.id}
                style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, marginBottom: 12 }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 8,
                  }}
                >
                  <Space>
                    <Tag color={t?.color}>{t?.label || item.sheet_type}</Tag>
                    <Text strong>{item.title}</Text>
                  </Space>
                  <Space>
                    {item.review_tier && <Tag>{item.review_tier}</Tag>}
                    <Tag color={s?.color}>{s?.label || item.review_status}</Tag>
                  </Space>
                </div>

                {renderContent(hasQa ? item.qa_content : item.ai_content)}
                {hasQa && (
                  <Text type="success" style={{ fontSize: 12 }}>
                    （已 QA 修订）
                  </Text>
                )}
                {item.review_comment && (
                  <Paragraph type="secondary" style={{ fontSize: 12, margin: '4px 0 0' }}>
                    审核意见：{item.review_comment}
                  </Paragraph>
                )}

                <Space style={{ marginTop: 8 }}>
                  <Button
                    size="small"
                    type="primary"
                    icon={<CheckOutlined />}
                    disabled={item.review_status === 'approved'}
                    onClick={() => handleReview(item, 'approved')}
                  >
                    通过
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<CloseOutlined />}
                    disabled={item.review_status === 'rejected'}
                    onClick={() => handleReject(item)}
                  >
                    拒绝
                  </Button>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(item)}>
                    编辑
                  </Button>
                </Space>
              </div>
            );
          })
        )}
      </Spin>

      <Modal
        title="编辑 QA 版内容"
        open={!!editItem}
        onCancel={() => setEditItem(null)}
        onOk={saveEdit}
        confirmLoading={editSaving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        {Object.entries(editForm).map(([k, v]) => (
          <div key={k} style={{ marginBottom: 12 }}>
            <Text type="secondary">{FIELD_LABEL[k] || k}</Text>
            <Input.TextArea
              rows={2}
              value={v}
              onChange={(e) => setEditForm((prev) => ({ ...prev, [k]: e.target.value }))}
            />
          </div>
        ))}
      </Modal>
    </Drawer>
  );
};

export default CheatSheetDrawer;
