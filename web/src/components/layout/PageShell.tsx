import type { CSSProperties, ReactNode } from 'react';
import { layoutTokens } from './tokens';

interface PageShellProps {
  children: ReactNode;
  maxWidth?: number | string;
  style?: CSSProperties;
}

function PageShell({ children, maxWidth = '100%', style }: PageShellProps) {
  return (
    <main
      style={{
        width: '100%',
        maxWidth,
        margin: '0 auto',
        color: layoutTokens.text,
        ...style,
      }}
    >
      {children}
    </main>
  );
}

export default PageShell;

