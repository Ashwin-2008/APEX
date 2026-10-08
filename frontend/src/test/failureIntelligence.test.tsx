import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MistiqFailureIntelligence } from '../components/MistiqFailureIntelligence'
import type { FailureHistoryResponse, FailureHistoryRow, ResearchPrediction, ResearchStatus, TrajectoryResponse } from '../types/projectReview'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response)
}

const openRow: FailureHistoryRow = {
  fingerprint: 'fp-testing', category: 'testing', severity: 'high', confidence: 0.82,
  component: 'review service', file: 'backend/app/services/review.py', line: 42,
  evidence: 'Repeated assertion gaps across reviews', analyzer_source: 'test_inventory',
  remediation: 'Add regression tests', status: 'OPEN', occurrences: 2, review_numbers: [1, 3],
  first_seen: '2026-09-01T10:00:00', last_seen: '2026-09-20T10:00:00',
  resolved_at: null, resolution_evidence: null, related_commit: null,
}

const resolvedRow: FailureHistoryRow = {
  fingerprint: 'fp-dependency', category: 'dependency', severity: 'medium', confidence: 0.74,
  component: 'deps', file: null, line: null,
  evidence: 'Outdated package pin', analyzer_source: 'dependency_analyzer',
  remediation: 'Pin runtime dependencies', status: 'RESOLVED', occurrences: 1, review_numbers: [2],
  first_seen: '2026-09-05T10:00:00', last_seen: '2026-09-05T10:00:00',
  resolved_at: '2026-09-12T10:00:00', resolution_evidence: 'Pinned to patched version', related_commit: 'abc1234',
}

function historyOf(overrides: Partial<FailureHistoryResponse> = {}): FailureHistoryResponse {
  return {
    project: { id: 7, name: 'demo', repository_path: '/repos/local/demo' },
    summary: {
      review_count: 3, distinct_failure_count: 2, open_failure_count: 1, resolved_failure_count: 1,
      categories: ['dependency', 'testing'], first_review_at: '2026-09-01T10:00:00', last_review_at: '2026-09-20T10:00:00',
    },
    findings: [openRow, resolvedRow],
    message: null,
    ...overrides,
  }
}

function statusOf(overrides: Partial<ResearchStatus> = {}): ResearchStatus {
  return {
    dataset_version: 'v1', projects: 1, reviews: 3, transitions: 2, training_observations: 4,
    distinct_timepoints: 3, failure_categories: 2, date_range: { first: '2026-09-01', last: '2026-09-20' },
    status: 'INSUFFICIENT_OBSERVATIONS', message: 'Not enough observations yet.',
    leakage: { passed: true, checks: [], errors: [], warnings: [] },
    model_status: 'NOT_TRAINED', model_available: false, model_detail: 'No trained artifact available.', artifact: null,
    evaluation_requirements: {
      min_observations: 10, min_distinct_categories: 2, min_distinct_timepoints: 3, min_walk_forward_train_observations: 6,
    },
    ...overrides,
  }
}

const unavailablePrediction: ResearchPrediction = {
  available: false, project_id: 7, reason: 'Fewer observations than the evaluation minimum.', message: 'Prediction withheld.',
}

const trainedPrediction: ResearchPrediction = {
  available: true, project_id: 7, predicted_category: 'testing',
  predictions: [{ category: 'testing', probability: 0.62 }, { category: 'dependency', probability: 0.38 }],
  supporting_features: [{ feature: 'open_finding_ratio', value: 0.5, contribution: 0.31, direction: 'increases' }],
  historical_evidence: {
    review_count: 3, findings_in_latest_review: 2, observed_categories: ['testing', 'dependency'],
    transition_count: 2, note: 'Built from persisted reviews only.',
  },
  model: { name: 'MISTIQ-APR', version: '1.0' },
  training_metadata: { training_observations: 445 },
  disclaimer: 'Historical association only. Not a certainty.',
}

interface SetupOptions {
  history?: FailureHistoryResponse | { status: number; detail: string }
  trajectory?: TrajectoryResponse
  status?: ResearchStatus
  prediction?: ResearchPrediction
}

