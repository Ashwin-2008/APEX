import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import App from '../App'
import { StudentProvider } from '../context/StudentContext'
import { ThemeProvider } from '../context/ThemeContext'
import { PracticePage } from '../pages/Pages'
const responsiveStyles = readFileSync('src/styles/index.css', 'utf8')

const question = {
  question_id: 12, topic: 'Machine Learning', subtopic: 'Classification', difficulty: 2,
  question_text: 'Which metric measures positive predictive value?',
  option_a: 'Recall', option_b: 'Precision', option_c: 'Accuracy', option_d: 'F1', estimated_time: 60,
}
const mistake = {
  mistake_event_id: 3, student_id: 7, attempt_id: 4, error_type: 'CONCEPT_CONFUSION',
  topic: 'Machine Learning', subtopic: 'Classification', timestamp: '2026-09-18T10:00:00',
}
const profile = { id: 7, name: 'Sam Learner', created_at: '2026-09-01T10:00:00' }
const prediction = {
  id: 2, student_id: 7, prediction: 'CONCEPT_CONFUSION', probability: 0.71, confidence: 0.68,
  reliability: 0.96, status: 'NORMAL_OPERATION', model: 'MISTIQ-AMPA', model_version: '1.0',
  context_question_id: 12, timestamp: '2026-09-18T10:00:00',
}

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response)
}
function renderApp(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><ThemeProvider><StudentProvider><App /></StudentProvider></ThemeProvider></MemoryRouter>)
}

function renderPractice() {
  return render(<MemoryRouter initialEntries={['/practice']}><ThemeProvider><StudentProvider><PracticePage /></StudentProvider></ThemeProvider></MemoryRouter>)
}

function setup(path: string, options: { predictionStatus?: number; progress?: Record<string, unknown>; mistakes?: unknown[] } = {}, mount: (path: string) => void = renderApp) {
  localStorage.setItem('mistiq.development.studentId', '7')
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/students/7')) return jsonResponse(profile)
    if (url.endsWith('/students/7/progress')) return jsonResponse(options.progress || { student_id: 7, attempt_count: 0, correct_count: 0, accuracy: 0, mistake_count: 0 })
    if (url.endsWith('/students/7/mistakes')) return jsonResponse(options.mistakes || [])
    if (url.endsWith('/students/7/state')) return jsonResponse({ error: 'insufficient_data', detail: 'No state' }, 409)
    if (url.endsWith('/predictions/7/latest')) return jsonResponse(prediction, options.predictionStatus || 200)
    if (url.endsWith('/questions')) return jsonResponse([question])
    if (url.endsWith('/attempts') && init?.method === 'POST') return jsonResponse({
      attempt: { attempt_id: 4, student_id: 7, question_id: 12, selected_option: 'B', correct: true, response_time: 8, timestamp: '2026-09-18T10:00:00', attempt_number: 1 },
      mistake_event: null, prediction: null, prediction_status: 'NO_RELIABLE_PREDICTION', correct_option: 'B', correct_answer: 'Precision',
    }, 201)
    return jsonResponse({ detail: 'Unexpected test API request' }, 500)
  })
  vi.stubGlobal('fetch', fetchMock)
  mount(path)
  return fetchMock
}

