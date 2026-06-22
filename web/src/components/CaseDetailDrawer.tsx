/**
 * 用例详情 Drawer — 展示完整用例正文 + 人工编辑 + AI 重写
 * 复用 GET /api/v1/testcases/:id 接口
 * 被 CaseLibrary 和 Workbench 共用
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RobotOutlined,
} from '@ant-design/icons';

import {
  getTestCaseDetail,
  regenerateTestCase,
  updateTestCase,
} from '../services/batchApi';
import type { Priority, ReviewStatus, TestCase, TestStep } from '../types';

const { Text, Paragraph } = Typography;

const PRIORITY_COLOR: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
};

const PRIORITY_OPTIONS = [
  { value: 'P0', label: 'P0' },
  { value: 'P1', label: 'P1' },
  { value: 'P2', label: 'P2' },
  { value: 'P3', label: 'P3' },
];

const REVIEW_TAG: Record<ReviewStatus, { color: string; label: string }> = {
  pending: { color: 'default', label: '待审' },
  confirmed: { color: 'green', label: '已确认' },
  needs_modification: { color: 'orange', label: '需修改' },
  deleted: { color: 'red', label: '已删除' },
};

function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

type ReviewAction = 'confirmed' | 'needs_modification' | 'deleted';

interface CaseDetailDrawerProps {
  caseId: string | null;
  open: boolean;
  onClose: () => void;
  /** 传入则抽屉底部显示审核操作（确认/需修改/删除）；不传则只读浏览 */
  onReview?: (caseId: string, status: ReviewAction, comment?: string) => Promise<void>;
  /** 传入 true 启用编辑和 AI 重写能力 */
  editable?: boolean;
}

// ─── 步骤编辑器 ─────────────────────────────────────────────────────────────────

interface StepEditorProps {
  steps: TestStep[];
  onChange: (steps: TestStep[]) => void;
}

