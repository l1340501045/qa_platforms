import type { ReactNode } from 'react';
import { Empty, Typography } from 'antd';
import { layoutTokens } from '../layout/tokens';

const { Text } = Typography;

interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  role?: 'status' | 'alert';
}

function EmptyState({ title, description, action, role }: EmptyStateProps) {
  return (
    <div
      role={role}
      style={{
        padding: '48px 24px',
        border: `1px dashed ${layoutTokens.border}`,
        borderRadius: layoutTokens.radius,
        background: layoutTokens.surface,
        textAlign: 'center',
      }}
    >
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={false}>
        <div style={{ fontWeight: 600, color: layoutTokens.text }}>{title}</div>
        {description && (
          <Text
            style={{
              display: 'block',
              marginTop: 8,
              color: layoutTokens.textSecondary,
            }}
          >
            {description}
          </Text>
        )}
        {action && <div style={{ marginTop: 16 }}>{action}</div>}
      </Empty>
    </div>
  );
}

export default EmptyState;
