import type { ReactNode } from 'react';
import { Typography } from 'antd';
import { layoutTokens } from './tokens';

const { Text } = Typography;

export interface MetricItem {
  key: string;
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger';
}

const toneColor: Record<NonNullable<MetricItem['tone']>, string> = {
  default: layoutTokens.text,
  primary: layoutTokens.primary,
  success: layoutTokens.success,
  warning: layoutTokens.warning,
  danger: layoutTokens.danger,
};

interface MetricStripProps {
  items: MetricItem[];
}

function MetricStrip({ items }: MetricStripProps) {
  if (items.length === 0) return null;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: 0,
        marginBottom: 20,
        border: `1px solid ${layoutTokens.border}`,
        borderRadius: layoutTokens.radius,
        background: layoutTokens.surface,
        overflow: 'hidden',
      }}
    >
      {items.map((item, index) => (
        <div
          key={item.key}
          style={{
            minHeight: 78,
            padding: '14px 16px',
            borderLeft: index === 0 ? undefined : `1px solid ${layoutTokens.borderSubtle}`,
          }}
        >
          <Text style={{ color: layoutTokens.textSecondary, fontSize: 13 }}>
            {item.label}
          </Text>
          <div
            style={{
              marginTop: 6,
              color: toneColor[item.tone ?? 'default'],
              fontSize: 24,
              fontWeight: 650,
              lineHeight: 1.2,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {item.value}
          </div>
          {item.hint && (
            <Text style={{ color: layoutTokens.textMuted, fontSize: 12 }}>
              {item.hint}
            </Text>
          )}
        </div>
      ))}
    </div>
  );
}

export default MetricStrip;

