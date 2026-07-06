import React, { useMemo } from 'react';
import { Space, Table, Tag } from 'antd';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';

import type { CaseTreeCase, ReviewStatus } from '../../types';
import {
  PRIORITY_COLOR,
  REVIEW_TAG,
  getTrustDisplay,
  renderCaseQualityTags,
} from './caseDisplay';

interface CaseAssetTableProps {
  cases: CaseTreeCase[];
  titleColumnLabel?: string;
  titleAsLink?: boolean;
  showIterationTag?: boolean;
  onOpenCase?: (caseId: string) => void;
  renderActions?: (record: CaseTreeCase) => React.ReactNode;
  actionColumnWidth?: number;
  pagination?: TablePaginationConfig;
  rowClickToOpen?: boolean;
  highlightedCaseId?: string;
}

function getTitleClampStyle(maxLines = 2): React.CSSProperties {
  return {
    display: '-webkit-box',
    WebkitBoxOrient: 'vertical',
    WebkitLineClamp: maxLines,
    overflow: 'hidden',
    whiteSpace: 'normal',
    lineHeight: 1.45,
  };
}

const CaseAssetTable: React.FC<CaseAssetTableProps> = ({
  cases,
  titleColumnLabel = '用例标题',
  titleAsLink = false,
  showIterationTag = false,
  onOpenCase,
  renderActions,
  actionColumnWidth = 132,
  pagination,
  rowClickToOpen = false,
  highlightedCaseId,
}) => {
  const hasActions = Boolean(renderActions);
  const tableScrollX = hasActions ? 560 + actionColumnWidth : 760;
  const columns: ColumnsType<CaseTreeCase> = useMemo(() => {
    const tableColumns: ColumnsType<CaseTreeCase> = [
      {
        title: titleColumnLabel,
        dataIndex: 'title',
        key: 'title',
        width: hasActions ? 240 : 360,
        render: (text: string, record) => {
          const titleStyle = getTitleClampStyle();
          const titleNode = titleAsLink ? (
            <a
              title={text}
              onClick={() => onOpenCase?.(record.id)}
              style={titleStyle}
            >
              {text}
            </a>
          ) : (
            <span title={text} style={titleStyle}>
              {text}
            </span>
          );
          if (!showIterationTag || record.iteration <= 1) return titleNode;
          return (
            <Space size={4} align="start" style={{ width: '100%' }}>
              <Tag color="purple" style={{ margin: 0, flexShrink: 0 }}>
                已重写
              </Tag>
              <span style={{ minWidth: 0, flex: 1 }}>
                {titleNode}
              </span>
            </Space>
          );
        },
      },
      {
        title: '优先级',
        dataIndex: 'priority',
        key: 'priority',
        width: hasActions ? 62 : 74,
        render: (val: string) => <Tag color={PRIORITY_COLOR[val] || 'default'}>{val}</Tag>,
      },
      {
        title: '质量',
        key: 'quality',
        width: hasActions ? 118 : 138,
        render: (_, record) => renderCaseQualityTags(record),
      },
      {
        title: '可信度',
        dataIndex: 'trust_level',
        key: 'trust_level',
        width: hasActions ? 72 : 86,
        render: (val: number) => {
          const { color, label } = getTrustDisplay(val);
          return <span style={{ color, fontWeight: 600 }}>{label}</span>;
        },
      },
      {
        title: '状态',
        dataIndex: 'review_status',
        key: 'review_status',
        width: hasActions ? 68 : 92,
        render: (val: ReviewStatus) => {
          const cfg = REVIEW_TAG[val];
          return <Tag color={cfg.color}>{cfg.label}</Tag>;
        },
      },
    ];

    if (renderActions) {
      tableColumns.push({
        title: '操作',
        key: 'actions',
        width: actionColumnWidth,
        fixed: 'right',
        render: (_, record) => renderActions(record),
      });
    }

    return tableColumns;
  }, [actionColumnWidth, hasActions, onOpenCase, renderActions, showIterationTag, titleAsLink, titleColumnLabel]);

  return (
    <Table<CaseTreeCase>
      rowKey="id"
      columns={columns}
      dataSource={cases}
      pagination={pagination}
      size="small"
      scroll={{ x: tableScrollX }}
      onRow={(record) => ({
        onClick: rowClickToOpen ? () => onOpenCase?.(record.id) : undefined,
        style: rowClickToOpen ? { cursor: 'pointer' } : undefined,
      })}
      rowClassName={(record) => (record.id === highlightedCaseId ? 'case-asset-table-row-highlight' : '')}
    />
  );
};

export default CaseAssetTable;
