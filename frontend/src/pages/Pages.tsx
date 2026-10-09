import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { DashboardPage as ModernDashboardPage } from './DashboardPage'
import { ProjectEvolutionPage } from './ProjectEvolutionPage'
import { EngineeringFailuresPage } from './EngineeringFailuresPage'
import { ProfileSettingsPage } from './ProfileSettingsPage'
import { getLearnerState, getMistakeSummary, getMistakes, getProgress } from '../api/students'
import { getQuestions } from '../api/questions'
import { submitAttempt } from '../api/attempts'
import { getLatestPrediction, getLatestExplanation } from '../api/predictions'
import { getNextRecommendation } from '../api/recommendations'
import { mistakeLabels } from '../constants/errorLabels'
import { mistakeTrendText, performanceTrendText } from '../constants/analyticsLanguage'
import { ApiError } from '../api/client'
import {
  getPredictionTrace,
  getResearchAblations,
  getResearchCalibration,
  getResearchConfusion,
  getResearchCurves,
  getResearchColdStart,
  getResearchEvaluation,
  getResearchModel,
  getResearchPredictions,
  getResearchSeeds,
} from '../api/research'
import { useStudent } from '../context/StudentContext'
import { useTheme } from '../context/ThemeContext'
import { Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../components'
import {
  DashboardIcon,
  ShieldIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  ActivityIcon,
  ZapIcon,
  ArrowRightIcon,
  FolderIcon,
  GithubIcon,
  GitBranchIcon,
  GitCommitIcon,
  SunIcon,
  MoonIcon,
  LaptopIcon,
} from '../components/ui/Icons'
import type {
  AttemptSubmission,
  ErrorType,
  LearnerState,
  MistakeEvent,
  MistakeSummary,
  OptionKey,
  Prediction,
  PredictionExplanation,
  Progress,
  Question,
  RecommendedPractice,
} from '../types/entities'

const optionKeys: OptionKey[] = ['A', 'B', 'C', 'D']
const optionText = (question: Question, key: OptionKey) =>
  question[`option_${key.toLowerCase()}` as 'option_a' | 'option_b' | 'option_c' | 'option_d']
const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : 'Something went wrong. Please try again.'

/* =========================================================================
   LOGIN / ENTRY PAGE
   ========================================================================= */
export function LoginPage() {
  const { student, ready, enter, reconnect, restoreError } = useStudent()
  const navigate = useNavigate()
  const location = useLocation()
  const [name, setName] = useState('')
  const [studentId, setStudentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const from = (location.state as { from?: string } | null)?.from || '/dashboard'

  useEffect(() => {
    if (ready && student) navigate(from, { replace: true })
  }, [ready, student, from, navigate])

  async function createProfile(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await enter(name.trim())
      navigate('/dashboard', { replace: true })
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function reconnectProfile(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await reconnect(Number(studentId))
      navigate('/dashboard', { replace: true })
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function startShowcase() {
    setBusy(true)
    setError('')
    try {
      await reconnect(1)
      navigate('/dashboard', { replace: true })
    } catch {
      setError(
        'The showcase profile is not ready. Run python scripts/setup_showcase.py, then restart the backend.'
      )
    } finally {
      setBusy(false)
    }
  }

  if (!ready) return <LoadingState label="Opening your learning space…" />

  return (
    <main className="entry-page">
      <div className="entry-brand">
        <span className="brand-logo-gem">M</span>
        MISTIQ<span>2.0</span>
      </div>
      <div className="entry-grid">
        <section className="entry-intro">
          <span className="eyebrow">Mistake Intelligence &amp; Sequential Prediction</span>
          <h1>Learn from how mistakes change over time.</h1>
          <p>
            A learning system that predicts what a student may struggle with next by learning from how their mistakes evolve over time.
          </p>
          <div className="entry-note">
            <span className="note-mark">✳</span>
            <span>Your progress and predictions come from recorded synthetic practice.</span>
          </div>
          <div className="showcase-cta">
            <Button onClick={startShowcase} disabled={busy}>
              {busy ? 'Opening showcase…' : 'Start Showcase'} <span aria-hidden="true">→</span>
            </Button>
            <a className="text-link" href="#explore-mistiq">
              Explore MISTIQ
            </a>
          </div>
          <span className="showcase-label">Showcase Mode · Synthetic Data</span>
        </section>

        <Card className="entry-card" id="explore-mistiq">
          <div className="eyebrow">Explore MISTIQ</div>
          <h2>Continue with a local profile</h2>
          <p>
            This local demonstration uses synthetic data only. It does not provide account authentication.
          </p>
          {restoreError && <ErrorState message={restoreError} />}
          <form onSubmit={createProfile} className="form-stack">
            <label htmlFor="student-name">Your name</label>
            <input
              id="student-name"
              value={name}
              maxLength={200}
              onChange={event => setName(event.target.value)}
              placeholder="e.g. Alex"
              required
            />
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? 'Connecting…' : 'Create a local profile'} <span aria-hidden="true">→</span>
            </Button>
          </form>

          <div className="form-divider">
            <span>Already have a profile?</span>
          </div>

          <form onSubmit={reconnectProfile} className="form-stack">
            <label htmlFor="student-id">Student ID</label>
            <div className="inline-form">
              <input
                id="student-id"
                type="number"
                min="1"
                value={studentId}
                onChange={event => setStudentId(event.target.value)}
                placeholder="Enter your ID"
                required
              />
              <Button type="submit" className="button-secondary" disabled={busy || !studentId}>
                Continue
              </Button>
            </div>
          </form>
          {error && <ErrorState message={error} />}
        </Card>
      </div>
      <footer className="entry-footer">MISTIQ 2.0 · Showcase Mode · Synthetic Data</footer>
    </main>
  )
}

/* =========================================================================
   PREDICTION & RECOMMENDATION CARDS
   ========================================================================= */
function PredictionCard({
  prediction,
  explanation,
  empty = false,
}: {
  prediction: Prediction | null
  explanation: PredictionExplanation | null
  empty?: boolean
}) {
  if (!prediction) {
    return (
      <Card className="prediction-card">
        <div className="card-kicker">Likely next challenge</div>
        <div className="prediction-empty">
          <span className="illustration-mark">✳</span>
          <div>
            <h3>{empty ? 'Keep practicing' : 'No challenge identified yet'}</h3>
            <p>We need a little more practice history before we can identify a likely challenge.</p>
          </div>
        </div>
      </Card>
    )
  }

  const reliable = prediction.status === 'NORMAL_OPERATION'

  return (
    <Card className="prediction-card">
      <div className="card-kicker">
        Likely next challenge{' '}
        <span className={reliable ? 'signal-pill' : 'signal-pill signal-early'}>
          {reliable ? 'Normal operation' : 'Early signal'}
        </span>
      </div>
      <div className="prediction-content">
        <span className="prediction-icon">◉</span>
        <div>
          <h3>
            {mistakeLabels[prediction.prediction] ||
              prediction.prediction.split('_').join(' ').toLowerCase()}
          </h3>
          <p>
            {reliable
              ? 'This estimate comes from the sequence of your recorded practice.'
              : 'This is an early signal from your practice so far. Keep exploring different questions.'}
          </p>
          {prediction.prediction === 'CONCEPT_CONFUSION' &&
          explanation?.learning_need?.length ? (
            <p className="pattern-highlight">
              Recent concept confusion: {explanation.learning_need.join(', ')}
            </p>
          ) : null}
          {reliable && (
            <div className="prediction-metrics">
              <span>
                Model probability <strong>{(prediction.probability * 100).toFixed(0)}%</strong>
              </span>
              <span>
                Confidence <strong>{(prediction.confidence * 100).toFixed(0)}%</strong>
              </span>
              <span>
                Data reliability <strong>{(prediction.reliability * 100).toFixed(0)}%</strong>
              </span>
            </div>
          )}
        </div>
      </div>
      {explanation && (
        <details className="prediction-why">
          <summary>Why am I seeing this?</summary>
          <p>{explanation.summary}</p>
          {explanation.evidence.length > 0 && (
            <ul>
              {explanation.evidence.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          )}
          <div className="top-probabilities">
            <strong>Other possible patterns</strong>
            {explanation.top_predictions.map(item => (
              <span key={item.error_type}>
                {mistakeLabels[item.error_type]} · {(item.probability * 100).toFixed(0)}%
              </span>
            ))}
          </div>
        </details>
      )}
    </Card>
  )
}

function RecommendationCard({ recommendation }: { recommendation: RecommendedPractice | null }) {
  if (!recommendation) {
    return (
      <Card className="recommendation-card">
        <div className="card-kicker">Recommended practice</div>
        <h3>Practice questions will appear here</h3>
        <p>Add questions to the library to receive a next-step recommendation.</p>
      </Card>
    )
  }

  return (
    <Card className="recommendation-card">
      <div className="card-kicker">
        Recommended practice{' '}
        {recommendation.cold_start && <span className="signal-pill signal-early">Getting started</span>}
      </div>
      <h3>{recommendation.question.subtopic || recommendation.question.topic}</h3>
      <p>{recommendation.recommendation.reason}</p>
      <p className="recommendation-detail">
        Difficulty {recommendation.question.difficulty} of 5 ·{' '}
        {recommendation.question.estimated_time} sec guide
      </p>
      <Link className="text-link" to={`/practice?question=${recommendation.question.question_id}`}>
        Try this question <span aria-hidden="true">→</span>
      </Link>
    </Card>
  )
}

/* =========================================================================
   DASHBOARD PAGE: ENGINEERING OVERVIEW
   ========================================================================= */
export function DashboardPage() {
  return <ModernDashboardPage />
}


/* =========================================================================
   PRACTICE PAGE
   ========================================================================= */
export function PracticePage() {
  const { student } = useStudent()
  const location = useLocation()
  const [questions, setQuestions] = useState<Question[]>([])
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<OptionKey | null>(null)
  const [result, setResult] = useState<AttemptSubmission | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [startedAt, setStartedAt] = useState(Date.now())
  const feedbackRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    getQuestions({
      topic: params.get('topic') || undefined,
      subtopic: params.get('subtopic') || undefined,
    })
      .then(items => {
        setQuestions(items)
        const requested = Number(params.get('question'))
        const requestedIndex = items.findIndex(item => item.question_id === requested)
        if (requestedIndex >= 0) setIndex(requestedIndex)
      })
      .catch(reason => setError(errorMessage(reason)))
      .finally(() => setLoading(false))
  }, [location.search])

  const question = questions[index]

  useEffect(() => {
    if (question && !result) setStartedAt(Date.now())
  }, [question?.question_id, result])

  useEffect(() => {
    if (result) feedbackRef.current?.focus({ preventScroll: true })
  }, [result])

  function nextQuestion() {
    setIndex(current => (current + 1) % questions.length)
    setSelected(null)
    setResult(null)
    setError('')
    setStartedAt(Date.now())
  }

  async function submit() {
    if (!student || !question || !selected) return
    setSubmitting(true)
    setError('')
    try {
      const response = await submitAttempt({
        student_id: student.id,
        question_id: question.question_id,
        selected_option: selected,
        response_time: Math.max(1, Math.round((Date.now() - startedAt) / 1000)),
        idempotency_key: crypto.randomUUID(),
      })
      setResult(response)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading)
    return (
      <>
        <PageHeader
          title="Practice"
          description="Take your time. Each question is a chance to learn."
        />
        <LoadingState label="Finding a question…" />
      </>
    )

  if (error && !question)
    return (
      <>
        <PageHeader
          title="Practice"
          description="Take your time. Each question is a chance to learn."
        />
        <ErrorState message={error} />
      </>
    )

  if (!questions.length)
    return (
      <>
        <PageHeader
          title="Practice"
          description="Take your time. Each question is a chance to learn."
        />
        <Card>
          <EmptyState
            title="No questions are available yet"
            description="Once questions are added to the learning library, they will appear here."
          />
        </Card>
      </>
    )

  const difficulty = ['Very easy', 'Easy', 'Medium', 'Hard', 'Very hard'][question.difficulty - 1]

  return (
    <>
      <PageHeader
        title="Practice"
        description="Take your time. Each question is a chance to learn."
      />
      <div className="practice-layout">
        <div className="practice-main">
          <div className="practice-meta">
            <span>
              {question.topic}
              {question.subtopic ? ` / ${question.subtopic}` : ''}
            </span>
            <span className="difficulty-tag">{difficulty}</span>
          </div>

          <Card className="question-card">
            <div className="question-count">
              QUESTION {String(index + 1).padStart(2, '0')} <span>·</span>{' '}
              {question.estimated_time} sec guide
            </div>
            <h2>{question.question_text}</h2>
            <fieldset className="answer-list" disabled={!!result || submitting}>
              <legend className="sr-only">Choose one answer</legend>
              {optionKeys.map(key => (
                <label
                  key={key}
                  className={`answer-option ${selected === key ? 'selected' : ''} ${
                    result?.correct_option === key ? 'answer-correct' : ''
                  } ${
                    result && selected === key && !result.attempt.correct
                      ? 'answer-incorrect'
                      : ''
                  }`}
                >
                  <input
                    type="radio"
                    name="answer"
                    value={key}
                    aria-label={`${key}. ${optionText(question, key)}`}
                    checked={selected === key}
                    onChange={() => setSelected(key)}
                  />
                  <span className="option-key" aria-hidden="true">
                    {key}
                  </span>
                  <span>{optionText(question, key)}</span>
                  {result?.correct_option === key && (
                    <span className="answer-mark">Correct answer</span>
                  )}
                </label>
              ))}
            </fieldset>

            {error && <ErrorState message={error} />}

            {!result ? (
              <div className="question-actions">
                <span className="quiet-note">Your answer is checked by MISTIQ.</span>
                <Button onClick={submit} disabled={!selected || submitting}>
                  {submitting ? 'Checking…' : 'Submit answer'}{' '}
                  <span aria-hidden="true">→</span>
                </Button>
              </div>
            ) : (
              <div
                ref={feedbackRef}
                tabIndex={-1}
                className={`feedback-panel ${
                  result.attempt.correct ? 'feedback-good' : 'feedback-review'
                }`}
                role="status"
              >
                <span className="feedback-icon">{result.attempt.correct ? '✓' : '↗'}</span>
                <div>
                  <h3>{result.attempt.correct ? 'Correct.' : 'Not quite.'}</h3>
                  <p>
                    The correct answer is{' '}
                    <strong>
                      {result.correct_option}. {result.correct_answer}
                    </strong>
                  </p>
                  {result.mistake_event?.error_type === 'CONCEPT_CONFUSION' && (
                    <div className="aha-card">
                      <div className="card-kicker">A pattern MISTIQ noticed</div>
                      <strong>Concept confusion</strong>
                      <p className="confusion-pair">
                        {question.subtopic || question.topic} ↔{' '}
                        {optionText(question, result.attempt.selected_option)}
                      </p>
                      <p>
                        Your answer connects two related concepts. Practicing this distinction can help make the difference clearer.
                      </p>
                      <Link
                        className="button button-secondary"
                        to={`/practice?topic=${encodeURIComponent(question.topic)}`}
                      >
                        Practice this concept
                      </Link>
                    </div>
                  )}
                  {result.mistake_event && (
                    <p>
                      This looks like a{' '}
                      <strong>
                        {mistakeLabels[result.mistake_event.error_type].toLowerCase()}
                      </strong>{' '}
                      in {result.mistake_event.subtopic || result.mistake_event.topic}. A good concept to revisit.
                    </p>
                  )}
                  {!result.mistake_event && (
                    <p>Keep building on what you know about {question.subtopic || question.topic}.</p>
                  )}
                  {result.prediction && (
                    <p className="feedback-prediction">
                      A possible next challenge:{' '}
                      {mistakeLabels[result.prediction.prediction].toLowerCase()}.
                    </p>
                  )}
                  {!result.prediction && (
                    <p className="quiet-note">
                      {result.prediction_status === 'NO_RELIABLE_PREDICTION'
                        ? 'A few more practice answers will help MISTIQ spot useful patterns.'
                        : 'Your attempt and learning progress have been saved.'}
                    </p>
                  )}
                  <Button className="button-secondary" onClick={nextQuestion}>
                    Next question <span aria-hidden="true">→</span>
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>

        <aside className="practice-aside">
          <Card>
            <span className="aside-mark">✳</span>
            <h3>Practice, then reflect</h3>
            <p>There is no rush. Give each question a thoughtful try and learn from the feedback.</p>
            <div className="aside-rule" />
            <span className="aside-label">IN THIS SESSION</span>
            <strong>{questions.length} questions available</strong>
          </Card>
        </aside>
      </div>
    </>
  )
}

function TrendCopy({ value }: { value: string }) {
  if (value in performanceTrendText)
    return <span>{performanceTrendText[value as keyof typeof performanceTrendText]}</span>
  if (value in mistakeTrendText)
    return <span>{mistakeTrendText[value as keyof typeof mistakeTrendText]}</span>
  return <span>{performanceTrendText.INSUFFICIENT_DATA}</span>
}

function AccuracyChart({ points }: { points: NonNullable<Progress['trajectory']> }) {
  if (points.length < 2)
    return <p className="analytics-empty">Keep practicing to reveal a clearer learning trend.</p>
  const x = (idx: number) => 24 + (idx * 552) / Math.max(1, points.length - 1)
  const accuracyLine = points
    .map((point, idx) => `${x(idx)},${124 - point.accuracy * 100}`)
    .join(' ')
  const difficultyLine = points
    .map((point, idx) => `${x(idx)},${124 - ((point.difficulty - 1) / 4) * 100}`)
    .join(' ')
  return (
    <>
      <svg
        className="trajectory-chart"
        viewBox="0 0 600 150"
        role="img"
        aria-label="Cumulative accuracy and attempted difficulty by chronological attempt number"
      >
        <title>Accuracy and question difficulty across attempts</title>
        <line x1="24" y1="24" x2="576" y2="24" />
        <line x1="24" y1="74" x2="576" y2="74" />
        <line x1="24" y1="124" x2="576" y2="124" />
        <polyline points={accuracyLine} />
        <polyline className="difficulty-line" points={difficultyLine} />
        <text x="24" y="145">
          Attempt 1
        </text>
        <text x="522" y="145">
          Attempt {points.length}
        </text>
      </svg>
      <div className="chart-legend">
        <span>
          <i className="legend-accuracy" />
          Cumulative accuracy
        </span>
        <span>
          <i className="legend-difficulty" />
          Difficulty attempted (1–5)
        </span>
      </div>
      <p className="chart-caption">
        The difficulty line shows challenge level, not improvement. Accuracy is calculated from results through each attempt.
      </p>
    </>
  )
}

/* =========================================================================
   PROGRESS PAGE: PROJECT EVOLUTION
   ========================================================================= */
export function ProgressPage() {
  return <ProjectEvolutionPage />
}

/* =========================================================================
   MISTAKES PAGE: ENGINEERING FAILURES COMMAND CENTER
   ========================================================================= */
export function MistakesPage() {
  return <EngineeringFailuresPage />
}

/* =========================================================================
   PROFILE PAGE: DEVELOPER & PROJECT PROFILE
   ========================================================================= */
export function ProfilePage() {
  return <ProfileSettingsPage />
}

/* =========================================================================
   RESEARCH PAGE / MODEL LAB
   ========================================================================= */
export function ResearchPage({ mode }: { mode: 'overview' | 'formula' | 'evaluation' }) {
  const [model, setModel] = useState<Record<string, any> | null>(null)
  const [evaluation, setEvaluation] = useState<Record<string, any> | null>(null)
  const [ablations, setAblations] = useState<Record<string, any> | null>(null)
  const [seeds, setSeeds] = useState<Record<string, any> | null>(null)
  const [curves, setCurves] = useState<Record<string, any> | null>(null)
  const [coldStart, setColdStart] = useState<Record<string, any> | null>(null)
  const [calibration, setCalibration] = useState<Record<string, any> | null>(null)
  const [confusion, setConfusion] = useState<Record<string, any> | null>(null)
  const [evaluationModel, setEvaluationModel] = useState('mistiq-ampa')
  const [evaluationSeed, setEvaluationSeed] = useState('42')
  const [comparisonModel, setComparisonModel] = useState('all')
  const [ablationFilter, setAblationFilter] = useState('all')
  const [studentId, setStudentId] = useState('')
  const [predictions, setPredictions] = useState<Record<string, any>[]>([])
  const [predictionId, setPredictionId] = useState('')
  const [trace, setTrace] = useState<Record<string, any> | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getResearchModel()
      .then(setModel)
      .catch(reason => setError(errorMessage(reason)))
  }, [])

  useEffect(() => {
    if (mode !== 'evaluation') return
    Promise.all([
      getResearchEvaluation(),
      getResearchAblations(),
      getResearchSeeds(),
      getResearchCurves(),
      getResearchColdStart(),
    ])
      .then(([e, a, s, c, cold]) => {
        setEvaluation(e)
        setAblations(a)
        setSeeds(s)
        setCurves(c)
        setColdStart(cold)
      })
      .catch(reason => setError(errorMessage(reason)))
  }, [mode])

  useEffect(() => {
    if (mode !== 'evaluation') return
    Promise.all([
      getResearchCalibration(evaluationModel, Number(evaluationSeed)),
      getResearchConfusion(evaluationModel, Number(evaluationSeed)),
    ])
      .then(([cal, conf]) => {
        setCalibration(cal)
        setConfusion(conf)
      })
      .catch(reason => setError(errorMessage(reason)))
  }, [mode, evaluationModel, evaluationSeed])

  const loadPredictions = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setTrace(null)
    setPredictions([])
    setPredictionId('')
    try {
      const rows = await getResearchPredictions(Number(studentId))
      setPredictions(rows)
      if (rows[0]) setPredictionId(String(rows[0].id))
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const loadTrace = async () => {
    if (!predictionId) return
    setError('')
    try {
      setTrace(await getPredictionTrace(Number(predictionId)))
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const titles = {
    overview: ['Research / Model Lab', 'Implementation and saved model details from this project.'],
    formula: [
      'Formula Explorer',
      'Reconstruct a stored prediction from its attempt history and saved AMPA parameters.',
    ],
    evaluation: [
      'Evaluation',
      'Phase 4 evaluation artifacts, read directly from experiment outputs.',
    ],
  } as const

  const [title, description] = titles[mode]
  const metricKeys = [
    'accuracy',
    'macro_precision',
    'macro_recall',
    'macro_f1',
    'weighted_f1',
    'log_loss',
    'top2_accuracy',
    'top3_accuracy',
    'brier_score',
    'ece',
  ]
  const fmt = (v: unknown) => (typeof v === 'number' ? v.toFixed(4) : String(v ?? '—'))

  return (
    <div className="research-page-container">
      <div className="page-header-row">
        <div>
          <span className="eyebrow">MISTIQ-APR LABORATORY</span>
          <h1 className="main-title">{title}</h1>
          <p className="dashboard-subtitle">{description}</p>
        </div>
      </div>

      <div className="research-links research-tabs">
        <Link to="/research" className={mode === 'overview' ? 'active' : ''}>
          Research overview
        </Link>
        <Link to="/research/formula" className={mode === 'formula' ? 'active' : ''}>
          Formula explorer
        </Link>
        <Link to="/research/evaluation" className={mode === 'evaluation' ? 'active' : ''}>
          Evaluation
        </Link>
      </div>

      {error && <p className="error research-error">{error}</p>}

      {mode === 'overview' && (
        <div className="research-grid">
          <Card className="research-wide">
            <div className="card-kicker">MISTIQ-AMPA · {model?.model_version ?? '…'}</div>
            <h2>Adaptive Mistake Propagation Algorithm</h2>
            <p>
              Predicts a likely next mistake category from sequential learning behavior. It is a project-specific custom sequential mistake-prediction framework, not a claimed universal machine-learning paradigm.
            </p>
            <div className="research-facts">
              <span>
                Features<strong>{model?.feature_count ?? '—'}</strong>
              </span>
              <span>
                Classes<strong>{model?.class_count ?? '—'}</strong>
              </span>
              <span>
                Training<strong>{model?.training_status ?? '—'}</strong>
              </span>
              <span>
                Evaluation<strong>{model?.evaluation_status ?? '—'}</strong>
              </span>
            </div>
          </Card>

          <Card className="research-wide">
            <div className="card-kicker">IMPLEMENTED PIPELINE</div>
            <div className="research-pipeline">
              {[
                'Student attempts',
                'Mistake events',
                'Mistake memory',
                'Feature engineering',
                'Risk representation',
                'AMPA scores',
                'Stable softmax',
                'Prediction and explanation',
                'Recommendation',
              ].map((item, i) => (
                <div key={item}>
                  <span>{String(i + 1).padStart(2, '0')}</span>
                  {item}
                </div>
              ))}
            </div>
          </Card>

          <Card className="research-wide">
            <div className="card-kicker">FEATURES FROM THE MODEL IMPLEMENTATION</div>
            <div className="research-feature-grid">
              {(model?.feature_definitions ?? []).map((feature: Record<string, any>) => (
                <article key={feature.name}>
                  <div>
                    <strong>{feature.label ?? feature.name.replaceAll('_', ' ')}</strong>
                    <code>{feature.symbol}</code>
                  </div>
                  <p>{feature.description}</p>
                  <small>
                    Range {feature.range}. {feature.role}
                  </small>
                </article>
              ))}
            </div>
            <p className="research-note">
              The model transforms learning stability to instability (1 − stability) before standardization and scoring. Student profile labels are computational learning-history signals, not psychological attributes.
            </p>
          </Card>
        </div>
      )}

      {mode === 'formula' && (
        <div className="research-stack">
          <Card>
            <div className="card-kicker">SELECT HISTORICAL CONTEXT</div>
            <form className="research-form" onSubmit={loadPredictions}>
              <label>
                Student ID
                <input
                  value={studentId}
                  onChange={e => setStudentId(e.target.value)}
                  required
                  type="number"
                  min="1"
                />
              </label>
              <button className="button" type="submit">
                Load predictions
              </button>
            </form>
            {predictions.length > 0 && (
              <div className="research-form">
                <label>
                  Prediction
                  <select value={predictionId} onChange={e => setPredictionId(e.target.value)}>
                    {predictions.map(p => (
                      <option value={p.id} key={p.id}>
                        #{p.id} · {p.prediction} · {p.timestamp}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="button" onClick={loadTrace}>
                  Trace calculation
                </button>
              </div>
            )}
            {predictions.length === 0 && studentId && (
              <p className="research-note">Enter a student ID and load stored predictions.</p>
            )}
          </Card>

          {model && (
            <Card>
              <div className="card-kicker">IMPLEMENTED FEATURE PARAMETERS</div>
              <p>
                Memory: recency weight exp(−λ · age days), λ={fmt(model.hyperparameters?.decay_rate)}; repetition A(N)=1+α log(1+N), α={fmt(model.hyperparameters?.repetition_alpha)}; bounded memory scale={fmt(model.hyperparameters?.memory_scale)}.
              </p>
              <p>
                Momentum compares two windows of k={model.hyperparameters?.momentum_window} interactions with scale={fmt(model.hyperparameters?.momentum_scale)}. Scoring normalization and saved training parameters come from model version {model.model_version}.
              </p>
            </Card>
          )}

          {trace && (
            <>
              <Card>
                <div className="card-kicker">FEATURE SNAPSHOT</div>
                <p>
                  Context: {trace.context?.topic} / {trace.context?.subtopic ?? '—'} · difficulty{' '}
                  {trace.context?.difficulty} · attempts replayed {trace.attempt_count}. Raw history features and standardized scoring values are shown separately.
                </p>
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Class</th>
                        {(model?.features ?? []).map((f: string) => (
                          <th key={f}>{f}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {trace.classes?.map((label: string) => (
                        <tr
                          key={label}
                          className={
                            trace.prediction?.predicted_error === label ? 'trace-predicted' : ''
                          }
                        >
                          <th>{label}</th>
                          {(model?.features ?? []).map((f: string) => (
                            <td key={f}>{fmt(trace.scoring_features_by_class?.[label]?.[f])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <div className="card-kicker">
                  LEARNED WEIGHTS AND BIAS · {trace.model_version}
                </div>
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Class</th>
                        {(model?.features ?? []).map((f: string) => (
                          <th key={f}>{f}</th>
                        ))}
                        <th>Bias</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trace.classes?.map((label: string, i: number) => (
                        <tr
                          key={label}
                          className={
                            trace.prediction?.predicted_error === label ? 'trace-predicted' : ''
                          }
                        >
                          <th>{label}</th>
                          {(model?.features ?? []).map((_: string, j: number) => (
                            <td key={j}>{fmt(trace.weights?.[i]?.[j])}</td>
                          ))}
                          <td>{fmt(trace.bias?.[i])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <div className="card-kicker">
                  SELECTED CLASS SCORE · {trace.prediction?.predicted_error ?? 'NO RELIABLE PREDICTION'}
                </div>
                <p>
                  For each class z = b + Σ(weight × standardized feature). Contributions below are the actual selected class feature × learned weight.
                </p>
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Feature</th>
                        <th>Value</th>
                        <th>Weight</th>
                        <th>Contribution</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trace.contributions?.map((r: Record<string, any>) => (
                        <tr key={r.feature}>
                          <th>{r.label}</th>
                          <td>{fmt(r.value)}</td>
                          <td>{fmt(r.weight)}</td>
                          <td>{fmt(r.contribution)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p>
                  Bias:{' '}
                  {fmt(
                    trace.bias?.[trace.classes?.indexOf(trace.prediction?.predicted_error)]
                  )}{' '}
                  · Raw score: {fmt(trace.raw_scores?.[trace.prediction?.predicted_error])}
                </p>
              </Card>

              <Card>
                <div className="card-kicker">STABLE SOFTMAX AND OUTCOME</div>
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Class</th>
                        <th>Raw z</th>
                        <th>z − max(z)</th>
                        <th>exp(shifted z)</th>
                        <th>Probability</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trace.classes?.map((label: string) => (
                        <tr
                          key={label}
                          className={
                            trace.prediction?.predicted_error === label ? 'trace-predicted' : ''
                          }
                        >
                          <th>{label}</th>
                          <td>{fmt(trace.raw_scores?.[label])}</td>
                          <td>{fmt(trace.shifted_scores?.[label])}</td>
                          <td>{fmt(trace.exponentials?.[label])}</td>
                          <td>{fmt(trace.probabilities?.[label])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p>
                  Prediction:{' '}
                  <strong>
                    {trace.prediction?.predicted_error ?? 'No reliable prediction'}
                  </strong>{' '}
                  · Probability {fmt(trace.prediction?.probability)} · Confidence{' '}
                  {fmt(trace.prediction?.confidence)} · Data reliability{' '}
                  {fmt(trace.prediction?.data_reliability)}
                </p>
                <p className="research-note">
                  Confidence is probability × data reliability. Reliability summarizes history volume, topic relevance, concept coverage, and consistency. Trace verification: {trace.verification_status}.
                </p>
              </Card>
            </>
          )}
        </div>
      )}

      {mode === 'evaluation' && (
        <div className="research-stack">
          <Card>
            <div className="card-kicker">EXPERIMENT SELECTOR</div>
            <div className="research-form">
              <label>
                Comparison model
                <select
                  value={comparisonModel}
                  onChange={e => setComparisonModel(e.target.value)}
                >
                  <option value="all">All models</option>
                  {[
                    ...new Set(
                      (evaluation?.results ?? []).map((r: Record<string, any>) => r.model_name)
                    ),
                  ].map((x: any) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Ablation
                <select value={ablationFilter} onChange={e => setAblationFilter(e.target.value)}>
                  <option value="all">All ablations</option>
                  {[
                    ...new Set(
                      (ablations?.results ?? [])
                        .map((r: Record<string, any>) => r.removed_feature)
                        .filter(Boolean)
                    ),
                  ].map((x: any) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Calibration / confusion model
                <select
                  value={evaluationModel}
                  onChange={e => setEvaluationModel(e.target.value)}
                >
                  {[
                    'mistiq-ampa',
                    'majority',
                    'logistic_regression',
                    'decision_tree',
                    'random_forest',
                    'knn',
                  ].map(x => (
                    <option key={x} value={x}>
                      {x.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Seed
                <select
                  value={evaluationSeed}
                  onChange={e => setEvaluationSeed(e.target.value)}
                >
                  <option value="42">42</option>
                  <option value="123">123</option>
                </select>
              </label>
            </div>
          </Card>

          <Card>
            <div className="card-kicker">
              MODEL COMPARISON · {evaluation?.source ?? 'Loading'}
            </div>
            {evaluation?.available ? (
              <div className="research-table-wrap">
                <table className="research-table">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Seed</th>
                      {metricKeys.map(k => (
                        <th key={k}>{k.replace(/_/g, ' ')}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.results
                      .filter(
                        (row: Record<string, any>) =>
                          comparisonModel === 'all' || row.model_name === comparisonModel
                      )
                      .map((row: Record<string, any>, i: number) => (
                        <tr key={`${row.model_name}-${row.seed}-${i}`}>
                          <th>{row.model_name}</th>
                          <td>{row.seed}</td>
                          {metricKeys.map(k => (
                            <td key={k}>{fmt(Number(row[k]))}</td>
                          ))}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>No Phase 4 comparison results are present in the configured artifact.</p>
            )}
          </Card>

          <Card>
            <div className="card-kicker">ABLATION RESULTS · {ablations?.source}</div>
            {ablations?.available ? (
              <>
                <p>
                  ΔF1 is the ablation seed score minus the available full AMPA aggregate mean; the comparison file does not contain per-seed full model scores.
                </p>
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Experiment</th>
                        <th>Seed</th>
                        <th>Macro F1</th>
                        <th>ΔF1 vs full AMPA mean</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ablations.results
                        .filter(
                          (row: Record<string, any>) =>
                            ablationFilter === 'all' || row.removed_feature === ablationFilter
                        )
                        .map((row: Record<string, any>, i: number) => {
                          const base = evaluation?.results?.find(
                            (candidate: Record<string, any>) =>
                              candidate.model_name === 'MISTIQ-AMPA' &&
                              String(candidate.seed) === 'mean'
                          )
                          return (
                            <tr key={`${row.experiment_id}-${i}`}>
                              <th>{row.model_name}</th>
                              <td>{row.seed}</td>
                              <td>{fmt(Number(row.macro_f1))}</td>
                              <td>
                                {base
                                  ? fmt(Number(row.macro_f1) - Number(base.macro_f1))
                                  : '—'}
                              </td>
                            </tr>
                          )
                        })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p>No ablation output is available.</p>
            )}
          </Card>

          <div className="research-split">
            <Card>
              <div className="card-kicker">CALIBRATION · seed {calibration?.seed}</div>
              {calibration?.available ? (
                <>
                  <p>
                    Brier {fmt(calibration.result?.brier_score)} · ECE{' '}
                    {fmt(calibration.result?.ece)}
                  </p>
                  {calibration.result?.bins?.map((bin: Record<string, any>) => (
                    <div className="research-bin" key={bin.bin}>
                      <span>
                        {Number(bin.lower).toFixed(1)}–{Number(bin.upper).toFixed(1)}
                      </span>
                      <div>
                        <i
                          style={{
                            width: `${Math.min(100, bin.mean_confidence * 100)}%`,
                          }}
                        />
                        <b
                          style={{
                            left: `${Math.min(100, bin.accuracy * 100)}%`,
                          }}
                        />
                      </div>
                      <small>
                        n={bin.count}; confidence {fmt(bin.mean_confidence)}; accuracy{' '}
                        {fmt(bin.accuracy)}
                      </small>
                    </div>
                  ))}
                </>
              ) : (
                <p>Calibration artifact is not available.</p>
              )}
            </Card>

            <Card>
              <div className="card-kicker">CONFUSION MATRIX · seed {confusion?.seed}</div>
              {confusion?.available ? (
                <div className="research-table-wrap">
                  <table className="research-table">
                    <thead>
                      <tr>
                        <th>Actual \ Predicted</th>
                        {confusion.result?.labels?.map((x: string) => (
                          <th key={x}>{x}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {confusion.result?.matrix?.map((row: number[], i: number) => (
                        <tr key={i}>
                          <th>{confusion.result?.labels?.[i]}</th>
                          {row.map((val, j) => (
                            <td key={j}>{val}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p>Confusion matrix is not available for this selection.</p>
              )}
            </Card>
          </div>

          <Card>
            <div className="card-kicker">SEED ROBUSTNESS</div>
            {seeds?.available ? (
              <div className="research-table-wrap">
                <table className="research-table">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Metric</th>
                      <th>Mean</th>
                      <th>SD</th>
                      <th>Min</th>
                      <th>Max</th>
                      <th>Seeds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(seeds.results).flatMap(([name, metrics]: [string, any]) =>
                      Object.entries(metrics).map(([metric, stats]: [string, any]) => (
                        <tr key={`${name}-${metric}`}>
                          <th>{name}</th>
                          <td>{metric}</td>
                          <td>{fmt(stats.mean)}</td>
                          <td>{fmt(stats.std)}</td>
                          <td>{fmt(stats.min)}</td>
                          <td>{fmt(stats.max)}</td>
                          <td>{stats.seeds}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>Seed robustness results are unavailable.</p>
            )}
          </Card>

          <Card>
            <div className="card-kicker">LEARNING CURVES</div>
            {curves?.available && curves.results?.length ? (
              <div className="research-table-wrap">
                <table className="research-table">
                  <thead>
                    <tr>
                      <th>History attempts</th>
                      <th>Seed</th>
                      <th>Sample count</th>
                      <th>Macro F1</th>
                      <th>Accuracy</th>
                      <th>ECE</th>
                    </tr>
                  </thead>
                  <tbody>
                    {curves.results.map((r: Record<string, any>, i: number) => (
                      <tr key={i}>
                        <th>{r.history_attempts}</th>
                        <td>{r.seed}</td>
                        <td>{r.sample_count}</td>
                        <td>{fmt(r.metrics?.macro_f1)}</td>
                        <td>{fmt(r.metrics?.accuracy)}</td>
                        <td>{fmt(r.metrics?.ece)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>
                Learning-curve result file is unavailable or empty. Cold-start ranges are defined in the model, but no separate cold-start analysis is inferred here.
              </p>
            )}
          </Card>

          <Card>
            <div className="card-kicker">COLD-START PERFORMANCE</div>
            {coldStart?.available && coldStart.results?.length ? (
              <div className="research-table-wrap">
                <table className="research-table">
                  <thead>
                    <tr>
                      <th>History bucket</th>
                      <th>Seed</th>
                      <th>Policy</th>
                      <th>Samples</th>
                      <th>Status</th>
                      <th>Macro F1</th>
                      <th>Log loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coldStart.results.map((r: Record<string, any>, i: number) => (
                      <tr key={i}>
                        <th>{r.history_bucket}</th>
                        <td>{r.seed}</td>
                        <td>{r.confidence_policy}</td>
                        <td>{r.sample_count}</td>
                        <td>{r.status}</td>
                        <td>{r.metrics ? fmt(r.metrics.macro_f1) : 'Not scored'}</td>
                        <td>{r.metrics ? fmt(r.metrics.log_loss) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p>Cold-start analysis is unavailable.</p>
            )}
            <p className="research-note">
              AMPA confidence policy abstains from a reliable class prediction at four or fewer attempts. Small history buckets may contain too few held-out examples for performance estimates.
            </p>
          </Card>
        </div>
      )}
    </div>
  )
}
