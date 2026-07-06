import type { ReactNode } from 'react';
import { layoutTokens } from './tokens';

interface FilterBarProps {
  children: ReactNode;
  align?: 'start' | 'center' | 'end';
}

function FilterBar({ children, align = 'center' }: FilterBarProps) {
  const alignItems = align === 'start' ? 'flex-start' : align === 'end' ? 'flex-end' : align;

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 12,
        alignItems,
        padding: 12,
        marginBottom: 16,
        border: `1px solid ${layoutTokens.border}`,
        borderRadius: layoutTokens.radius,
        background: layoutTokens.surface,
      }}
    >
      {children}
    </div>
  );
}

export default FilterBar;
