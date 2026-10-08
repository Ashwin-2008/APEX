import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveProjectReviewPage } from '../pages/LiveProjectReviewPage'
import { findingDisplayKey, type DedupableFinding } from '../utils/findingDedup'
import type { FailureHistoryResponse, FailureHistoryRow, ProjectReview, RequirementReport, ResearchStatus } from '../types/projectReview'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  closed = false
  private listeners = new Map<string, Array<(event: MessageEvent) => void>>()
  constructor(public url: string) { FakeEventSource.instances.push(this) }
  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) || []), handler])
  }
  close() { this.closed = true }
  connect() { this.onopen?.() }
  emit(type: string, payload: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify({ type, project_id: 7, ...payload }) })
    for (const handler of this.listeners.get(type) || []) handler(event)
  }
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response)
}

const seedFinding: DedupableFinding = {
  category: 'security', severity: 'critical', confidence: 0.95,
  timestamp: '2026-10-08T10:00:00Z',
  evidence: 'Potential hard-coded secret at src/config/app.py:33, token=demo',
  analyzer_source: 'secret_detector', status: 'new', remediation: 'Rotate the credential.',
}
const seedKey = findingDisplayKey(seedFinding)

const analysis: ProjectReview = {
  project: { path: 'C:/work/demo-app', file_count: 12, language_mix: { Python: 12 }, commit_count: 4, bugfix_commit_count: 1, recent_churn: '2 days' },
  events: [seedFinding],
  history: [],
  transition_graph: [],
  failure_loops: [],
  failure_dna: { testing_deficiency: 0.8, security_risk: 0.4 },
  next_failure_predictions: [],
  summary: { event_count: 1, open_high_or_critical: 1, generated_at: '2026-10-08T10:00:00Z', methodology: 'deterministic' },
}

const history: FailureHistoryResponse = {
  project: { id: 7, name: 'demo-app', repository_path: 'C:/work/demo-app' },
  summary: { review_count: 1, distinct_failure_count: 0, open_failure_count: 0, resolved_failure_count: 0, categories: [], first_review_at: null, last_review_at: '2026-10-08T10:00:00' },
  findings: [] as FailureHistoryRow[],
  message: 'No persisted failure history yet.',
}

const requirements: RequirementReport = {
  requirements: [
    { requirement_key: 'r1', title: 'Users can sign in', source: 'docs', coverage: { status: 'COVERED', confidence: 0.8, evidence: 'auth.py', implementation: { files: ['auth.py'] }, tests: { files: ['test_auth.py'] } } },
    { requirement_key: 'r2', title: 'Export data as CSV', source: 'docs', coverage: { status: 'PARTIALLY_COVERED', confidence: 0.5, evidence: 'export.py exists, no tests', implementation: { files: ['export.py'] }, tests: { files: [] } } },
  ],
  message: null,
}

const researchStatus: ResearchStatus = {
  dataset_version: 'v1', projects: 1, reviews: 1, transitions: 0, training_observations: 1, distinct_timepoints: 1,
  failure_categories: 1, date_range: { first: '2026-10-08', last: '2026-10-08' }, status: 'INSUFFICIENT_OBSERVATIONS',
  message: 'Not enough observations yet.', leakage: { passed: true, checks: [], errors: [], warnings: [] },
  model_status: 'NOT_TRAINED', model_available: false, model_detail: 'No trained artifact available.', artifact: null,
  evaluation_requirements: { min_observations: 10, min_distinct_categories: 2, min_distinct_timepoints: 3, min_walk_forward_train_observations: 6 },
}

async function connectProjectInUi() {
  render(<LiveProjectReviewPage />)
  const pathInput = await screen.findByLabelText('Project path')
  pathInput.focus()
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(pathInput, 'C:/work/demo-app')
  pathInput.dispatchEvent(new Event('input', { bubbles: true }))
  const button = screen.getByRole('button', { name: 'Connect Project' }) as HTMLButtonElement
  await waitFor(() => expect(button.disabled).toBe(false))
  button.click()
  await screen.findByRole('heading', { level: 1, name: 'demo-app' })
}

