import { describe, expect, it } from 'vitest'
import type { FailureEvent } from '../types/projectReview'
import {
  applyFindingEvent,
  dedupeActiveFindings,
  dedupeRecommendations,
  findingDisplayKey,
  findingLocations,
  recommendationKey,
  seedFindings,
} from '../utils/findingDedup'

const base: FailureEvent = {
  category: 'security', severity: 'high', evidence: 'Secret at src/auth.py:12, src/legacy.py:88', analyzer_source: 'secret_detector',
  remediation: 'Rotate the leaked key', status: 'OPEN', component: 'auth', file: 'src/auth.py', line: 12,
}

function eventOf(overrides: Partial<FailureEvent> & { fingerprint?: string } = {}): FailureEvent & { fingerprint?: string } {
  return { ...base, ...overrides }
}

describe('findingDisplayKey', () => {
  it('is stable between a delivered finding and the analysis event for the same material', () => {
    const seeded = eventOf({ status: 'OPEN' })
    const delivered = eventOf({ status: 'NEW', fingerprint: 'fp-abc' })
    expect(findingDisplayKey(seeded)).toBe(findingDisplayKey(delivered))
  })

  it('treats missing and null location fields as the same empty material slots (matching backend fingerprint_event)', () => {
    const analysisEvent = { ...eventOf(), component: undefined, file: undefined, line: undefined }
    const persistedFinding = { ...eventOf(), component: null, file: null, line: null }
    expect(findingDisplayKey(analysisEvent)).toBe(findingDisplayKey(persistedFinding))
  })

  it('ignores case and surrounding whitespace in the material', () => {
    expect(findingDisplayKey(eventOf({ category: 'SecuriTY' }))).toBe(findingDisplayKey(eventOf({ category: 'security' })))
    expect(findingDisplayKey(eventOf({ evidence: '  Secret at src/auth.py:12, src/legacy.py:88  ' }))).toBe(findingDisplayKey(eventOf()))
  })

  it('distinguishes findings that differ on evidence material', () => {
    expect(findingDisplayKey(eventOf())).not.toBe(findingDisplayKey(eventOf({ evidence: 'Secret at src/other.py:3' })))
  })
})

describe('seed and live finding stream deduplication', () => {
  it('does not create a duplicate when the same finding arrives as a live event after the analysis seed', () => {
    const findings = seedFindings([eventOf({ status: 'OPEN' })])
    const updated = applyFindingEvent(findings, eventOf({ status: 'NEW', fingerprint: 'fp-abc' }), 'finding.detected')
    expect(Object.keys(updated)).toHaveLength(1)
  })

  it('resolves a finding by removing the same material entry', () => {
    const findings = seedFindings([eventOf({ status: 'OPEN' })])
    const resolved = applyFindingEvent(findings, eventOf({ status: 'RESOLVED', fingerprint: 'fp-abc' }), 'finding.resolved')
    expect(resolved).toEqual({})
  })

  it('keeps distinct findings separate', () => {
    const findings = seedFindings([eventOf()])
    const updated = applyFindingEvent(findings, eventOf({ category: 'testing', evidence: 'No tests for src/app.js', component: 'app' }), 'finding.detected')
    expect(Object.keys(updated)).toHaveLength(2)
  })
})

describe('dedupeActiveFindings', () => {
  it('keeps the latest active lifecycle state of each finding and drops resolved rows', () => {
    const duplicates = dedupeActiveFindings([
      eventOf({ status: 'OPEN' }),
      eventOf({ status: 'NEW', fingerprint: 'fp-abc' }),
      eventOf({ status: 'RESOLVED', fingerprint: 'fp-abc' }),
    ])
    expect(duplicates).toHaveLength(1)
    expect(duplicates[0].status).toBe('NEW')
    expect(duplicates[0].fingerprint).toBe('fp-abc')
  })

  it('drops resolved findings entirely when no active occurrence remains', () => {
    const active = dedupeActiveFindings([eventOf({ status: 'RESOLVED', fingerprint: 'fp-x' })])
    expect(active).toHaveLength(0)
  })
})

describe('dedupeRecommendations', () => {
  it('keeps one recommendation per normalized remediation, preferring the first occurrence', () => {
    const recommendations = dedupeRecommendations([
      eventOf({ remediation: 'Pin runtime dependencies' }),
      eventOf({ category: 'dependency', evidence: 'Other', status: 'NEW', remediation: '  pin   runtime DEPENDENCIES  ' }),
      eventOf({ category: 'security', evidence: 'More', status: 'OPEN', remediation: 'Rotate the leaked key' }),
    ])
    expect(recommendations).toHaveLength(2)
    expect(recommendations[0].remediation).toBe('Pin runtime dependencies')
    expect(recommendations[1].remediation).toBe('Rotate the leaked key')
  })

  it('drops findings without remediation and caps at five entries', () => {
    const six = Array.from({ length: 6 }, (_, index) => eventOf({ evidence: `src/f${index}.py:1`, remediation: `Fix item ${index}` }))
    const list = dedupeRecommendations([...six, eventOf({ remediation: '' })])
    expect(list).toHaveLength(5)
    expect(list.every(item => item.remediation)).toBeTruthy()
  })
})

describe('recommendationKey', () => {
  it('normalizes casing and whitespace for comparison', () => {
    expect(recommendationKey('Pin  runtime  deps')).toBe(recommendationKey('pin runtime deps'))
  })
})

describe('findingLocations', () => {
  it('uses file:line as the primary location and treats further evidence paths as additional', () => {
    const { primary, component, additional } = findingLocations(eventOf())
    expect(primary).toBe('src/auth.py:12')
    expect(component).toBe('auth')
    expect(additional).toContain('src/legacy.py:88')
  })

  it('falls back to the first evidence location when there is no file', () => {
    const { primary, additional } = findingLocations({ ...eventOf(), file: undefined, line: undefined })
    expect(primary).toBe('src/auth.py:12')
    expect(additional).toEqual(['src/legacy.py:88'])
  })

  it('falls back to component when no path can be located', () => {
    const { primary, component } = findingLocations({ ...eventOf(), file: undefined, line: undefined, evidence: 'Repeated assertion gaps' })
    expect(primary).toBe('auth')
    expect(component).toBeNull()
  })

  it('does not report the primary location again in additional evidence', () => {
    const { additional } = findingLocations(eventOf({ file: 'src/auth.py', line: 12, evidence: 'Secret at src/auth.py:12' }))
    expect(additional).not.toContain('src/auth.py:12')
  })
})