export interface ProjectNotification {
  id: string
  type: string
  title: string
  detail: string
  createdAt: string
  seen: boolean
}

const STORAGE_KEY = 'mistiq.project.notifications'
const MAX_NOTIFICATIONS = 50

function read(): ProjectNotification[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(parsed) ? parsed as ProjectNotification[] : []
  } catch {
    return []
  }
}

export function getProjectNotifications(): ProjectNotification[] {
  return read()
}

export function markProjectNotificationsSeen(ids?: string[]) {
  const selected = ids ? new Set(ids) : null
  const next = read().map(item => selected ? (selected.has(item.id) ? { ...item, seen: true } : item) : { ...item, seen: true })
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: JSON.stringify(next) }))
}

function recordKey(event: { type?: string; [key: string]: unknown }): string {
  const type = String(event.type || '')
  const finding = event.finding
  if (finding && typeof finding === 'object') {
    const fingerprint = (finding as { fingerprint?: unknown }).fingerprint
    if (fingerprint !== undefined && fingerprint !== null && String(fingerprint) !== '') {
      return `${type}:fingerprint:${String(fingerprint)}`
    }
  }
  for (const field of ['review_id', 'current_commit_sha', 'related_commit'] as const) {
    const value = event[field]
    if (value !== undefined && value !== null && String(value) !== '') return `${type}:${field}:${String(value)}`
  }
  if (event.timestamp !== undefined && event.timestamp !== null && String(event.timestamp) !== '') {
    return `${type}:at:${String(event.timestamp)}`
  }
  return `${type}:at:${new Date().toISOString().slice(0, 16)}`
}

export function recordProjectNotification(event: { type?: string; [key: string]: unknown }) {
  const type = String(event.type || '')
  const messages: Record<string, [string, string]> = {
    'finding.created': ['New engineering risk', 'A new finding was detected in the connected project.'],
    'finding.updated': ['Finding updated', 'A known finding changed after the latest analysis.'],
    'finding.resolved': ['Finding resolved', 'A previously reported finding is no longer present.'],
    'analysis.completed': ['Analysis completed', 'The latest project changes were analyzed successfully.'],
    'analysis.failed': ['Monitoring error', String(event.message || 'The latest project analysis failed.')],
    'prediction.updated': ['Prediction refreshed', 'Apex-APR refreshed its next-failure estimate.'],
    'dna.updated': ['Engineering profile changed', 'Failure DNA was updated from the latest evidence.'],
    'project.changed': ['Project changed', 'ApexIQ detected a new project or Git change.'],
  }
  const message = messages[type]
  if (!message) return
  const key = recordKey(event)
  const current = read()
  if (current.some(existing => existing.id === key)) return
  const item: ProjectNotification = {
    id: key,
    type,
    title: message[0],
    detail: message[1],
    createdAt: new Date().toISOString(),
    seen: false,
  }
  const next = [item, ...current].slice(0, MAX_NOTIFICATIONS)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: JSON.stringify(next) }))
}

export function persistProjectContext(context: Record<string, unknown>) {
  localStorage.setItem('mistiq.project.context', JSON.stringify(context))
}

export function clearProjectContext() {
  localStorage.removeItem('mistiq.project.context')
  window.dispatchEvent(new StorageEvent('storage', { key: 'mistiq.project.context', newValue: null }))
}

export function clearProjectNotifications() {
  localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY, newValue: '[]' }))
}
