import React from 'react';
import { Space, Tag } from 'antd';

import type { CaseBucket, CaseTreeCase, CaseVerdict, ReviewIssueType, ReviewStatus } from '../../types';

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

export const BUCKET_TAG: Record<CaseBucket, { color: string; label: string; description: string }> = {
  main: {
    color: 'green',
    label: '主集候选',
    description: '可进入人工审查的执行候选，用例是否可复用仍要结合审查状态判断。',
  },
  needs_spec: {
    color: 'gold',
    label: '规格待澄清',
    description: '需求或规则证据不足，应转为规格问题，不应直接当作可执行测试。',
  },
  to_fix: {
    color: 'red',
    label: '生成待修正',
    description: '生成或核验发现明显问题，需要修正后再进入执行候选。',
  },
};

export const VERDICT_TAG: Record<CaseVerdict, { color: string; label: string; description: string }> = {
  grounded: {
    color: 'green',
    label: '有依据',
    description: '断言能在 PRD 或关联资料中找到支撑。',
  },
  ungrounded: {
    color: 'orange',
    label: '无依据',
    description: '断言缺少可追溯证据，需要人工核对或回退为澄清项。',
  },
  undefined: {
    color: 'gold',
    label: '规格未定义',
    description: '需求没有明确定义该行为，适合作为澄清项处理。',
  },
  conflict: {
    color: 'red',
    label: '与PRD冲突',
    description: '断言与已知 PRD 证据冲突，应优先修正或删除。',
  },
};

export const REVIEW_ISSUE_TAG: Record<ReviewIssueType, { color: string; label: string; description: string }> = {
  case_wrong: {
    color: 'red',
    label: '用例错误',
    description: '用例自身断言或步骤有问题，需要改写。',
  },
  prd_conflict: {
    color: 'purple',
    label: 'PRD冲突',
    description: '需求内部或用例与需求存在冲突，需要先定准规则。',
  },
  verify_uncertain: {
    color: 'blue',
    label: '核验不确定',
    description: '证据链不足以自动判定，需要人工复核。',
  },
};

export const BUCKET_FILTER_OPTIONS = (Object.entries(BUCKET_TAG) as Array<[CaseBucket, typeof BUCKET_TAG[CaseBucket]]>)
  .map(([value, item]) => ({ value, label: item.label }));

export const VERDICT_FILTER_OPTIONS = (Object.entries(VERDICT_TAG) as Array<[CaseVerdict, typeof VERDICT_TAG[CaseVerdict]]>)
  .map(([value, item]) => ({ value, label: item.label }));

export const REVIEW_ISSUE_FILTER_OPTIONS = (
  Object.entries(REVIEW_ISSUE_TAG) as Array<[ReviewIssueType, typeof REVIEW_ISSUE_TAG[ReviewIssueType]]>
).map(([value, item]) => ({ value, label: item.label }));

export function getTrustDisplay(level: number): { color: string; label: string } {
  if (level <= 2) return { color: '#52c41a', label: '高可信' };
  if (level === 3) return { color: '#faad14', label: '中可信' };
  return { color: '#f5222d', label: '低可信' };
}

export function renderCaseQualityTags(record: CaseTreeCase): React.ReactNode {
  const bucket = record.bucket ? BUCKET_TAG[record.bucket] : undefined;
  const verdict = record.verdict ? VERDICT_TAG[record.verdict] : undefined;
  const reviewIssue = record.review_issue_type ? REVIEW_ISSUE_TAG[record.review_issue_type] : undefined;
  return (
    <Space size={4} wrap>
      {bucket && <Tag color={bucket.color}>{bucket.label}</Tag>}
      {verdict && <Tag color={verdict.color}>{verdict.label}</Tag>}
      {reviewIssue && <Tag color={reviewIssue.color}>{reviewIssue.label}</Tag>}
    </Space>
  );
}
