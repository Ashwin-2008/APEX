import type { FailureEvent } from '../types/projectReview'

export type DedupableFinding = FailureEvent & { fingerprint?: string }

export interface DisplayKeySource {
  category?: string | null
  component?: string | null
  file?: string | null
  line?: number | null
  analyzer_source?: string | null
  evidence?: string | null
}

const FINGERPRINT_FIELDS = ['category', 'component', 'file', 'line', 'analyzer_source', 'evidence'] as const

export function findingDisplayKey(finding: DisplayKeySource): string {
  const record = finding as unknown as Record<string, unknown>
  return FINGERPRINT_FIELDS.map(field => {
    const value = record[field]
    const normalized = value === null || value === undefined ? '' : String(value)
    return normalized.trim().toLowerCase()
  }).join('|')
}

export function recommendationKey(remediation: string): string {
  return remediation.replace(/\s+/g, ' ').trim().toLowerCase()
}

export function seedFindings(events: DedupableFinding[]): Record<string, FailureEvent> {
  const seeded: Record<string, FailureEvent> = {}
  for (const event of events) seeded[findingDisplayKey(event)] = event
  return seeded
}

export function applyFindingEvent(
  findings: Record<string, FailureEvent>,
  finding: DedupableFinding,
  eventType: string,
): Record<string, FailureEvent> {
  const key = findingDisplayKey(finding)
  const next = { ...findings }
  if (eventType === 'finding.resolved') delete next[key]
  else next[key] = finding
  return next
}

export function dedupeActiveFindings(findings: DedupableFinding[]): DedupableFinding[] {
  const byKey = new Map<string, DedupableFinding>()
  for (const finding of findings) {
    if (String(finding.status || '').trim().toUpperCase() === 'RESOLVED') continue
    byKey.set(findingDisplayKey(finding), finding)
  }
  return Array.from(byKey.values())
}

export function dedupeRecommendations(findings: DedupableFinding[]): DedupableFinding[] {
  const seen = new Set<string>()
  const unique: DedupableFinding[] = []
  for (const finding of findings) {
    const remediation = String(finding.remediation || '').trim()
    if (!remediation) continue
    const key = recommendationKey(remediation)
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(finding)
  }
  return unique.slice(0, 5)
}

const EVIDENCE_LOCATION = /[\w./\\-]+\.[A-Za-z0-9]+:\d+/g

export interface LocationSource {
  file?: string | null
  line?: number | null
  component?: string | null
  evidence?: string | null
}

export interface FindingLocations {
  primary: string
  component: string | null
  additional: string[]
}

export function findingLocations(finding: LocationSource): FindingLocations {
  const evidence = String(finding.evidence || '')
  const fromEvidence = Array.from(new Set(evidence.match(EVIDENCE_LOCATION) ?? []))
  const fromFile = finding.file ? `${finding.file}${finding.line ? `:${finding.line}` : ''}` : null
  const primary = fromFile || fromEvidence[0] || finding.component || 'Project scope'
  const additional = (fromFile ? fromEvidence : fromEvidence.slice(1)).filter(location => location !== primary)
  const component = finding.component && finding.component !== primary ? finding.component : null
  return { primary, component, additional }
}
