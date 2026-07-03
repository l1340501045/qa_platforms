import type { ReactNode } from 'react';

interface SplitPaneProps {
  left: ReactNode;
  right: ReactNode;
  leftWidth?: number;
  rightMinWidth?: number;
  gap?: number;
}

function SplitPane({ left, right, leftWidth = 280, rightMinWidth = 360, gap = 20 }: SplitPaneProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'stretch',
        gap,
        minWidth: 0,
      }}
    >
      <aside
        style={{
          width: leftWidth,
          maxWidth: '100%',
          flex: `0 1 ${leftWidth}px`,
          minWidth: 0,
        }}
      >
        {left}
      </aside>
      <section style={{ flex: `1 1 ${rightMinWidth}px`, minWidth: 0 }}>{right}</section>
    </div>
  );
}

export default SplitPane;
