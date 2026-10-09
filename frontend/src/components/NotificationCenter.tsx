import { useEffect, useRef, useState } from 'react'
import { getProjectNotifications, markProjectNotificationsSeen, type ProjectNotification } from '../utils/projectNotifications'
import { BellIcon, CheckCircleIcon } from './ui/Icons'

function formatTimeAgo(isoString: string): string {
  try {
    const past = new Date(isoString).getTime()
    const now = Date.now()
    const diffSec = Math.max(0, Math.floor((now - past) / 1000))
    if (diffSec < 60) return `${diffSec}s ago`
    const diffMin = Math.floor(diffSec / 60)
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHours = Math.floor(diffMin / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  } catch {
    return 'recently'
  }
}

function getSeverityBadge(type: string, detail: string): { label: string; modifier: string; dot: string } {
  const text = (type + ' ' + detail).toLowerCase()
  if (text.includes('critical')) return { label: 'CRITICAL', modifier: 'critical', dot: '🔴' }
  if (text.includes('high')) return { label: 'HIGH', modifier: 'high', dot: '🟠' }
  if (text.includes('medium')) return { label: 'MEDIUM', modifier: 'medium', dot: '🟡' }
  if (text.includes('low')) return { label: 'LOW', modifier: 'low', dot: '🔵' }
  if (type === 'finding.resolved') return { label: 'RESOLVED', modifier: 'resolved', dot: '🟢' }
  return { label: 'SIGNAL', modifier: 'info', dot: '⚪' }
}

export interface NotificationCenterProps {
  isOpen?: boolean
  onToggle?: () => void
  onClose?: () => void
  showTrigger?: boolean
}

export function NotificationCenter({
  isOpen: externalOpen,
  onToggle: externalToggle,
  onClose: externalClose,
  showTrigger = true,
}: NotificationCenterProps = {}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [tab, setTab] = useState<'new' | 'seen'>('new')
  const [items, setItems] = useState<ProjectNotification[]>(getProjectNotifications)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const isControlled = externalOpen !== undefined
  const open = isControlled ? externalOpen : internalOpen

  useEffect(() => {
    const refresh = () => setItems(getProjectNotifications())
    window.addEventListener('storage', refresh)
    return () => window.removeEventListener('storage', refresh)
  }, [])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        if (isControlled) {
          externalClose?.()
        } else {
          setInternalOpen(false)
        }
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open, isControlled, externalClose])

  function handleOpenTransition() {
    const unread = items.filter(item => !item.seen)
    if (unread.length > 0) {
      markProjectNotificationsSeen(unread.map(item => item.id))
      setItems(getProjectNotifications())
    }
  }

  function toggleOpen() {
    if (isControlled) {
      if (!open) handleOpenTransition()
      externalToggle?.()
    } else {
      setInternalOpen(value => {
        const next = !value
        if (next) handleOpenTransition()
        return next
      })
    }
  }

  function handleClose() {
    if (isControlled) {
      externalClose?.()
    } else {
      setInternalOpen(false)
    }
  }

  function handleNotificationClick(id: string) {
    markProjectNotificationsSeen([id])
    setItems(getProjectNotifications())
  }

  function handleMarkAllSeen() {
    markProjectNotificationsSeen()
    setItems(getProjectNotifications())
  }

  const newItems = items.filter(item => !item.seen)
  const seenItems = items.filter(item => item.seen)
  const visible = tab === 'new' ? newItems : seenItems

  return (
    <div className="notification-center relative" ref={dropdownRef}>
      {showTrigger && (
        <button
          className="header-icon-button notif-trigger"
          aria-label={`Notifications${newItems.length ? `, ${newItems.length} new` : ''}`}
          aria-expanded={open}
          onClick={toggleOpen}
          title="Open Notifications"
        >
          <span aria-hidden="true" className="notif-icon-wrap">
            <BellIcon size={16} />
          </span>
          {newItems.length > 0 && (
            <b className="notif-badge">{newItems.length > 99 ? '99+' : newItems.length}</b>
          )}
        </button>
      )}

      {open && (
        <section className="notification-panel" aria-label="Notification center">
          <div className="notification-panel-head">
            <div className="notification-head-text">
              <span className="notif-eyebrow">OBSERVABILITY SIGNALS</span>
              <h2>Notifications</h2>
            </div>
            <div className="notification-head-actions">
              <button
                type="button"
                className="text-button mark-all-btn"
                onClick={handleMarkAllSeen}
                title="Mark all notifications as seen"
              >
                <CheckCircleIcon size={13} className="inline mr-1 text-primary" />
                Mark all seen
              </button>
              <button
                type="button"
                className="notif-close-btn"
                onClick={handleClose}
                aria-label="Close notification panel"
              >
                ×
              </button>
            </div>
          </div>

          <div className="notification-tabs">
            <button
              type="button"
              className={tab === 'new' ? 'active' : ''}
              onClick={() => setTab('new')}
            >
              NEW ({newItems.length})
            </button>
            <button
              type="button"
              className={tab === 'seen' ? 'active' : ''}
              onClick={() => setTab('seen')}
            >
              SEEN ({seenItems.length})
            </button>
          </div>

          <div className="notification-list-wrap">
            {visible.length > 0 ? (
              <ul className="notif-card-list">
                {visible.map(item => {
                  const badge = getSeverityBadge(item.type, item.title + ' ' + item.detail)
                  return (
                    <li
                      key={item.id}
                      className={`notif-card ${item.seen ? 'notif-seen' : 'notif-unread'}`}
                      onClick={() => handleNotificationClick(item.id)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="notif-card-header">
                        <span className={`notif-sev-badge notif-sev-${badge.modifier}`}>
                          <span className="notif-dot-char" aria-hidden="true">{badge.dot}</span> {badge.label}
                        </span>
                        <time dateTime={item.createdAt} title={new Date(item.createdAt).toLocaleString()}>
                          {formatTimeAgo(item.createdAt)}
                        </time>
                      </div>
                      <div className="notif-card-body">
                        <strong>{item.title}</strong>
                        <p>{item.detail}</p>
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <div className="notification-empty">
                <span className="empty-notif-icon">✓</span>
                <p>{tab === 'new' ? 'No new project signals.' : 'No notifications have been seen yet.'}</p>
                <small className="text-muted">Live analyzer and monitoring events will appear here in real-time.</small>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
