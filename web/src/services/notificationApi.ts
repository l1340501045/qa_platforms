/**
 * 通知 API — 对齐 /api/v1/notifications
 */
import api from './api';
import type {
  MarkAllReadResponse,
  Notification,
  PaginatedData,
  UnreadCountResponse,
} from '../types';

export interface NotificationListParams {
  page?: number;
  per_page?: number;
  is_read?: boolean;
}

/** 获取未读通知数量 */
export async function getUnreadCount(): Promise<UnreadCountResponse> {
  const res = await api.get('/notifications/unread-count');
  return res.data;
}

/** 分页获取通知列表 */
export async function listNotifications(
  params?: NotificationListParams,
): Promise<PaginatedData<Notification>> {
  const res = await api.get('/notifications', { params });
  return res.data;
}

/** 标记单条通知为已读 */
export async function markNotificationRead(
  notificationId: string,
): Promise<{ id: string; read: boolean }> {
  const res = await api.patch(`/notifications/${notificationId}/read`);
  return res.data;
}

/** 全部标记已读 */
export async function markAllNotificationsRead(): Promise<MarkAllReadResponse> {
  const res = await api.post('/notifications/mark-all-read');
  return res.data;
}
