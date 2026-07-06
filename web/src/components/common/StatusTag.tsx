import { Tag } from 'antd';
import type { ReactNode } from 'react';

export type StatusTone = 'default' | 'processing' | 'success' | 'warning' | 'danger' | 'info';

const toneColor: Record<StatusTone, string> = {
  default: 'default',
  processing: 'processing',
  success: 'success',
  warning: 'warning',
  danger: 'error',
  info: 'blue',
};

interface StatusTagProps {
  tone?: StatusTone;
  children: ReactNode;
}

function StatusTag({ tone = 'default', children }: StatusTagProps) {
  return <Tag color={toneColor[tone]}>{children}</Tag>;
}

export default StatusTag;
