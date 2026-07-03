import type { ReactNode } from 'react';
import { Space, Typography } from 'antd';
import { layoutTokens } from './tokens';

const { Title, Text } = Typography;

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}

function PageHeader({ title, description, eyebrow, meta, actions }: PageHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 16,
        alignItems: 'flex-start',
        marginBottom: 20,
      }}
    >
      <div style={{ minWidth: 0 }}>
        {eyebrow && (
          <Text
            style={{
              display: 'block',
              marginBottom: 4,
              color: layoutTokens.primary,
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            {eyebrow}
          </Text>
        )}
        <Title level={2} style={{ margin: 0, fontSize: 24, lineHeight: 1.25 }}>
          {title}
        </Title>
        {description && (
          <Text
            style={{
              display: 'block',
              marginTop: 8,
              color: layoutTokens.textSecondary,
              fontSize: 14,
              lineHeight: 1.6,
            }}
          >
            {description}
          </Text>
        )}
        {meta && <div style={{ marginTop: 10 }}>{meta}</div>}
      </div>
      {actions && (
        <Space size={8} wrap style={{ justifyContent: 'flex-end', minHeight: 40 }}>
          {actions}
        </Space>
      )}
    </div>
  );
}

export default PageHeader;

