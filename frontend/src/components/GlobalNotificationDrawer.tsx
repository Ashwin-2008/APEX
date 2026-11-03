import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchNotifications, fetchUnreadCount, markAllNotificationsRead, markNotificationRead } from '../api/notificationsApi'
import { useProject } from '../context/ProjectContext'
import type { NotificationItem } from '../types/projectReview'
import { BellIcon } from './ui/Icons'

export function GlobalNotificationDrawer() {
  const [open, setOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [filterUnread, setFilterUnread] = useState(false)
  const [loading, setLoading] = useState(false)
  const drawerRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { selectProject } = useProject()

  const refreshCountsAndNotifs = async () => {
    try {
      const count = await fetchUnreadCount()
      setUnreadCount(count)
      if (open) {
        setLoading(true)
        const list = await fetchNotifications({ seen: filterUnread ? false : undefined })
        setNotifications(list)
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshCountsAndNotifs()
    const interval = setInterval(refreshCountsAndNotifs, 10000)
    return () => clearInterval(interval)
  }, [open, filterUnread])

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  const handleMarkRead = async (id: number) => {
    try {
      await markNotificationRead(id)
      setNotifications(prev => prev.map(n => (n.id === id ? { ...n, seen: true } : n)))
      setUnreadCount(prev => Math.max(0, prev - 1))
    } catch {
      // ignore
    }
  }

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead()
      setNotifications(prev => prev.map(n => ({ ...n, seen: true })))
      setUnreadCount(0)
    } catch {
      // ignore
    }
  }

  const handleNavigateToProject = async (notif: NotificationItem) => {
    if (notif.project_id) {
      await selectProject(notif.project_id)
      navigate('/project-review')
    }
    if (!notif.seen) {
      await handleMarkRead(notif.id)
    }
    setOpen(false)
  }

  return (
    <div className="relative inline-block text-left" ref={drawerRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative p-2 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
        title="View Notifications"
      >
        <BellIcon size={16} />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full border border-slate-900 shadow">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-96 rounded-xl shadow-2xl bg-slate-900 border border-slate-700 py-3 z-50 animate-in fade-in slide-in-from-top-2">
          <div className="px-4 pb-2 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-100">Notifications</span>
              {unreadCount > 0 && (
                <span className="text-[10px] bg-red-500/20 text-red-300 px-1.5 py-0.5 rounded font-mono">
                  {unreadCount} unread
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setFilterUnread(!filterUnread)}
                className={`text-[11px] px-2 py-0.5 rounded ${
                  filterUnread ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Unread only
              </button>
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={handleMarkAllRead}
                  className="text-[11px] text-indigo-400 hover:text-indigo-300 font-medium"
                >
                  Mark all read
                </button>
              )}
            </div>
          </div>

          <div className="max-h-80 overflow-y-auto divide-y divide-slate-800/60">
            {loading ? (
              <div className="py-6 text-center text-xs text-slate-500">Loading notifications…</div>
            ) : notifications.length === 0 ? (
              <div className="py-8 text-center text-xs text-slate-500">
                {filterUnread ? 'No unread notifications' : 'No notifications yet'}
              </div>
            ) : (
              notifications.map(notif => (
                <div
                  key={notif.id}
                  className={`px-4 py-2.5 transition-colors hover:bg-slate-800/60 flex items-start gap-3 ${
                    notif.seen ? 'opacity-70' : 'bg-slate-800/20'
                  }`}
                >
                  <div
                    className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${
                      notif.seen ? 'bg-slate-600' : 'bg-indigo-400'
                    }`}
                  />
                  <div className="flex-1 min-w-0 cursor-pointer" onClick={() => handleNavigateToProject(notif)}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-200 truncate">{notif.title}</span>
                      <span className="text-[10px] text-slate-500 flex-shrink-0 ml-2">
                        {notif.created_at ? new Date(notif.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 line-clamp-2 mt-0.5">{notif.message}</p>
                  </div>
                  {!notif.seen && (
                    <button
                      type="button"
                      onClick={() => handleMarkRead(notif.id)}
                      className="text-[10px] text-slate-500 hover:text-indigo-300 ml-1 flex-shrink-0"
                      title="Mark as read"
                    >
                      ✓
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

