/**
 * 通知铃铛组件 — Header 右侧
 * 功能：未读 Badge + 点击弹出 Drawer + 标记已读 + 全部已读
 * 轮询未读数（30s 间隔）
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Drawer,
  Empty,
  List,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { BellOutlined, CheckOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from '../services/notificationApi';
import type { Notification, PaginatedData } from '../types';
import { buildNotificationBatchUrl } from '../utils/batchReturn';

const { Text } = Typography;

const POLL_INTERVAL = 10000; // 10s（设计决策 §4）

const NOTIFICATION_TYPE_MAP: Record<string, { color: string; label: string }> = {
  batch_completed: { color: 'green', label: '完成' },
  batch_failed: { color: 'red', label: '失败' },
  batch_suspended: { color: 'orange', label: '暂停' },
};

const NotificationBell: React.FC = () => {
  const navigate = useNavigate();

  const [unreadCount, setUnreadCount] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  const pollRef = useRef<number | null>(null);

  // ─── 轮询未读数 + visibilitychange 暂停 ───
  const fetchUnread = useCallback(async () => {
    try {
      const res = await getUnreadCount();
      setUnreadCount(res.count);
    } catch {
      // 静默失败
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current !== null) return;
    pollRef.current = window.setInterval(fetchUnread, POLL_INTERVAL);
  }, [fetchUnread]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    fetchUnread();
    startPolling();

    const handleVisibility = () => {
      if (document.hidden) {
        stopPolling();
      } else {
        fetchUnread(); // 恢复时立即拉一次
        startPolling();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      stopPolling();
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [fetchUnread, startPolling, stopPolling]);

  // ─── 加载通知列表 ───
  const fetchList = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res: PaginatedData<Notification> = await listNotifications({ page: p, per_page: 20 });
      setNotifications(res.items);
      setTotal(res.total);
      setPage(res.page);
    } finally {
      setLoading(false);
    }
  }, []);

  // 打开 Drawer 时加载列表
  const handleOpen = () => {
    setDrawerOpen(true);
    fetchList(1);
  };

  // ─── 标记单条已读 ───
  const handleMarkRead = async (notificationId: string) => {
    try {
      await markNotificationRead(notificationId);
      setNotifications((prev) =>
        prev.map((n) => (n.id === notificationId ? { ...n, read: true } : n)),
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      message.error('标记失败');
    }
  };

  // ─── 全部标记已读 ───
  const handleMarkAllRead = async () => {
    setMarkingAll(true);
    try {
      const res = await markAllNotificationsRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
      message.success(`已标记 ${res.updated_count} 条为已读`);
    } catch {
      message.error('操作失败');
    } finally {
      setMarkingAll(false);
    }
  };

  // ─── 点击通知跳转 ───
  const handleClick = (notification: Notification) => {
    if (!notification.read) {
      handleMarkRead(notification.id);
    }
    if (notification.target_type === 'batch' && notification.target_id) {
      setDrawerOpen(false);
      navigate(buildNotificationBatchUrl(notification.target_id, notification.type));
    }
  };

  return (
    <>
      <Badge count={unreadCount} size="small" offset={[-4, 4]}>
        <BellOutlined
          style={{ fontSize: 20, cursor: 'pointer' }}
          onClick={handleOpen}
        />
      </Badge>

      <Drawer
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>通知中心</span>
            {unreadCount > 0 && (
              <Button
                size="small"
                icon={<CheckOutlined />}
                onClick={handleMarkAllRead}
                loading={markingAll}
              >
                全部已读
              </Button>
            )}
          </div>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={420}
      >
        <List
          loading={loading}
          dataSource={notifications}
          locale={{ emptyText: <Empty description="暂无通知" /> }}
          pagination={
            total > 20
              ? {
                  current: page,
                  pageSize: 20,
                  total,
                  onChange: fetchList,
                  size: 'small',
                }
              : false
          }
          renderItem={(item) => {
            const typeCfg = NOTIFICATION_TYPE_MAP[item.type] || { color: 'default', label: item.type };
            return (
              <List.Item
                style={{
                  cursor: 'pointer',
                  backgroundColor: item.read ? 'transparent' : '#f6ffed',
                  padding: '12px 16px',
                  borderRadius: 4,
                  marginBottom: 4,
                }}
                onClick={() => handleClick(item)}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag color={typeCfg.color}>{typeCfg.label}</Tag>
                      <Text strong={!item.read}>{item.title}</Text>
                    </Space>
                  }
                  description={
                    <div>
                      {item.body && <div style={{ marginBottom: 4 }}>{item.body}</div>}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {new Date(item.created_at).toLocaleString('zh-CN')}
                      </Text>
                    </div>
                  }
                />
                {!item.read && (
                  <Badge status="processing" />
                )}
              </List.Item>
            );
          }}
        />
      </Drawer>
    </>
  );
};

export default NotificationBell;
