import { request } from './client'
import type { NotificationItem } from '../types/projectReview'

export async function fetchNotifications(options?: {
  projectId?: number
  seen?: boolean
  limit?: number
}): Promise<NotificationItem[]> {
  const query = new URLSearchParams()
  if (options?.projectId !== undefined) query.set('project_id', String(options.projectId))
  if (options?.seen !== undefined) query.set('seen', String(options.seen))
  if (options?.limit !== undefined) query.set('limit', String(options.limit))

  const qs = query.toString() ? `?${query.toString()}` : ''
  return request<NotificationItem[]>(`/notifications${qs}`)
}

export async function fetchUnreadCount(projectId?: number): Promise<number> {
  const query = new URLSearchParams()
  if (projectId !== undefined) query.set('project_id', String(projectId))
  const qs = query.toString() ? `?${query.toString()}` : ''
  const data = await request<{ unread_count: number }>(`/notifications/unread-count${qs}`)
  return data.unread_count
}

export async function markNotificationRead(notificationId: number): Promise<void> {
  await request<{ status: string }>(`/notifications/${notificationId}/read`, {
    method: 'POST',
  })
}

export async function markAllNotificationsRead(projectId?: number): Promise<number> {
  const query = new URLSearchParams()
  if (projectId !== undefined) query.set('project_id', String(projectId))
  const qs = query.toString() ? `?${query.toString()}` : ''
  const data = await request<{ status: string; marked_read_count: number }>(`/notifications/mark-all-read${qs}`, {
    method: 'POST',
  })
  return data.marked_read_count
}