function latestEventSource(): FakeEventSource {
  const instance = FakeEventSource.instances[FakeEventSource.instances.length - 1]
  expect(instance).toBeTruthy()
  return instance
}

describe('live project review page', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method || 'GET').toUpperCase()
      if (url.endsWith('/project-reviews/connect') && method === 'POST') {
        return jsonResponse({ analysis, project_id: 7, monitoring_status: 'active' })
      }
      if (url.endsWith('/failure-history')) return jsonResponse(history)
      if (url.endsWith('/requirements/coverage')) return jsonResponse(requirements)
      if (url.endsWith('/trajectory')) return jsonResponse({ reviews: [], transitions: [], loops: [], message: 'Insufficient historical evidence for transition analysis.' })
      if (url.endsWith('/research/status')) return jsonResponse(researchStatus)
      if (url.endsWith('/research-prediction')) return jsonResponse({ available: false, project_id: 7, reason: 'No failure history to predict from.' })
      if (url.endsWith('/monitoring/stop') && method === 'POST') return jsonResponse({ project_id: 7, monitoring_status: 'paused' })
      return jsonResponse({ detail: `unexpected request ${url}` }, 500)
    }))
  })

  afterEach(() => { vi.unstubAllGlobals() })

  it('walks from connect to a live command center using only backend data', async () => {
    await connectProjectInUi()
    expect(screen.getByText('LIVE MODE')).toBeTruthy()
    expect(screen.getByText(/Branch: /).textContent).toContain('not available')
    expect(screen.getByText(/Monitoring: /).textContent).toContain('ANALYZING CHANGES')

    const source = latestEventSource()
    await waitFor(() => expect(source).toBeTruthy())
    source.connect()
    await waitFor(() => expect(screen.getByText(/Monitoring: /).textContent).toContain('LIVE MONITORING'))

    expect(screen.getByText('Overall risk')).toBeTruthy()
    expect(screen.getByText('1 high or critical issue')).toBeTruthy()
    expect(screen.getByText('1 active issue')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'PROBLEMS TO FIX' })).toBeTruthy()
    expect(screen.getByText('Hard-coded secret detected')).toBeTruthy()
    expect(screen.getAllByText('Rotate the credential.').length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'WHAT SHOULD I DO NEXT?' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'REQUIREMENTS' })).toBeTruthy()
    expect(await screen.findByText('Export data as CSV')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'RECENTLY FIXED' })).toBeTruthy()
    expect(screen.getByText(/No issues have been resolved/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'WHAT CHANGED?' })).toBeTruthy()

    const steps = screen.getByRole('list', { name: 'Getting started steps' })
    expect(within(steps).getByText('STEP 1 Connected')).toBeTruthy()
    expect(within(steps).getByText('STEP 4 Monitoring enabled')).toBeTruthy()
    await waitFor(() => expect(screen.getByText(/Your project is now being monitored/)).toBeTruthy())
  })

  it('feeds live events into activity, problems, and resolved work without a reload', async () => {
    await connectProjectInUi()
    const source = latestEventSource()
    source.connect()
    await waitFor(() => expect(screen.getByText(/Monitoring: LIVE MONITORING/)).toBeTruthy())

    source.emit('analysis.started', { files: ['src/auth/login.py'], branch: 'main', current_commit_sha: 'abc1234def' })
    await waitFor(() => expect(screen.getByText(/Monitoring: /).textContent).toContain('ANALYZING CHANGES'))
    expect(screen.getByText(/Branch: /).textContent).toContain('main')
    expect(screen.getByText(/Last commit:/).textContent).toContain('abc1234')

    source.emit('analysis.completed', { review_id: 2, review_number: 2, files: ['src/auth/login.py'], branch: 'main', current_commit_sha: 'abc1234def' })
    await waitFor(() => expect(screen.getByText(/Monitoring: LIVE MONITORING/)).toBeTruthy())
    await waitFor(() => expect(screen.getByText('Last checked')).toBeTruthy())
    expect(screen.queryByText('Not yet')).toBeNull()

    const feed = screen.getByRole('list', { name: 'What changed' })
    expect(within(feed).getByText('Analyzing the latest changes')).toBeTruthy()
    expect(within(feed).getAllByRole('listitem').length).toBeGreaterThan(1)

    const newFinding: DedupableFinding = {
      category: 'testing', severity: 'high', confidence: 0.9, timestamp: '2026-10-08T10:05:00Z',
      evidence: 'No test files were detected in the repository.', analyzer_source: 'test_inventory',
      status: 'OPEN', remediation: 'Add regression tests for the critical paths.', fingerprint: 'fp-testing',
    }
    source.emit('finding.created', { finding: newFinding })
    await waitFor(() => expect(screen.getByText('Tests are missing')).toBeTruthy())
    expect(screen.getByText('No test files were detected in the repository.')).toBeTruthy()

    source.emit('finding.resolved', {
      fingerprint: seedKey, category: 'security', severity: 'critical',
      component: null, file: null, resolved_at: '2026-10-08T10:06:00Z',
      resolution_evidence: 'Credential moved to the secret manager.', related_commit: 'abc1234def',
    })
    const problems = screen.getByRole('heading', { name: 'PROBLEMS TO FIX' }).closest('section') as HTMLElement
    await waitFor(() => expect(within(problems).queryByText('Hard-coded secret detected')).toBeNull())
    expect(screen.getByText('Credential moved to the secret manager.')).toBeTruthy()
    expect(screen.getAllByText('abc1234').length).toBeGreaterThan(0)

    source.emit('monitoring.status', { status: 'paused', branch: 'main', current_commit_sha: 'abc1234def' })
    await waitFor(() => expect(screen.getByText(/Monitoring: MONITORING PAUSED/)).toBeTruthy())
    expect((screen.getByRole('button', { name: 'Monitoring stopped' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not duplicate replayed events or repeated findings', async () => {
    await connectProjectInUi()
    const source = latestEventSource()
    source.connect()
    await waitFor(() => expect(screen.getByText(/Monitoring: LIVE MONITORING/)).toBeTruthy())

    const replayable = { type: 'finding.created', finding: { category: 'dependency', severity: 'medium', confidence: 0.8, timestamp: '2026-10-08T10:07:00Z', evidence: 'Outdated package pin', analyzer_source: 'dependency_analyzer', status: 'ACTIVE', remediation: 'Pin runtime dependencies.', fingerprint: 'fp-dep' } }
    source.emit('finding.created', replayable)
    source.emit('finding.created', replayable)
    await waitFor(() => expect(screen.getByText('Dependency management gap')).toBeTruthy())

    const problemCards = screen.getAllByRole('article')
    expect(problemCards).toHaveLength(2)

    const feed = screen.getByRole('list', { name: 'What changed' })
    const messages = within(feed).getAllByRole('listitem').map(item => item.textContent || '')
    expect(messages.filter(text => text.includes('New medium dependencies issue detected'))).toHaveLength(1)
  })

  it('stops monitoring through the backend endpoint', async () => {
    await connectProjectInUi()
    const source = latestEventSource()
    source.connect()
    await waitFor(() => expect(screen.getByText(/Monitoring: LIVE MONITORING/)).toBeTruthy())

    screen.getByRole('button', { name: 'Stop Monitoring' }).click()
    await waitFor(() => expect(screen.getByText(/Monitoring: MONITORING PAUSED/)).toBeTruthy())
    const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    const stopCall = calls.find(call => String(call[0]).endsWith('/monitoring/stop'))
    expect(stopCall).toBeTruthy()
    expect(stopCall?.[1]).toMatchObject({ method: 'POST' })
  })
})