const StepEditor: React.FC<StepEditorProps> = ({ steps, onChange }) => {
  const updateStep = (index: number, field: keyof TestStep, value: string) => {
    const updated = [...steps];
    updated[index] = { ...updated[index], [field]: value };
    onChange(updated);
  };

  const addStep = () => {
    onChange([
      ...steps,
      { step_number: steps.length + 1, action: '', input_data: '', expected_result: '' },
    ]);
  };

  const removeStep = (index: number) => {
    const updated = steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, step_number: i + 1 }));
    onChange(updated);
  };

  return (
    <div>
      {steps.map((step, idx) => (
        <div
          key={idx}
          style={{
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            padding: 12,
            marginBottom: 8,
            position: 'relative',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <Text strong>步骤 {idx + 1}</Text>
            {steps.length > 1 && (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => removeStep(idx)}
              />
            )}
          </div>
          <div style={{ marginBottom: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>动作</Text>
            <Input
              value={step.action}
              onChange={(e) => updateStep(idx, 'action', e.target.value)}
              placeholder="具体操作动作"
            />
          </div>
          <div style={{ marginBottom: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>输入数据</Text>
            <Input
              value={step.input_data}
              onChange={(e) => updateStep(idx, 'input_data', e.target.value)}
              placeholder="输入数据"
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>预期结果</Text>
            <Input
              value={step.expected_result}
              onChange={(e) => updateStep(idx, 'expected_result', e.target.value)}
              placeholder="预期结果"
            />
          </div>
        </div>
      ))}
      <Button type="dashed" block icon={<PlusOutlined />} onClick={addStep}>
        添加步骤
      </Button>
    </div>
  );
};

// ─── 字符串列表编辑器 ─────────────────────────────────────────────────────────────

interface StringListEditorProps {
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
}

const StringListEditor: React.FC<StringListEditorProps> = ({ items, onChange, placeholder }) => {
  const updateItem = (index: number, value: string) => {
    const updated = [...items];
    updated[index] = value;
    onChange(updated);
  };

  const addItem = () => onChange([...items, '']);

  const removeItem = (index: number) => onChange(items.filter((_, i) => i !== index));

  return (
    <div>
      {items.map((item, idx) => (
        <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
          <Input
            value={item}
            onChange={(e) => updateItem(idx, e.target.value)}
            placeholder={placeholder}
            style={{ flex: 1 }}
          />
          {items.length > 1 && (
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => removeItem(idx)}
            />
          )}
        </div>
      ))}
      <Button type="dashed" size="small" icon={<PlusOutlined />} onClick={addItem}>
        添加
      </Button>
    </div>
  );
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────────

const CaseDetailDrawer: React.FC<CaseDetailDrawerProps> = ({
  caseId,
  open,
  onClose,
  onReview,
  editable = false,
}) => {
  const [loading, setLoading] = useState(false);
  const [caseData, setCaseData] = useState<TestCase | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [modifyOpen, setModifyOpen] = useState(false);
  const [modifyComment, setModifyComment] = useState('');

  // 编辑态
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<{
    title: string;
    priority: Priority;
    preconditions: string[];
    steps: TestStep[];
    expected_results: string[];
  } | null>(null);
  const [saving, setSaving] = useState(false);

  // AI 重写态
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenComment, setRegenComment] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const iterationRef = useRef<number>(0);

  const handleReview = async (status: ReviewAction, comment?: string) => {
    if (!caseId || !onReview) return;
    setReviewing(true);
    try {
      await onReview(caseId, status, comment);
      onClose();
    } catch {
      /* 父级 / 拦截器已统一提示 */
    } finally {
      setReviewing(false);
    }
  };

  const loadCase = useCallback(async () => {
    if (!caseId) return;
    setLoading(true);
    try {
      const data = await getTestCaseDetail(caseId);
      setCaseData(data);
    } catch {
      message.error('加载用例详情失败');
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    if (!caseId || !open) {
      setCaseData(null);
      setEditing(false);
      setEditForm(null);
      setRegenerating(false);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    loadCase();
  }, [caseId, open, loadCase]);

  // 清理轮询
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ─── 编辑功能 ───

  const enterEdit = () => {
    if (!caseData) return;
    setEditForm({
      title: caseData.title,
      priority: caseData.priority,
      preconditions: [...(caseData.preconditions || [])],
      steps: (caseData.steps || []).map((s) => ({ ...s })),
      expected_results: [...(caseData.expected_results || [])],
    });
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setEditForm(null);
  };

  const saveEdit = async () => {
    if (!caseId || !editForm) return;
    setSaving(true);
    try {
      const updated = await updateTestCase(caseId, {
        title: editForm.title,
        priority: editForm.priority,
        preconditions: editForm.preconditions,
        steps: editForm.steps,
        expected_results: editForm.expected_results,
      });
      setCaseData(updated);
      setEditing(false);
      setEditForm(null);
      message.success('保存成功');
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ─── AI 重写功能 ───

  const handleRegenerate = async () => {
    if (!caseId || !regenComment.trim()) {
      message.warning('请填写修改意见');
      return;
    }
    setRegenOpen(false);
    setRegenerating(true);
    iterationRef.current = caseData?.iteration || 0;

    try {
      await regenerateTestCase(caseId, regenComment.trim());
      setRegenComment('');

      // 轮询检测完成（带超时上限，避免重写失败时一直转圈）
      let pollCount = 0;
      const MAX_POLLS = 40; // 40 × 3s = 120s
      pollRef.current = setInterval(async () => {
        pollCount += 1;
        try {
          const latest = await getTestCaseDetail(caseId);
          if (latest.iteration > iterationRef.current) {
            // 重写完成
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setCaseData(latest);
            setRegenerating(false);
            message.success('AI 重写完成');
            return;
          }
        } catch {
          // 轮询失败静默重试
        }
        if (pollCount >= MAX_POLLS) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setRegenerating(false);
          message.warning('AI 重写超时，请稍后刷新查看（任务可能仍在后台运行）');
        }
      }, 3000);
    } catch {
      setRegenerating(false);
      message.error('提交重写请求失败');
    }
  };

  // ─── 渲染 ───

  const steps: TestStep[] = Array.isArray(caseData?.steps)
    ? (caseData.steps as TestStep[])
    : [];

  const preconditions: string[] = Array.isArray(caseData?.preconditions)
    ? (caseData.preconditions as string[])
    : [];

  const expectedResults: string[] = Array.isArray(caseData?.expected_results)
    ? (caseData.expected_results as string[])
    : [];

  const { color: trustColor, label: trustLabel } = caseData
    ? getTrustDisplay(caseData.trust_level)
    : { color: '#8c8c8c', label: '-' };

  const renderFooter = () => {
    if (editing) {
      return (
        <Space>
          <Button type="primary" loading={saving} onClick={saveEdit}>
            保存
          </Button>
          <Button onClick={cancelEdit}>取消</Button>
        </Space>
      );
    }

    const actions: React.ReactNode[] = [];

    if (editable && !regenerating) {
      actions.push(
        <Button key="edit" icon={<EditOutlined />} onClick={enterEdit}>
          编辑
        </Button>,
      );
      actions.push(
        <Button key="regen" icon={<RobotOutlined />} onClick={() => setRegenOpen(true)}>
          AI 重写
        </Button>,
      );
    }

    if (onReview && caseData) {
      actions.push(
        <Button
          key="confirm"
          type="primary"
          loading={reviewing}
          disabled={caseData.review_status === 'confirmed'}
          onClick={() => handleReview('confirmed')}
        >
          确认
        </Button>,
        <Button
          key="modify"
          loading={reviewing}
          disabled={caseData.review_status === 'needs_modification'}
          onClick={() => setModifyOpen(true)}
        >
          需修改
        </Button>,
        <Popconfirm
          key="delete"
          title="确定删除该用例？"
          okText="删除"
          okButtonProps={{ danger: true }}
          onConfirm={() => handleReview('deleted')}
        >
          <Button danger loading={reviewing} disabled={caseData.review_status === 'deleted'}>
            删除
          </Button>
        </Popconfirm>,
      );
    }

    return actions.length > 0 ? <Space wrap>{actions}</Space> : undefined;
  };

  return (
    <Drawer
      title={editing ? '编辑用例' : caseData?.title || '用例详情'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnClose
      footer={caseData ? renderFooter() : undefined}
    >
      <Spin spinning={loading || regenerating} tip={regenerating ? 'AI 重写中...' : undefined}>
        {caseData && !editing && (
          <>
            {/* 基本信息 */}
            <Descriptions column={2} size="small" style={{ marginBottom: 24 }}>
              <Descriptions.Item label="优先级">
                <Tag color={PRIORITY_COLOR[caseData.priority] || 'default'}>
                  {caseData.priority}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="可信度">
                <span style={{ color: trustColor, fontWeight: 600 }}>{trustLabel}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Review 状态">
                <Tag color={REVIEW_TAG[caseData.review_status as ReviewStatus]?.color}>
                  {REVIEW_TAG[caseData.review_status as ReviewStatus]?.label || caseData.review_status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="迭代次数">{caseData.iteration}</Descriptions.Item>
            </Descriptions>

            {/* 前置条件 */}
            {preconditions.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  前置条件
                </Text>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {preconditions.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 测试步骤 */}
            {steps.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  测试步骤
                </Text>
                <Steps
                  direction="vertical"
                  size="small"
                  current={-1}
                  items={steps.map((step) => ({
                    title: step.action,
                    description: (
                      <div>
                        {step.input_data && (
                          <div>
                            <Text type="secondary">输入数据：</Text>
                            {step.input_data}
                          </div>
                        )}
                        {step.expected_result && (
                          <div>
                            <Text type="secondary">预期结果：</Text>
                            {step.expected_result}
                          </div>
                        )}
                      </div>
                    ),
                  }))}
                />
              </div>
            )}

            {/* 预期结果（汇总） */}
            {expectedResults.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  预期结果
                </Text>
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {expectedResults.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 三者皆空时兜底 */}
            {preconditions.length === 0 &&
              steps.length === 0 &&
              expectedResults.length === 0 && (
                <Empty
                  description="该用例暂无前置条件 / 步骤 / 预期结果"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  style={{ margin: '24px 0' }}
                />
              )}

            {/* 溯源信息 */}
            {caseData.provenance &&
              (caseData.provenance.source_section ||
                caseData.provenance.verbatim_excerpt ||
                caseData.provenance.derived_from) && (
              <div style={{ marginBottom: 24 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  溯源 (Provenance)
                </Text>
                <Descriptions column={1} size="small" bordered>
                  {caseData.provenance.source_section && (
                    <Descriptions.Item label="来源章节">
                      {caseData.provenance.source_section}
                    </Descriptions.Item>
                  )}
                  {caseData.provenance.verbatim_excerpt && (
                    <Descriptions.Item label="原文摘录">
                      <Paragraph
                        ellipsis={{ rows: 3, expandable: true }}
                        style={{ margin: 0 }}
                      >
                        {caseData.provenance.verbatim_excerpt}
                      </Paragraph>
                    </Descriptions.Item>
                  )}
                  {caseData.provenance.derived_from && (
                    <Descriptions.Item label="衍生自">
                      {Array.isArray(caseData.provenance.derived_from)
                        ? caseData.provenance.derived_from.join(', ')
                        : String(caseData.provenance.derived_from)}
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}

            {/* Review 意见 */}
            {caseData.review_comment && (
              <div>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  Review 意见
                </Text>
                <Paragraph style={{ background: '#f5f5f5', padding: 12, borderRadius: 4 }}>
                  {caseData.review_comment}
                </Paragraph>
              </div>
            )}
          </>
        )}

        {/* 编辑态 */}
        {caseData && editing && editForm && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>用例名称</Text>
              <Input
                value={editForm.title}
                onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>优先级</Text>
              <Select
                value={editForm.priority}
                onChange={(v) => setEditForm({ ...editForm, priority: v as Priority })}
                options={PRIORITY_OPTIONS}
                showSearch
                optionFilterProp="label"
                style={{ width: 120 }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>前置条件</Text>
              <StringListEditor
                items={editForm.preconditions}
                onChange={(items) => setEditForm({ ...editForm, preconditions: items })}
                placeholder="前置条件"
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>测试步骤</Text>
              <StepEditor
                steps={editForm.steps}
                onChange={(s) => setEditForm({ ...editForm, steps: s })}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: 'block', marginBottom: 4 }}>预期结果</Text>
              <StringListEditor
                items={editForm.expected_results}
                onChange={(items) => setEditForm({ ...editForm, expected_results: items })}
                placeholder="预期结果"
              />
            </div>
          </div>
        )}
      </Spin>

      {/* 需修改 Modal */}
      <Modal
        title="需修改 — 填写修改意见"
        open={modifyOpen}
        onCancel={() => setModifyOpen(false)}
        confirmLoading={reviewing}
        okText="提交"
        cancelText="取消"
        onOk={async () => {
          if (!modifyComment.trim()) {
            message.warning('请填写修改意见');
            return;
          }
          await handleReview('needs_modification', modifyComment.trim());
          setModifyOpen(false);
          setModifyComment('');
        }}
      >
        <Input.TextArea
          rows={4}
          value={modifyComment}
          onChange={(e) => setModifyComment(e.target.value)}
          placeholder="请输入修改意见（必填）"
        />
      </Modal>

      {/* AI 重写 Modal */}
      <Modal
        title="AI 重写 — 填写修改意见"
        open={regenOpen}
        onCancel={() => setRegenOpen(false)}
        okText="开始重写"
        cancelText="取消"
        onOk={handleRegenerate}
      >
        <Input.TextArea
          rows={4}
          value={regenComment}
          onChange={(e) => setRegenComment(e.target.value)}
          placeholder="请输入希望 AI 如何修改此用例（必填）"
        />
      </Modal>
    </Drawer>
  );
};

export default CaseDetailDrawer;
