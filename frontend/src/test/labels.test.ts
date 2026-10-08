import { describe, expect, it } from 'vitest'
import {
  ACTIVITY_REPLAY_WINDOW_MS,
  appendActivity,
  analyzerSourceName,
  categoryNoun,
  categoryTitle,
  dimensionLabel,
  severityLabel,
  severitySymbol,
  statusLabel,
  translateEvent,
  whyItMatters,
  type ActivityEntry,
} from '../utils/labels'
import type { ProjectEvent } from '../hooks/useProjectEvents'

const event = (overrides: Partial<ProjectEvent> & { type: string }): ProjectEvent => ({
  project_id: 7,
  ...overrides,
} as ProjectEvent)

describe('human-readable labels', () => {
  it('maps analyzer categories to plain nouns', () => {
    expect(categoryNoun('security')).toBe('Security')
    expect(categoryNoun('testing')).toBe('Testing')
    expect(categoryNoun('dependency')).toBe('Dependencies')
    expect(categoryNoun('some_unknown_category')).toBe('Some Unknown Category')
  })

  it('gives findings a plain-language title with an analyzer-specific fallback', () => {
    expect(categoryTitle({ category: 'security', analyzer_source: 'secret_detector' })).toBe('Hard-coded secret detected')
    expect(categoryTitle({ category: 'testing', analyzer_source: 'test_inventory' })).toBe('Tests are missing')
    expect(categoryTitle({ category: 'security', analyzer_source: 'unknown_analyzer' })).toBe('Security issue')
  })

  it('describes why each analyzer finding matters', () => {
    expect(whyItMatters({ category: 'security', analyzer_source: 'secret_detector' })).toMatch(/credential/i)
    expect(whyItMatters({ category: 'testing', analyzer_source: 'test_inventory' })).toMatch(/regressions/i)
    expect(whyItMatters({ category: 'security', analyzer_source: 'brand_new_analyzer' })).toContain('brand new analyzer')
  })

  it('names analyzer sources for display', () => {
    expect(analyzerSourceName('secret_detector')).toBe('Secret detector')
    expect(analyzerSourceName('git_history')).toBe('Git history analyzer')
    expect(analyzerSourceName('some_future_analyzer')).toBe('Some Future Analyzer')
  })

  it('normalizes lifecycle statuses to the allowed display set', () => {
    expect(statusLabel('open')).toBe('ACTIVE')
    expect(statusLabel('OPEN')).toBe('ACTIVE')
    expect(statusLabel('NEW')).toBe('NEW')
    expect(statusLabel('REOPENED')).toBe('REOPENED')
    expect(statusLabel('RESOLVED')).toBe('RESOLVED')
    expect(statusLabel(null)).toBe('ACTIVE')
    expect(statusLabel(undefined)).toBe('ACTIVE')
  })

  it('renders severity as a symbol plus a text label so colour is never the only signal', () => {
    expect(severitySymbol('critical')).toBe('●')
    expect(severitySymbol('high')).toBe('▲')
    expect(severitySymbol('medium')).toBe('■')
    expect(severitySymbol('low')).toBe('○')
    expect(severityLabel('critical')).toBe('CRITICAL')
    expect(severityLabel(null)).toBe('MEDIUM')
  })

  it('uses plain-language DNA dimension labels', () => {
    expect(dimensionLabel('testing_deficiency')).toBe('Testing problems')
    expect(dimensionLabel('security_risk')).toBe('Security risk')
    expect(dimensionLabel('integration_fragility')).toBe('Integration fragility')
    expect(dimensionLabel('unknown_dimension')).toBe('Unknown Dimension')
  })
})

describe('SSE event translators', () => {
  it('never surfaces raw technical event names', () => {
    const types = [
      'project.changed', 'analysis.started', 'analysis.completed', 'analysis.failed',
      'finding.created', 'finding.updated', 'finding.resolved', 'requirement.updated',
      'dna.updated', 'prediction.updated', 'llm.explanation.completed', 'monitoring.status',
    ]
    for (const type of types) {
      const message = translateEvent(event({ type, finding: { category: 'security', severity: 'high' } }), 0).message
      expect(message).not.toContain('.')
      expect(message).not.toMatch(/^[a-z]+\.[a-z]+/)
      expect(message.length).toBeGreaterThan(0)
    }
  })

  it('explains findings with category and severity instead of event codes', () => {
    const created = translateEvent(event({ type: 'finding.created', finding: { category: 'testing', severity: 'critical' } }), 0)
    expect(created.message).toBe('New critical testing issue detected')
    const updated = translateEvent(event({ type: 'finding.updated', finding: { category: 'dependency', severity: 'medium' } }), 1)
    expect(updated.message).toBe('Dependencies issue updated (medium)')
    const resolved = translateEvent(event({ type: 'finding.resolved', finding: { category: 'security', severity: 'high' } }), 2)
    expect(resolved.message).toBe('Security issue resolved')
  })

  it('reports monitoring status and analysis progress in plain language', () => {
    expect(translateEvent(event({ type: 'monitoring.status', status: 'active' }), 0).message).toBe('Live monitoring is active')
    expect(translateEvent(event({ type: 'monitoring.status', status: 'paused' }), 0).message).toBe('Live monitoring paused')
    expect(translateEvent(event({ type: 'analysis.started' }), 0).message).toBe('Analyzing the latest changes')
    expect(translateEvent(event({ type: 'analysis.failed', message: 'boom' }), 0).message).toBe('Analysis failed while scanning changes')
  })

  it('attaches the first changed file and prefers the server timestamp', () => {
    const entry = translateEvent(event({
      type: 'project.changed',
      files: ['src/auth/login.py', 'README.md'],
      timestamp: '2026-10-08T10:00:00Z',
    }), 0)
    expect(entry.file).toBe('src/auth/login.py')
    expect(entry.time.toISOString()).toBe('2026-10-08T10:00:00.000Z')
  })

  it('builds a content key that does not change when the event is replayed', () => {
    const payload = {
      type: 'finding.created',
      finding: { category: 'security', severity: 'high', fingerprint: 'fp-1' },
      timestamp: '2026-10-08T10:00:00Z',
      files: ['src/app.py'],
    }
    const first = translateEvent(event(payload), 0)
    const replay = translateEvent(event(payload), 41)
    expect(first.key).toBe(replay.key)
  })
})

describe('activity replay deduplication', () => {
  const entry = (key: string, receivedAt: number): ActivityEntry => ({
    key,
    time: new Date(),
    message: 'Analyzing the latest changes',
    receivedAt,
  })

  it('drops a replayed event inside the replay window', () => {
    const first = entry('k', 1_000)
    const next = appendActivity([first], { ...first, receivedAt: 2_000 }, 2_500)
    expect(next).toHaveLength(1)
    expect(next[0]).toBe(first)
  })

  it('allows the same content again after the replay window has passed', () => {
    const first = entry('k', 1_000)
    const later = appendActivity([first], { ...first, receivedAt: 999_999 }, 1_000 + ACTIVITY_REPLAY_WINDOW_MS + 1)
    expect(later).toHaveLength(2)
  })

  it('keeps distinct events and caps the feed length', () => {
    let feed: ActivityEntry[] = []
    for (let index = 0; index < 60; index += 1) feed = appendActivity(feed, entry(`key-${index}`, index * 10))
    expect(feed).toHaveLength(50)
    expect(feed[0].key).toBe('key-59')
    expect(new Set(feed.map(item => item.key)).size).toBe(50)
  })
})