function setup(options: SetupOptions = {}, props: Partial<Parameters<typeof MistiqFailureIntelligence>[0]> = {}) {
  const historyValue = options.history ?? historyOf()
  const trajectoryValue: TrajectoryResponse = options.trajectory ?? { reviews: [], transitions: [], loops: [], message: 'Insufficient historical evidence for transition analysis.' }
  const statusValue = options.status ?? statusOf()
  const predictionValue = options.prediction ?? unavailablePrediction
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/failure-history')) {
      return 'status' in historyValue
        ? jsonResponse({ detail: historyValue.detail }, historyValue.status)
        : jsonResponse(historyValue)
    }
    if (url.endsWith('/trajectory')) return jsonResponse(trajectoryValue)
    if (url.endsWith('/research/status')) return jsonResponse(statusValue)
    if (url.endsWith('/research-prediction')) return jsonResponse(predictionValue)
    return jsonResponse({ detail: `unexpected request ${url}` }, 500)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MistiqFailureIntelligence projectId={7} source="local" sseState="CONNECTED" failureDna={{}} refreshToken={0} {...props} />)
  return fetchMock
}

describe('MISTIQ-APR failure intelligence panel', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('shows STATE A when no failure has ever been persisted', async () => {
    setup({
      history: historyOf({ summary: { review_count: 1, distinct_failure_count: 0, open_failure_count: 0, resolved_failure_count: 0, categories: [], first_review_at: null, last_review_at: '2026-09-20T10:00:00' }, findings: [], message: 'No persisted failure history yet.' }),
      prediction: { available: false, project_id: 7, reason: 'No failure history to predict from.' },
    })
    expect(await screen.findByText('A · NO FAILURE HISTORY YET')).toBeTruthy()
    expect(screen.getByText(/No failure has been persisted for this project yet/)).toBeTruthy()
    expect(screen.getByText(/not a training-data state/)).toBeTruthy()
    expect(screen.getByText('No failure history')).toBeTruthy()
    expect(screen.getByText(/Nothing to connect: no failure has been recorded for this project/)).toBeTruthy()
    expect(screen.getByText('LIVE · ANALYZED REPOSITORY')).toBeTruthy()
    expect(screen.getByText('LIVE · SSE CONNECTED')).toBeTruthy()
    expect(screen.getByText('From active findings to next-failure prediction')).toBeTruthy()
    expect(screen.getByText(/stages are a data path, not a causal chain/)).toBeTruthy()
    expect(screen.getByText(/Prediction for this project: No failure history to predict from/)).toBeTruthy()
    expect(screen.queryByText(/INSUFFICIENT DATA/)).toBeNull()
  })

  it('shows STATE B with observed requirements and no invented prediction', async () => {
    setup({ status: statusOf(), prediction: unavailablePrediction })
    expect(await screen.findByText('B · FAILURE HISTORY EXISTS · MODEL NOT TRAINED')).toBeTruthy()
    expect(screen.getByText(/but no trained MISTIQ-APR model is available for this dataset, so next-failure prediction is withheld rather than guessed/)).toBeTruthy()
    expect(screen.getByText(/Training observations:/)).toBeTruthy()
    expect(screen.getByText(/of 10 required — 6 more needed/)).toBeTruthy()
    expect(screen.getByText(/Distinct failure categories:/)).toBeTruthy()
    expect(screen.getByText(/of 2 required — requirement met/)).toBeTruthy()
    expect(screen.getByText(/Distinct review timepoints:/)).toBeTruthy()
    expect(screen.getByText(/The data path stops at the training dataset: 4 of 10 required observations/)).toBeTruthy()
    expect(screen.queryByText('Most likely next issue:')).toBeNull()
    expect(screen.getByText('Open failures')).toBeTruthy()
    expect(screen.getByText('Resolved failures')).toBeTruthy()
    expect(screen.getByText('Reviews observed')).toBeTruthy()
    expect(screen.getByText('Failure categories')).toBeTruthy()
    expect(screen.getByText('Not trained')).toBeTruthy()
  })

  it('shows STATE C using real artifact predictions and connected evidence', async () => {
    setup({ status: statusOf({ model_status: 'TRAINED', model_available: true, model_detail: 'Artifact valid.', status: 'TRAINED' }), prediction: trainedPrediction })
    expect(await screen.findByText('C · TRAINED MODEL PREDICTION AVAILABLE')).toBeTruthy()
    expect(screen.getByText('Most likely next issue:')).toBeTruthy()
    expect(screen.getByText('62.0%')).toBeTruthy()
    expect(screen.getByText('38.0%')).toBeTruthy()
    const modelTraining = screen.getByLabelText('Model training data')
    expect(within(modelTraining).getByText('MISTIQ-APR v1.0')).toBeTruthy()
    expect(within(modelTraining).getByText('445')).toBeTruthy()
    const projectHistory = screen.getByLabelText('Current project history')
    expect(projectHistory.textContent).toContain('Current project reviews')
    expect(projectHistory.textContent).toContain('Current project transitions')
    expect(projectHistory.textContent).toContain('Findings in latest review')
    expect(projectHistory.textContent).toContain('Observed categories')
    expect(within(projectHistory).getByText('Testing, Dependency')).toBeTruthy()
    expect(screen.getByText('Prediction is based on historical project observations and current project state. It is not a certainty or causal estimate.')).toBeTruthy()
    expect(screen.getByText('WHY THIS PREDICTION')).toBeTruthy()
    expect(screen.getByText(/Most influential signals: Open Finding Ratio \(increases\)\./)).toBeTruthy()
    expect(screen.getByText('Historical evidence: past reviews recorded Testing, Dependency across 3 persisted reviews.')).toBeTruthy()
    expect(screen.getByText('Current project evidence: 3 reviews · 2 transitions · 2 findings in the latest review.')).toBeTruthy()
    expect(screen.getByText(/Built from persisted reviews only\./)).toBeTruthy()
    const features = screen.getByText('Show technical model features').closest('details') as HTMLElement
    expect(features).toBeTruthy()
    expect(within(features).getByText('Open Finding Ratio: 0.5000')).toBeTruthy()
    expect(within(features).getByText('increases · contribution 0.31')).toBeTruthy()
    expect(screen.getByText('Historical association only. Not a certainty.')).toBeTruthy()
    expect(screen.getByText(/This is an observed association, not causation/)).toBeTruthy()
    expect(screen.getByText('Available')).toBeTruthy()
  })

  it('shows STATE E with the real error instead of hiding behind insufficient data', async () => {
    setup({ history: { status: 500, detail: 'failure history endpoint down' } })
    expect(await screen.findByText('E · ERROR LOADING PREDICTION DATA')).toBeTruthy()
    expect(screen.getByText(/This is an error state, not an insufficient-data state/)).toBeTruthy()
    expect(screen.getByText(/Failure history: failure history endpoint down/)).toBeTruthy()
    expect(screen.getAllByText('Failure history unavailable').length).toBeGreaterThan(0)
    expect(screen.getByText('Connection unknown while prediction data fails to load.')).toBeTruthy()
    expect(screen.queryByText(/NOT TRAINED — INSUFFICIENT DATA/)).toBeNull()
  })

  it('renders what, where, when, evidence, and why for every persisted failure', async () => {
    setup()
    const timeline = (await screen.findByText('FAILURE HISTORY')).closest('.fi-section') as HTMLElement
    expect(timeline).toBeTruthy()
    const summaries = timeline.querySelectorAll('.fi-timeline-item')
    expect(summaries).toHaveLength(2)
    expect(within(timeline).getAllByText('What')).toHaveLength(2)
    expect(within(timeline).getAllByText('Where')).toHaveLength(2)
    expect(within(timeline).getAllByText('When')).toHaveLength(2)
    expect(within(timeline).getAllByText('Evidence')).toHaveLength(2)
    expect(within(timeline).getAllByText('Why it matters')).toHaveLength(2)
    expect(within(timeline).getAllByText('Recommended action')).toHaveLength(2)
    expect(within(timeline).getByText('backend/app/services/review.py:42')).toBeTruthy()
    expect(within(timeline).getByText('deps')).toBeTruthy()
    expect(within(timeline).getAllByText(/First seen .* · Last seen .* · reviews 1, 3/)).toHaveLength(1)
    expect(within(timeline).getByText(/Repeated assertion gaps across reviews/)).toBeTruthy()
    expect(within(timeline).getByText(/source: test_inventory/)).toBeTruthy()
    expect(within(timeline).getByText(/Detected in 2 of 3 persisted reviews, so this is a repeat observation rather than a one-off\./)).toBeTruthy()
    expect(within(timeline).getByText(/Analyzer confidence 82%\./)).toBeTruthy()
    expect(within(timeline).getByText('Add regression tests')).toBeTruthy()
    expect(within(timeline).getByText('2 of 3 reviews')).toBeTruthy()
    expect(within(timeline).getByText(/Pinned to patched version · resolved .* · commit abc1234/)).toBeTruthy()
    expect(within(timeline).getByText('RESOLVED')).toBeTruthy()
  })

  it('labels observed transitions as non-causal and lists repeat failures', async () => {
    setup({
      trajectory: {
        reviews: [],
        transitions: [{ from: 'testing', to: 'dependency', count: 2 }],
        loops: [{ pattern: 'testing → dependency → testing', occurrence_count: 1 }],
        message: null,
      },
    })
    const heading = await screen.findByText('FAILURE PATTERNS')
    const section = heading.closest('.fi-section') as HTMLElement
    expect(section).toBeTruthy()
    expect(section.textContent).toContain('Testing')
    expect(section.textContent).toContain('Dependency')
    expect(section.textContent).toContain('observed 2 times')
    expect(section.textContent).toContain('Patterns show association, not causation')
    expect(section.textContent).toContain('Recurring patterns')
    expect(section.textContent).toContain('testing → dependency → testing')
    expect(section.textContent).toContain('observed 1 time')
    expect(section.textContent).toContain('Repeat failures')
    expect(section.textContent).toContain('Testing in 2 of 3 reviews')
  })

  it('scores Failure DNA evidence from persisted counts only', async () => {
    setup({}, { failureDna: { testing_deficiency: 0.8, security_risk: 0.15 } })
    const dna = (await screen.findByText('FAILURE DNA')).closest('.fi-section') as HTMLElement
    expect(dna).toBeTruthy()
    expect(dna.textContent).toContain('Levels are computed from persisted finding counts per category')
    expect(dna.textContent).toContain('Engine ratios are deterministic analyzer output, not probabilities')
    expect(within(dna).getByText('Testing problems')).toBeTruthy()
    expect(within(dna).getByText('LOW EVIDENCE')).toBeTruthy()
    expect(within(dna).getByText('1 open · 0 resolved')).toBeTruthy()
    expect(within(dna).getByText('1 supporting observation in Testing')).toBeTruthy()
    expect(within(dna).getByText('Engine ratio 0.80 is deterministic analyzer output, not a probability.')).toBeTruthy()
    expect(within(dna).getByText('Security risk')).toBeTruthy()
    expect(within(dna).getByText('NO EVIDENCE')).toBeTruthy()
    expect(within(dna).getByText('0 open · 0 resolved')).toBeTruthy()
    expect(within(dna).getByText('0 supporting observations in Security')).toBeTruthy()
    expect(dna.textContent).not.toMatch(/\d+%/)
  })

  it('flags showcase repository paths as synthetic instead of live', async () => {
    setup({
      history: historyOf({ project: { id: 7, name: 'sample', repository_path: 'C:/repos/showcase/sample' } }),
      status: statusOf({ model_status: 'TRAINED', model_available: true, model_detail: 'Artifact valid.' }),
      prediction: trainedPrediction,
    }, { sseState: 'STOPPED' })
    expect(await screen.findByText('SHOWCASE · SYNTHETIC DATA')).toBeTruthy()
    expect(screen.getByText('MONITORING STOPPED')).toBeTruthy()
    expect(screen.queryByText('LIVE · ANALYZED REPOSITORY')).toBeNull()
    expect(screen.getByText(/Source: Local folder/)).toBeTruthy()
  })
})