describe('MISTIQ student app', () => {
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })

  it('loads the dashboard with progress and recent mistake data', async () => {
    setup('/dashboard', {
      progress: { student_id: 7, attempt_count: 8, correct_count: 6, accuracy: 0.75, mistake_count: 2 },
      mistakes: [mistake], predictionStatus: 409,
    })
    expect(await screen.findByText('Good to see you, Sam.')).toBeTruthy()
    expect(screen.getByText('75')).toBeTruthy()
    expect(screen.getAllByText('Concept confusion').length).toBeGreaterThan(0)
    expect(screen.getByText('No challenge identified yet')).toBeTruthy()
  })

  it('loads a backend question, submits the answer, and shows checked feedback', async () => {
    const fetchMock = setup('/practice', {}, renderPractice)
    expect(await screen.findByText(question.question_text)).toBeTruthy()
    fireEvent.click(screen.getByText('Precision'))
    fireEvent.click(screen.getByRole('button', { name: /submit answer/i }))
    expect(await screen.findByText('Correct.')).toBeTruthy()
    expect(screen.getByText(/The correct answer is/)).toBeTruthy()
    const attemptCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/attempts') && init?.method === 'POST')
    expect(attemptCall).toBeTruthy()
    const body = JSON.parse(String(attemptCall?.[1]?.body))
    expect(body).toMatchObject({ student_id: 7, question_id: 12, selected_option: 'B' })
    expect(body).not.toHaveProperty('correct')
  })

  it('shows the question loading state until the API responds', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    let finishQuestions!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/students/7')) return jsonResponse(profile)
      if (String(input).endsWith('/questions')) return new Promise<Response>(resolve => { finishQuestions = resolve })
      return jsonResponse({ detail: 'not found' }, 404)
    }))
    renderPractice()
    expect(await screen.findByText('Finding a question…')).toBeTruthy()
    finishQuestions(await jsonResponse([question]))
    expect(await screen.findByText(question.question_text)).toBeTruthy()
  })

  it('shows an incorrect-answer feedback panel without blame', async () => {
    const fetchMock = setup('/practice', {}, renderPractice)
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith('/students/7')) return jsonResponse(profile)
      if (String(input).endsWith('/questions')) return jsonResponse([question])
      if (String(input).endsWith('/attempts') && init?.method === 'POST') return jsonResponse({
        attempt: { attempt_id: 5, student_id: 7, question_id: 12, selected_option: 'A', correct: false, response_time: 9, timestamp: '2026-09-18T10:00:00', attempt_number: 1 },
        mistake_event: mistake, prediction: null, prediction_status: 'NO_RELIABLE_PREDICTION', correct_option: 'B', correct_answer: 'Precision',
      }, 201)
      return jsonResponse({ detail: 'Not found' }, 404)
    })
    expect(await screen.findByText(question.question_text)).toBeTruthy()
    fireEvent.click(screen.getByText('Recall'))
    fireEvent.click(screen.getByRole('button', { name: /submit answer/i }))
    expect(await screen.findByText('Not quite.')).toBeTruthy()
    expect(screen.getAllByText(/concept confusion/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/A good concept to revisit/i)).toBeTruthy()
  })

  it('shows a useful backend-unavailable state', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network failure') }))
    renderApp('/login')
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/could not restore your student profile/i)).toBeTruthy()
  })

  it('creates a development student profile without claiming authentication', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/students') && init?.method === 'POST') return jsonResponse(profile, 201)
      if (url.endsWith('/students/7')) return jsonResponse(profile)
      if (url.endsWith('/students/7/progress')) return jsonResponse({ student_id: 7, attempt_count: 0, correct_count: 0, accuracy: 0, mistake_count: 0 })
      if (url.endsWith('/students/7/mistakes')) return jsonResponse([])
      if (url.endsWith('/predictions/7/latest')) return jsonResponse({ detail: 'Insufficient history' }, 409)
      return jsonResponse({ detail: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/login')
    expect(await screen.findByText('This local demonstration uses synthetic data only. It does not provide account authentication.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Your name'), { target: { value: 'Sam Learner' } })
    fireEvent.click(screen.getByRole('button', { name: /create a local profile/i }))
    expect(await screen.findByText('Good to see you, Sam.')).toBeTruthy()
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/students') && init?.method === 'POST')).toBe(true)
  })

  it('opens the seeded synthetic profile from Start Showcase', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/students/1')) return jsonResponse({ ...profile, id: 1, name: 'Aadhi Demo Student' })
      if (url.endsWith('/students/1/progress')) return jsonResponse({ student_id: 1, attempt_count: 0, correct_count: 0, accuracy: 0, mistake_count: 0 })
      if (url.endsWith('/students/1/mistakes')) return jsonResponse([])
      if (url.endsWith('/predictions/1/latest')) return jsonResponse({ detail: 'Not found' }, 404)
      return jsonResponse({ detail: 'Not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    renderApp('/login')
    expect(await screen.findByText(/A learning system that predicts what a student may struggle with next/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /start showcase/i }))
    expect(await screen.findByText('Good to see you, Aadhi.')).toBeTruthy()
    expect(screen.getByText('Showcase Mode')).toBeTruthy()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/students/1'))).toBe(true)
  })

  it('renders learning-profile signals from the stored learner state', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/students/7')) return jsonResponse(profile)
      if (String(input).endsWith('/students/7/state')) return jsonResponse({
        id: 1, student_id: 7, updated_at: '2026-09-18T10:00:00', attempt_count: 8, relevant_mistake_count: 2,
        mistake_frequency: 0.2, mistake_recency: 0.3, repetition_score: 0.1, difficulty_sensitivity: 0.4,
        behavior_pressure: 0.2, concept_confusion: 0.25, knowledge_stability: 0.8, mistake_momentum: 0.1,
      })
      return jsonResponse({ detail: 'Not found' }, 404)
    }))
    renderApp('/profile')
    expect(await screen.findByText('Your learning profile')).toBeTruthy()
    expect(screen.getByText('Concept confidence')).toBeTruthy()
    expect(screen.getByText('Challenge handling')).toBeTruthy()
    expect(screen.getByText(/These are learning signals, not labels/)).toBeTruthy()
  })

  it('renders progress analytics and accessible real-history trajectory data', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/students/7')) return jsonResponse(profile)
      if (url.endsWith('/students/7/progress')) return jsonResponse({
        student_id: 7, attempt_count: 4, correct_count: 3, accuracy: 0.75, mistake_count: 1,
        summary: { total_attempts: 4, total_correct: 3, total_incorrect: 1, overall_accuracy: 0.75, recent_accuracy: 0.75, recent_window_size: 10, recent_sample_size: 4, improvement_value: null, improvement_direction: 'INSUFFICIENT_DATA', sample_sizes: { recent: 2, previous: 2 }, window_size: 2, topics_practiced: 1, mistake_count: 1, repeated_mistake_count: 0, successful_high_difficulty_attempts: 0, high_difficulty_attempts: 0, current_streak: 2, best_streak: 2 },
        topic_performance: [{ topic: 'Classification', attempts: 4, correct: 3, incorrect: 1, accuracy: 0.75, recent_accuracy: 0.75, recent_attempts: 4, mistake_count: 1, difficulty_average: 2, trend: 'INSUFFICIENT_DATA', trend_value: null, trend_sample_sizes: { recent: 2, previous: 2 } }],
        subtopic_performance: [{ topic: 'Classification', subtopic: 'Precision', attempts: 4, correct: 3, incorrect: 1, accuracy: 0.75, recent_accuracy: 0.75, recent_attempts: 4, mistake_count: 1, difficulty_average: 2, trend: 'INSUFFICIENT_DATA', trend_value: null, trend_sample_sizes: { recent: 2, previous: 2 } }],
        difficulty_performance: [{ difficulty: 2, attempts: 4, correct: 3, incorrect: 1, accuracy: 0.75, mistake_rate: 0.25, average_response_time: 30 }],
        trajectory: [1, 2, 3, 4].map((attempt_number, index) => ({ attempt_number, timestamp: `2026-09-18T10:0${index}:00`, accuracy: index ? 0.75 : 0, difficulty: 2, mistake_rate: index ? 0.25 : 1, rolling_accuracy: null, rolling_mistake_rate: null, learning_stability: 0.4 })),
        difficulty_trajectory: [], recovery: { window_attempts: 3, recovery_count: 0, eligible_mistakes: 0, recovery_rate: null, average_recovery_attempts: null, sample_sufficient: false },
        stability: { value: 0.4, status: 'VARIABLE', sample_size: 4, source: 'learner_state' },
        mistake_momentum: { value: null, direction: 'INSUFFICIENT_DATA', trend: 'INSUFFICIENT_DATA', sample_size: 4, source: null },
      })
      return jsonResponse({ detail: 'Not found' }, 404)
    }))
    renderApp('/progress')
    expect(await screen.findByText('Topic progress')).toBeTruthy()
    expect(screen.getByText('Precision')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Cumulative accuracy and attempted difficulty by chronological attempt number' })).toBeTruthy()
    expect(screen.getByText('Keep practicing to measure your recovery pattern.')).toBeTruthy()
  })

  it('renders categorized mistakes, repeated patterns, and observed concept pairs', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/students/7')) return jsonResponse(profile)
      if (url.endsWith('/mistakes/7/summary')) return jsonResponse({
        student_id: 7, mistake_count: 3, attempt_count: 6,
        distribution: [{ error_type: 'CONCEPT_CONFUSION', occurrences: 3, percentage_of_mistakes: 1, recent_frequency: 0.5, recent_occurrences: 3, trend: 'DECREASING', trend_value: -0.2 }],
        recent_frequency: 0.5, trend: 'DECREASING', timeline_bucket: 'weekly', timeline: [], timeline_sufficient: false, timeline_message: 'Keep practicing to reveal your mistake patterns.',
        repeated: [{ error_type: 'CONCEPT_CONFUSION', topic: 'Machine Learning', subtopic: 'Classification', occurrences: 3, last_occurrence: '2026-09-18T10:00:00', recent_occurrences: 2, trend: 'DECREASING' }],
        confusions: { nodes: ['Precision', 'Recall'], edges: [{ concept_a: 'Precision', concept_b: 'Recall', occurrences: 3, recent_occurrences: 2, last_occurrence: '2026-09-18T10:00:00', strength: null, trend: 'DECREASING' }] },
        recent_mistakes: [mistake],
      })
      return jsonResponse({ detail: 'Not found' }, 404)
    }))
    renderApp('/mistakes')
    expect(await screen.findByText('3 recorded review moments')).toBeTruthy()
    expect(screen.getByText('Patterns that have appeared more than once')).toBeTruthy()
    expect(screen.getByText(/3 confusion events/)).toBeTruthy()
    expect(screen.getAllByText(/Showing up less often recently/).length).toBeGreaterThan(0)
    expect(screen.getByText('Your practice history')).toBeTruthy()
  })

  it('renders a real AMPA prediction and probability only for normal status', async () => {
    setup('/dashboard', { predictionStatus: 200, progress: { student_id: 7, attempt_count: 31, correct_count: 22, accuracy: 0.71, mistake_count: 9 } })
    expect(await screen.findByText('Concept confusion')).toBeTruthy()
    await waitFor(() => expect(screen.getByText(/Model probability/)).toBeTruthy())
    expect(screen.getByText(/Confidence/)).toBeTruthy()
    expect(screen.getByText(/Data reliability/)).toBeTruthy()
  })

  it('shows model evidence and a database-backed recommended question', async () => {
    localStorage.setItem('mistiq.development.studentId', '7')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/students/7')) return jsonResponse(profile)
      if (url.endsWith('/students/7/progress')) return jsonResponse({ student_id: 7, attempt_count: 31, correct_count: 22, accuracy: 0.71, mistake_count: 9 })
      if (url.endsWith('/students/7/mistakes')) return jsonResponse([mistake])
      if (url.endsWith('/predictions/7/latest')) return jsonResponse(prediction)
      if (url.endsWith('/predictions/7/latest/explanation')) return jsonResponse({
        prediction: 'CONCEPT_CONFUSION', probability: 0.71, risk_score: 1.2, reasons: [],
        top_predictions: [{ error_type: 'CONCEPT_CONFUSION', probability: 0.71 }, { error_type: 'TIME_PRESSURE', probability: 0.12 }],
        summary: 'This estimate uses your saved practice history.', evidence: ['Recent mistakes contributed to the model score.'], learning_need: ['Classification'],
      })
      if (url.endsWith('/recommendations/7/next')) return jsonResponse({
        recommendation: { id: 3, student_id: 7, type: 'PRACTICE_QUESTION', reason: 'This question addresses a recent review topic.', created_at: '2026-09-18T10:00:00', question_id: 12, score: 0.7, score_components: {}, completed_at: null },
        question, cold_start: false,
      })
      return jsonResponse({ detail: 'Not found' }, 404)
    }))
    renderApp('/dashboard')
    expect(await screen.findByText('Classification')).toBeTruthy()
    fireEvent.click(screen.getByText('Why am I seeing this?'))
    expect(await screen.findByText('Recent mistakes contributed to the model score.')).toBeTruthy()
    expect(screen.getByText('Other possible patterns')).toBeTruthy()
    expect(screen.getByRole('link', { name: /try this question/i }).getAttribute('href')).toBe('/practice?question=12')
  })

  it('renders actual mistake history grouped by type', async () => {
    setup('/mistakes', { mistakes: [mistake, { ...mistake, mistake_event_id: 8, error_type: 'CALCULATION_ERROR' }] })
    expect(await screen.findByText('Common mistakes')).toBeTruthy()
    expect(screen.getAllByText('Calculation error').length).toBeGreaterThan(0)
    expect(screen.getByText('2 total')).toBeTruthy()
  })

  it('shows an honest empty state when no progress exists', async () => {
    setup('/progress')
    expect(await screen.findByText('Your progress begins with practice')).toBeTruthy()
    expect(screen.queryByText(/\d+%/)).toBeNull()
  })

  it('keeps the workspace navigation to the engineering destinations', async () => {
    setup('/dashboard', { predictionStatus: 409 })
    const mainNav = await screen.findByRole('navigation', { name: 'Main navigation' })
    const labels = within(mainNav).getAllByRole('link').map(link => link.textContent || '')
    expect(labels).toContain('Dashboard')
    expect(labels).toContain('Project Review')
    expect(labels.some(l => l.includes('Project Evolution') || l.includes('Progress'))).toBe(true)
    expect(labels).toContain('Engineering Failures')
    expect(labels).not.toContain('Practice')
    expect(screen.getByRole('link', { name: 'Research Lab' }).getAttribute('href')).toBe('/project-review/research-lab')
    expect(screen.getAllByRole('link', { name: /profile/i }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: /profile/i }).some(link => link.getAttribute('href') === '/profile')).toBe(true)
  })

  it('keeps mobile navigation to four student destinations without Practice', async () => {
    setup('/dashboard', { predictionStatus: 409 })
    const nav = await screen.findByRole('navigation', { name: 'Mobile navigation' })
    const labels = within(nav).getAllByRole('link').map(link => link.textContent || '')
    expect(labels).toHaveLength(4)
    expect(labels).not.toContain('Practice')
    expect(nav.querySelector('a[href="/project-review"]')).not.toBeNull()
    expect(nav.querySelector('a[href="/research"]')).toBeNull()
  })

  it('redirects the removed Practice route back to the dashboard', async () => {
    setup('/practice', { predictionStatus: 409 })
    const nav = await screen.findByRole('navigation', { name: 'Mobile navigation' })
    expect(nav.querySelector('a[href="/practice"]')).toBeNull()
    expect(nav.querySelector('a[href="/dashboard"]')).not.toBeNull()
  })

  it('defines responsive rules for the 320px minimum and mobile navigation', () => {
    expect(responsiveStyles).toContain('min-width:320px')
    expect(responsiveStyles).toContain('@media(max-width:760px)')
    expect(responsiveStyles).toContain('.mobile-nav{position:fixed')
  })
})
