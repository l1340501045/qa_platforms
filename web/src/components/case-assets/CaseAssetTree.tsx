import React, { useEffect, useMemo, useState } from 'react';
import { AppstoreOutlined, FileTextOutlined, FolderOutlined } from '@ant-design/icons';
import { Button, Empty, Input, Space, Tag, Tree } from 'antd';
import type { DataNode } from 'antd/es/tree';

import {
  collectCaseAssetKeys,
  filterCaseAssetTree,
  getDefaultExpandedKeys,
} from './caseAssetModel';
import type { CaseAssetNode, CaseAssetTree as CaseAssetTreeModel } from './caseAssetModel';

interface CaseAssetTreeProps {
  tree: CaseAssetTreeModel;
  selectedKey: string;
  onSelect: (nodeKey: string) => void;
  searchPlaceholder?: string;
  emptyDescription?: string;
  height?: number;
  maxHeight?: number | string;
}

function iconForNode(node: CaseAssetNode): React.ReactNode {
  if (node.type === 'document') return <FileTextOutlined style={{ marginRight: 4 }} />;
  if (node.type === 'module') {
    return <AppstoreOutlined style={{ marginRight: 4, color: '#8c8c8c' }} />;
  }
  return <FolderOutlined style={{ marginRight: 4, color: node.type === 'branch' ? '#8c8c8c' : undefined }} />;
}

function toAntTreeNode(node: CaseAssetNode): DataNode {
  return {
    key: node.key,
    title: (
      <span
        title={node.title}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          maxWidth: '100%',
          verticalAlign: 'middle',
        }}
      >
        {iconForNode(node)}
        <span
          style={{
            maxWidth: node.type === 'root' ? 220 : 260,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            verticalAlign: 'middle',
          }}
        >
          {node.title}
        </span>
        <Tag style={{ marginLeft: 8 }} color={node.type === 'document' ? 'blue' : 'default'}>
          {node.type === 'root' ? `${node.count} 用例` : node.count}
        </Tag>
      </span>
    ),
    children: node.children.length > 0 ? node.children.map(toAntTreeNode) : undefined,
    isLeaf: node.children.length === 0,
  };
}

const CaseAssetTree: React.FC<CaseAssetTreeProps> = ({
  tree,
  selectedKey,
  onSelect,
  searchPlaceholder = '搜索模块/分支',
  emptyDescription = '暂无数据',
  height = 520,
  maxHeight = 'calc(100vh - 380px)',
}) => {
  const [keyword, setKeyword] = useState('');
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);

  const visibleRoot = useMemo(
    () => filterCaseAssetTree(tree.root, keyword, tree.caseMap),
    [tree, keyword],
  );
  const treeData = useMemo(() => (visibleRoot ? [toAntTreeNode(visibleRoot)] : []), [visibleRoot]);
  const allTreeKeys = useMemo(
    () => (visibleRoot ? collectCaseAssetKeys(visibleRoot) : []),
    [visibleRoot],
  );
  const defaultExpandedKeys = useMemo(() => getDefaultExpandedKeys(tree.root), [tree.root]);

  useEffect(() => {
    if (keyword.trim()) {
      setExpandedKeys(allTreeKeys);
      return;
    }
    setExpandedKeys(defaultExpandedKeys);
  }, [keyword, allTreeKeys, defaultExpandedKeys]);

  if (tree.root.children.length === 0) {
    return <Empty description={emptyDescription} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Input.Search
        allowClear
        size="small"
        placeholder={searchPlaceholder}
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
      />
      <Space size={8} wrap>
        <Button size="small" onClick={() => setExpandedKeys(collectCaseAssetKeys(tree.root))}>
          展开全部
        </Button>
        <Button size="small" onClick={() => setExpandedKeys([])}>
          收起全部
        </Button>
      </Space>
      {treeData.length > 0 ? (
        <div style={{ maxHeight, minHeight: 320, overflow: 'auto', paddingRight: 4 }}>
          <Tree
            treeData={treeData}
            expandedKeys={expandedKeys}
            onExpand={(keys) => setExpandedKeys(keys)}
            onSelect={(keys) => onSelect(keys.length > 0 ? String(keys[0]) : tree.root.key)}
            selectedKeys={[selectedKey]}
            height={height}
          />
        </div>
      ) : (
        <Empty description="无匹配节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </Space>
  );
};

export default CaseAssetTree;
