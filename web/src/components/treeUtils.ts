import { isValidElement } from 'react';
import type { Key, ReactNode } from 'react';
import type { DataNode } from 'antd/es/tree';

export function collectTreeKeys(nodes: DataNode[]): Key[] {
  return nodes.flatMap((node) => [
    node.key,
    ...collectTreeKeys((node.children || []) as DataNode[]),
  ]);
}

export function collectTreeKeysByDepth(nodes: DataNode[], maxDepth: number, depth = 0): Key[] {
  return nodes.flatMap((node) => {
    if (depth > maxDepth) return [];
    return [
      node.key,
      ...collectTreeKeysByDepth((node.children || []) as DataNode[], maxDepth, depth + 1),
    ];
  });
}

export function filterTreeDataByKeyword(nodes: DataNode[], keyword: string): DataNode[] {
  const normalized = keyword.trim().toLowerCase();
  if (!normalized) return nodes;

  return nodes.flatMap((node) => {
    const children = filterTreeDataByKeyword((node.children || []) as DataNode[], normalized);
    const titleText = typeof node.title === 'function' ? '' : treeTitleToText(node.title);
    const text = `${titleText} ${String(node.key)}`.toLowerCase();
    if (!text.includes(normalized) && children.length === 0) return [];
    return [{ ...node, children: children.length > 0 ? children : undefined }];
  });
}

function treeTitleToText(title: ReactNode): string {
  if (title === null || title === undefined || typeof title === 'boolean') return '';
  if (typeof title === 'string' || typeof title === 'number') return String(title);
  if (Array.isArray(title)) return title.map(treeTitleToText).join(' ');
  if (isValidElement<{ children?: ReactNode }>(title)) {
    return treeTitleToText(title.props.children);
  }
  return '';
}
