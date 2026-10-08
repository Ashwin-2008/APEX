import type { ProjectEvent } from '../hooks/useProjectEvents'

const titleCase = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())

const CATEGORY_NOUNS: Record<string, string> = {
  security: 'Security',
  testing: 'Testing',
  dependency: 'Dependencies',
  requirements: 'Requirements',
  authentication: 'Authentication',
  integration: 'Integration',
  architecture: 'Architecture',
  authorization: 'Authorization',
  input_validation: 'Input validation',
  data_integrity: 'Data integrity',
  api_contract: 'API contract',
  error_handling: 'Error handling',
  performance: 'Performance',
  configuration: 'Configuration',
  deployment: 'Deployment',
  observability: 'Observability',
}

export function categoryNoun(category: string): string {
  return CATEGORY_NOUNS[category] || titleCase(category)
}

const ANALYZER_TITLES: Record<string, string> = {
  secret_detector: 'Hard-coded secret detected',
  test_inventory: 'Tests are missing',
  dependency_analyzer: 'Dependency management gap',
  requirements_analyzer: 'Requirements are missing',
  surface_analyzer: 'Authentication gap detected',
  git_history: 'Frequent bug-fix activity',
}

export function categoryTitle(finding: { category: string; analyzer_source: string }): string {
  const title = ANALYZER_TITLES[finding.analyzer_source]
  return title || `${categoryNoun(finding.category)} issue`
}

const ANALYZER_NAMES: Record<string, string> = {
  secret_detector: 'Secret detector',
  test_inventory: 'Test inventory',
  dependency_analyzer: 'Dependency analyzer',
  requirements_analyzer: 'Requirements analyzer',
  surface_analyzer: 'Surface analyzer',
  git_history: 'Git history analyzer',
}

export function analyzerSourceName(source: string): string {
  return ANALYZER_NAMES[source] || titleCase(source)
}

const WHY_MATTERS: Record<string, string> = {
  secret_detector: 'A credential pattern appears to be stored in the repository. Secrets in source code can be exposed through commits, logs, and CI artifacts.',
  test_inventory: 'There is no automated test coverage for the critical execution paths, so regressions can be shipped without being noticed.',
  dependency_analyzer: 'The dependency manifest could not be verified, so outdated or vulnerable packages are hard to detect and pin.',
  requirements_analyzer: 'There is no written acceptance specification, so it is unclear when the product is actually correct.',
  surface_analyzer: 'The application exposes routes or API clients without visible authentication markers, so access control may be missing.',
  git_history: 'Recent history is dominated by fixes and reverts, which often indicates fragile code that changes repeatedly.',
}

export function whyItMatters(finding: { category: string; analyzer_source: string }): string {
  if (WHY_MATTERS[finding.analyzer_source]) return WHY_MATTERS[finding.analyzer_source]
  return `This issue was reported by the ${analyzerSourceName(finding.analyzer_source).toLowerCase()} with deterministic evidence.`
}

export function statusLabel(status: string | null | undefined): string {
  const value = String(status || 'ACTIVE').toUpperCase()
  if (value === 'OPEN') return 'ACTIVE'
  return value
}

const SEVERITY_SYMBOLS: Record<string, string> = { critical: '●', high: '▲', medium: '■', low: '○' }

export function severityLabel(severity: string | null | undefined): string {
  return String(severity || 'medium').toUpperCase()
}

export function severitySymbol(severity: string | null | undefined): string {
  return SEVERITY_SYMBOLS[String(severity || 'medium').toLowerCase()] || '■'
}

const DIMENSION_LABELS: Record<string, string> = {
  testing_deficiency: 'Testing problems',
  dependency_risk: 'Dependency risk',
  integration_fragility: 'Integration fragility',
  security_risk: 'Security risk',
  requirement_ambiguity: 'Requirements ambiguity',
  architecture_coupling: 'Architecture coupling',
  validation_weakness: 'Input validation weakness',
  authorization_risk: 'Authorization risk',
  configuration_drift: 'Configuration drift',
  error_handling_weakness: 'Error handling weakness',
  database_risk: 'Data integrity risk',
  deployment_risk: 'Deployment risk',
  observability_weakness: 'Observability weakness',
}

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] || titleCase(dimension)
}

export interface ActivityEntry {
  key: string
  time: Date
  message: string
  file?: string
  receivedAt: number
}

function findingFrom(event: ProjectEvent): { severity?: string; category?: string; file?: string } {
  const nested = (event.finding as { severity?: string; category?: string; file?: string } | undefined) || {}
  return {
    category: event.category as string | undefined,
    severity: event.severity as string | undefined,
    file: event.file as string | undefined,
    ...nested,
  }
}

const LIVE_MESSAGES: Record<string, string> = {
  'project.changed': 'Project files changed',
  'analysis.started': 'Analyzing the latest changes',
  'analysis.completed': 'Analysis finished — engineering profile updated',
  'analysis.failed': 'Analysis failed while scanning changes',
  'requirement.updated': 'Requirement coverage re-evaluated',
  'dna.updated': 'Engineering risk profile updated',
  'prediction.updated': 'Next-failure prediction refreshed',
  'llm.explanation.completed': 'Plain-language explanation was generated',
}

export function translateEvent(event: ProjectEvent, index: number): ActivityEntry {
  const finding = findingFrom(event)
  const noun = finding.category ? categoryNoun(finding.category) : undefined
  const severity = finding.severity?.toLowerCase()
  let message = LIVE_MESSAGES[event.type] || titleCase(String(event.type).replace(/\./g, ' '))
  if (event.type === 'finding.created') {
    message = noun
      ? severity
        ? `New ${severity} ${noun.toLowerCase()} issue detected`
        : `New ${noun.toLowerCase()} issue detected`
      : 'New issue detected'
  } else if (event.type === 'finding.updated') {
    message = noun ? `${noun} issue updated (${severity ?? 'state changed'})` : 'Issue updated'
  } else if (event.type === 'finding.resolved') {
    message = noun ? `${noun} issue resolved` : 'Issue resolved'
  } else if (event.type === 'monitoring.status') {
    message = event.status === 'active' ? 'Live monitoring is active' : 'Live monitoring paused'
  } else if (event.type === 'project.changed') {
    message = 'Files changed in the project'
  }
  const file = Array.isArray(event.files) && event.files.length
    ? String(event.files[0])
    : finding.file || undefined
  const rawTimestamp = event.timestamp
  const time = typeof rawTimestamp === 'string' && rawTimestamp ? new Date(rawTimestamp) : new Date()
  const fingerprint = String((event.finding as { fingerprint?: string } | undefined)?.fingerprint || event.fingerprint || '')
  const key = `${event.type}|${event.timestamp ?? ''}|${file ?? ''}|${message}|${fingerprint}`
  return { key, time, message, file, receivedAt: Date.now() }
}

export const ACTIVITY_REPLAY_WINDOW_MS = 120_000
export const MAX_ACTIVITY = 50

export function appendActivity(
  previous: ActivityEntry[],
  entry: ActivityEntry,
  now = Date.now(),
  windowMs = ACTIVITY_REPLAY_WINDOW_MS,
): ActivityEntry[] {
  const replay = previous.some(item => item.key === entry.key && now - item.receivedAt < windowMs)
  if (replay) return previous
  return [entry, ...previous].slice(0, MAX_ACTIVITY)
}