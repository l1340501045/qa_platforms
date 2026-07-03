import React from 'react';
import { Space, Tag } from 'antd';

import type { CaseTreeCase, ReviewIssueType, ReviewStatus } from '../../types';

export const PRIORITY_COLOR: Record<string, string> = {
  P0: 'red',
  P1: 'orange',
  P2: 'blue',
  P3: 'default',
};

export const REVIEW_TAG: Record<ReviewStatus, { color: string; label: string }> = {
  pending: { color: 'default', label: '待审' },
  confirmed: { color: 'green', label: '已确认' },
  needs_modification: { color: 'orange', label: '需修改' },
  deleted: { color: 'red', label: '已删除' },
};

export const BUCKET_TAG: Record<string, { color: string; label: string }> = {
  main: { color: 'green', label: '主集' },
  needs_spec: { color: 'gold', label: '待澄清' },
  to_fix: { color: 'red', label: '待修正' },
};

export const VERDICT_COLOR: Record<string, string> = {
  grounded: 'green',
  ungrounded: 'orange',
  undefined: 'gold',
  conflict: 'red',
};

export const REVIEW_ISSUE_TAG: Record<ReviewIssueType, { color: string; label: string }> = {
  case_wrong: { color: 'red', label: '用例错' },
  prd_conflict: { color: 'purple', label: 'PRD冲突' },
  verify_uncertain: { color: 'blue', label: '核验不确定' },
};

export function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

export function renderCaseQualityTags(record: CaseTreeCase): React.ReactNode {
  const bucket = record.bucket ? BUCKET_TAG[record.bucket] : undefined;
  const reviewIssue = record.review_issue_type ? REVIEW_ISSUE_TAG[record.review_issue_type] : undefined;
  return (
    <Space size={4} wrap>
      {bucket && <Tag color={bucket.color}>{bucket.label}</Tag>}
      {record.verdict && <Tag color={VERDICT_COLOR[record.verdict] || 'default'}>{record.verdict}</Tag>}
      {reviewIssue && <Tag color={reviewIssue.color}>{reviewIssue.label}</Tag>}
    </Space>
  );
}
