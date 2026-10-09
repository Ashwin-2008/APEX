import { beforeEach, describe, expect, it } from 'vitest'
import {
  getProjectNotifications,
  markProjectNotificationsSeen,
  recordProjectNotification,
} from '../utils/projectNotifications'

const findingEvent = (fingerprint: string) => ({
  type: 'finding.created',
  finding: { fingerprint, category: 'security', severity: 'critical' },
  timestamp: `2026-10-08T10:00:${fingerprint}Z`,
})

describe('project notifications', () => {
  beforeEach(() => { localStorage.clear() })

  it('records a notification as new', () => {
    recordProjectNotification(findingEvent('fp-1'))
    const items = getProjectNotifications()
    expect(items).toHaveLength(1)
    expect(items[0].title).toBe('New engineering risk')
    expect(items[0].seen).toBe(false)
  })

  it('ignores event types that are not user-facing', () => {
    recordProjectNotification({ type: 'monitoring.status', status: 'active' })
    recordProjectNotification({ type: 'analysis.started' })
    expect(getProjectNotifications()).toHaveLength(0)
  })

  it('does not duplicate repeated SSE events for the same finding', () => {
    recordProjectNotification(findingEvent('fp-1'))
    recordProjectNotification(findingEvent('fp-1'))
    recordProjectNotification(findingEvent('fp-1'))
    expect(getProjectNotifications()).toHaveLength(1)
  })

  it('keeps distinct findings as separate notifications', () => {
    recordProjectNotification(findingEvent('fp-1'))
    recordProjectNotification(findingEvent('fp-2'))
    expect(getProjectNotifications()).toHaveLength(2)
  })

  it('deduplicates analysis replays by review id', () => {
    recordProjectNotification({ type: 'analysis.completed', review_id: 4 })
    recordProjectNotification({ type: 'analysis.completed', review_id: 4 })
    recordProjectNotification({ type: 'analysis.completed', review_id: 5 })
    expect(getProjectNotifications()).toHaveLength(2)
  })

  it('marks selected notifications as seen', () => {
    recordProjectNotification(findingEvent('fp-1'))
    recordProjectNotification(findingEvent('fp-2'))
    const [first, second] = getProjectNotifications()
    markProjectNotificationsSeen([first.id])
    const after = getProjectNotifications()
    expect(after.find(item => item.id === first.id)?.seen).toBe(true)
    expect(after.find(item => item.id === second.id)?.seen).toBe(false)
  })

  it('marks every notification as seen', () => {
    recordProjectNotification(findingEvent('fp-1'))
    recordProjectNotification(findingEvent('fp-2'))
    markProjectNotificationsSeen()
    expect(getProjectNotifications().every(item => item.seen)).toBe(true)
  })

  it('survives corrupted stored state', () => {
    localStorage.setItem('mistiq.project.notifications', '{not json')
    expect(getProjectNotifications()).toEqual([])
    recordProjectNotification(findingEvent('fp-1'))
    expect(getProjectNotifications()).toHaveLength(1)
  })

  it('caps the stored history at fifty notifications', () => {
    for (let index = 0; index < 60; index += 1) {
      recordProjectNotification({ type: 'project.changed', current_commit_sha: `commit-${index}`, timestamp: `t-${index}` })
    }
    expect(getProjectNotifications()).toHaveLength(50)
  })
})
