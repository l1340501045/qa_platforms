/**
 * 用例详情 Drawer — 展示完整用例正文
 * 复用 GET /api/v1/testcases/:id 接口
 * 被 CaseLibrary 和 Workbench 共用
 */
import React, { useEffect, useState } from 'react';
import {
  Descriptions,
  Drawer,
  Spin,
  Steps,
  Tag,
  Typography,
  message,
} from 'antd';

import { getTestCaseDetail } from '../services/batchApi';
import type { ReviewStatus, TestCase, TestStep } from '../types';

const { Text, Paragraph } = Typography;

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

function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

interface CaseDetailDrawerProps {
  caseId: string | null;
  open: boolean;
  onClose: () => void;
}

const CaseDetailDrawer: React.FC<CaseDetailDrawerProps> = ({ caseId, open, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [caseData, setCaseData] = useState<TestCase | null>(null);

  useEffect(() => {
    if (!caseId || !open) {
      setCaseData(null);
      return;
    }

    const load = async () => {
      setLoading(true);
      try {
        const data = await getTestCaseDetail(caseId);
        setCaseData(data);
      } catch {
        message.error('加载用例详情失败');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [caseId, open]);

  // 解析步骤
  const steps: TestStep[] = Array.isArray(caseData?.steps)
    ? (caseData.steps as TestStep[])
    : [];

  // 解析前置条件
  const preconditions: string[] = Array.isArray(caseData?.preconditions)
    ? (caseData.preconditions as string[])
    : [];

  // 解析预期结果
  const expectedResults: string[] = Array.isArray(caseData?.expected_results)
    ? (caseData.expected_results as string[])
    : [];

  const { color: trustColor, label: trustLabel } = caseData
    ? getTrustDisplay(caseData.trust_level)
    : { color: '#8c8c8c', label: '-' };

  return (
    <Drawer
      title={caseData?.title || '用例详情'}
      open={open}
      onClose={onClose}
      width={640}
      destroyOnClose
    >
      <Spin spinning={loading}>
        {caseData && (
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

            {/* 溯源信息 */}
            {caseData.provenance && (
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
      </Spin>
    </Drawer>
  );
};

export default CaseDetailDrawer;
