import { useEffect, useMemo, useState } from 'react'
import {
  getCodeIntelligence,
  getFailureHistory,
  getResearchPrediction,
  getResearchStatus,
  getTrajectory,
  requestRemediation,
} from '../services/projectReviewApi'
import type {
  CodeIntelligencePreview,
  CodeIntelligenceRiskRegion,
  FailureHistoryResponse,
  FailureHistoryRow,
  RemediationResponse,
  ResearchPrediction,
  ResearchStatus,
  TrajectoryResponse,
} from '../types/projectReview'
import type { EventConnectionState } from '../hooks/useProjectEvents'
import { dimensionLabel } from '../utils/labels'

type PredictionState = 'A' | 'B' | 'C' | 'D' | 'E'

const PREDICTION_INTRO =
  'ApexIQ learns from how engineering problems appear and change across project reviews to identify recurring patterns and estimate what type of problem may appear next.'
const PREDICTION_CONTEXT =
  'Prediction is based on historical project observations and current project state. It is not a certainty or causal estimate.'
const NO_HISTORY_YET =
  'ApexIQ needs more project history before it can estimate the next failure category.'

interface MistiqFailureIntelligenceProps {
  projectId: number
  source: 'local' | 'github'
  sseState: EventConnectionState
  failureDna: Record<string, number>
  refreshToken: number
}

const pretty = (value: string) =>
  value.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : 'Not available')
const percent = (value: number) => `${(value * 100).toFixed(1)}%`

const STATE_LABEL: Record<PredictionState, string> = {
  A: 'A · NO FAILURE HISTORY YET',
  B: 'B · FAILURE HISTORY EXISTS · MODEL NOT TRAINED',
  C: 'C · TRAINED MODEL PREDICTION AVAILABLE',
  D: 'D · TRAINED MODEL · PREDICTION UNAVAILABLE',
  E: 'E · ERROR LOADING PREDICTION DATA',
}

const STATE_FLOW_LABEL: Record<PredictionState, string> = {
  A: 'No failure history',
  B: 'Not trained',
  C: 'Available',
  D: 'Unavailable',
  E: 'Error',
}

const EVIDENCE_STATE_LABEL: Record<string, string> = {
  verified_finding: 'Verified finding',
  potential_risk: 'Potential risk',
  model_ranked_candidate: 'Model-ranked review candidate',
  unknown_insufficient_evidence: 'Unknown / insufficient evidence',
}

const DNA_CATEGORY: Record<string, string> = {
  testing_deficiency: 'testing',
  dependency_risk: 'dependency',
  integration_fragility: 'integration',
  security_risk: 'security',
  requirement_ambiguity: 'requirements',
  architecture_coupling: 'architecture',
  validation_weakness: 'input_validation',
  authorization_risk: 'authorization',
  configuration_drift: 'configuration',
  error_handling_weakness: 'error_handling',
  database_risk: 'data_integrity',
  deployment_risk: 'deployment',
  observability_weakness: 'observability',
}

function evidenceLevel(total: number): { key: string; label: string; segments: number } {
  if (total <= 0) return { key: 'no-evidence', label: 'NO EVIDENCE', segments: 0 }
  if (total <= 2) return { key: 'low', label: 'LOW EVIDENCE', segments: 3 }
  if (total <= 4) return { key: 'medium', label: 'MEDIUM EVIDENCE', segments: 6 }
  return { key: 'high', label: 'HIGH EVIDENCE', segments: 10 }
}

function Badge({ value }: { value: string }) {
  return (
    <span className={`live-badge live-${String(value).toLowerCase()}`}>
      {pretty(value)}
    </span>
  )
}

function locationOf(finding: FailureHistoryRow): string {
  if (finding.file) return `${finding.file}${finding.line ? `:${finding.line}` : ''}`
  if (finding.component) return finding.component
  return 'Project scope'
}

function whyItMatters(finding: FailureHistoryRow, reviewCount: number): string {
  const recurrence =
    finding.occurrences > 1
      ? `Detected in ${finding.occurrences} of ${reviewCount} persisted reviews, so this is a repeat observation rather than a one-off.`
      : `Detected in 1 of ${reviewCount} persisted reviews so far.`
  const confidence = Number.isFinite(finding.confidence)
    ? ` Analyzer confidence ${Math.round(finding.confidence * 100)}%.`
    : ' Analyzer confidence not available.'
  const state =
    finding.status === 'RESOLVED'
      ? ' It is resolved now and is kept here as failure history.'
      : ' It is currently open.'
  return `${recurrence}${confidence}${state}`
}

function TimelineItem({
  finding,
  reviewCount,
  onRemediate,
}: {
  finding: FailureHistoryRow
  reviewCount: number
  onRemediate?: (finding: FailureHistoryRow) => void
}) {
  return (
    <details className="fi-timeline-item card">
      <summary className="fi-timeline-summary">
        <div className="fi-summary-badges">
          <Badge value={finding.severity} />
          <Badge value={finding.status} />
        </div>
        <strong className="fi-summary-category">{pretty(finding.category)}</strong>
        <span className="fi-occurrence">
          {finding.occurrences} of {reviewCount} reviews
        </span>
        <span className="fi-summary-chevron">▾</span>
      </summary>

      <div className="fi-timeline-body">
        <dl>
          <dt>What</dt>
          <dd>
            {pretty(finding.category)} failure · {pretty(finding.severity)} severity
            {Number.isFinite(finding.confidence)
              ? ` · ${Math.round(finding.confidence * 100)}% analyzer confidence`
              : ''}
          </dd>
          <dt>Where</dt>
          <dd>{locationOf(finding)}</dd>
          <dt>When</dt>
          <dd>
            First seen {when(finding.first_seen)} · Last seen {when(finding.last_seen)} · reviews{' '}
            {finding.review_numbers.join(', ') || 'Not available'}
          </dd>
          <dt>Evidence</dt>
          <dd>
            {finding.evidence} <small>(source: {finding.analyzer_source})</small>
          </dd>
          <dt>Why it matters</dt>
          <dd>{whyItMatters(finding, reviewCount)}</dd>
          <dt>Recommended action</dt>
          <dd>{finding.remediation}</dd>
          {finding.status === 'RESOLVED' && (
            <>
              <dt>Resolution</dt>
              <dd>
                {finding.resolution_evidence || 'No resolution evidence was recorded.'} · resolved{' '}
                {when(finding.resolved_at)}
                {finding.related_commit ? ` · commit ${finding.related_commit}` : ''}
              </dd>
            </>
          )}
        </dl>
        {finding.status !== 'RESOLVED' && onRemediate && (
          <div style={{ marginTop: '0.75rem' }}>
            <button
              type="button"
              className="button secondary"
              onClick={() => onRemediate(finding)}
            >
              Generate AI Remediation
            </button>
          </div>
        )}
      </div>
    </details>
  )
}

function RequirementList({ status }: { status: ResearchStatus }) {
  const requirements = status.evaluation_requirements
  const observations = status.training_observations
  const categories = status.failure_categories
  const timepoints = status.distinct_timepoints ?? null
  if (!requirements) {
    return (
      <p className="fi-meta">
        Evaluation requirements: Not available from the research status response.
      </p>
    )
  }
  const moreObservations = Math.max(0, requirements.min_observations - observations)
  const moreCategories = Math.max(0, requirements.min_distinct_categories - categories)
  const moreTimepoints =
    timepoints === null
      ? null
      : Math.max(0, requirements.min_distinct_timepoints - timepoints)
  return (
    <ul className="fi-requirements">
      <li>
        Training observations: <strong>{observations}</strong> of{' '}
        {requirements.min_observations} required
        {moreObservations > 0 ? ` — ${moreObservations} more needed` : ' — requirement met'}
      </li>
      <li>
        Distinct failure categories: <strong>{categories}</strong> of{' '}
        {requirements.min_distinct_categories} required
        {moreCategories > 0 ? ` — ${moreCategories} more needed` : ' — requirement met'}
      </li>
      <li>
        Distinct review timepoints:{' '}
        <strong>{timepoints === null ? 'Not available' : timepoints}</strong> of{' '}
        {requirements.min_distinct_timepoints} required
        {moreTimepoints === null
          ? ''
          : moreTimepoints > 0
          ? ` — ${moreTimepoints} more needed`
          : ' — requirement met'}
      </li>
      <li>
        Dataset status: <strong>{status.status}</strong>
      </li>
      <li>
        Model status: <strong>{status.model_status}</strong>
        {status.model_detail ? ` — ${status.model_detail}` : ''}
      </li>
    </ul>
  )
}

function formatFeatureValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(4)
}

function PredictionOutput({ prediction }: { prediction: ResearchPrediction }) {
  const evidence = prediction.historical_evidence as Record<string, unknown> | undefined
  const observed = Array.isArray(evidence?.observed_categories)
    ? (evidence.observed_categories as string[])
    : []
  const model = prediction.model as Record<string, unknown> | undefined
  const training = prediction.training_metadata as Record<string, unknown> | undefined
  const features = Array.isArray(prediction.supporting_features)
    ? prediction.supporting_features
    : []
  const predicted =
    prediction.predicted_category || prediction.predictions?.[0]?.category || ''
  const reviewCount = evidence?.review_count
  const transitionCount = evidence?.transition_count
  const latestFindings = evidence?.findings_in_latest_review
  const trainingObservations =
    training?.training_observations ?? model?.training_observations
  const modelName = `${String(model?.name || model?.model || 'Apex-APR')}${
    model?.version ? ` v${String(model.version)}` : ''
  }`
  const topFeatures = features.slice(0, 3)
  const uncertainty = prediction.uncertainty

  return (
    <div className="fi-prediction-output">
      <div className="fi-pred-hero">
        <p className="fi-meta">Most likely next issue:</p>
        <div className="fi-prediction-list">
          {(prediction.predictions || []).map((item, idx) => (
            <div
              className={`fi-prediction-row ${idx === 0 ? 'fi-pred-top' : ''}`}
              key={item.category}
            >
              <div className="fi-pred-label-row">
                <strong>{pretty(item.category)}</strong>
                <b>{percent(item.probability)}</b>
              </div>
              <div className="fi-track">
                <i
                  style={{
                    width: `${Math.min(100, Math.max(0, item.probability * 100))}%`,
                  }}
                />
              </div>
              {(item.historical_frequency !== undefined ||
                item.deterministic_risk_score !== undefined) && (
                <div className="fi-pred-submetrics" style={{ fontSize: '0.8rem', opacity: 0.85, marginTop: '0.25rem' }}>
                  <span>Model score: {(item.model_score ?? item.probability).toFixed(3)}</span>
                  {item.calibrated_probability !== undefined && item.calibrated_probability !== null && (
                    <span> · Calibrated: {percent(item.calibrated_probability)}</span>
                  )}
                  {item.historical_frequency !== undefined && (
                    <span> · Historical freq: {percent(item.historical_frequency)}</span>
                  )}
                  {item.deterministic_risk_score !== undefined && (
                    <span> · Deterministic risk: {item.deterministic_risk_score.toFixed(2)}</span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {uncertainty && (
        <div className="card" style={{ marginTop: '0.75rem', padding: '0.75rem' }}>
          <strong>
            Prediction Uncertainty: {pretty(uncertainty.level)}
          </strong>{' '}
          <small>
            (top-1 margin: {uncertainty.top_1_margin.toFixed(3)} · normalized entropy:{' '}
            {uncertainty.normalized_entropy.toFixed(3)})
          </small>
          <p className="fi-note" style={{ margin: '0.25rem 0 0' }}>
            {uncertainty.calibration_note}
          </p>
        </div>
      )}

      <section className="fi-why card" aria-label="Why this prediction">
        <h4>WHY THIS PREDICTION</h4>
        <ul>
          <li>
            Historical evidence:{' '}
            {observed.length
              ? `past reviews recorded ${observed.map(pretty).join(', ')}`
              : 'no categories recorded'}
            {typeof reviewCount === 'number' ? ` across ${reviewCount} persisted reviews` : ''}.
          </li>
          <li>
            Current project evidence:{' '}
            {typeof reviewCount === 'number'
              ? `${reviewCount} reviews`
              : 'review count not available'}
            {typeof transitionCount === 'number' ? ` · ${transitionCount} transitions` : ''}
            {typeof latestFindings === 'number'
              ? ` · ${latestFindings} findings in the latest review`
              : ''}
            .
          </li>
          <li>
            Most influential signals:{' '}
            {topFeatures.length
              ? `${topFeatures
                  .map(feature => `${pretty(feature.feature)} (${feature.direction})`)
                  .join(', ')}.`
              : 'no supporting features were returned by the saved model.'}
            {predicted ? ` ${pretty(predicted)} is the top predicted category.` : ''}
          </li>
        </ul>
      </section>

      <div className="fi-context-grid">
        <section className="fi-context-block card" aria-label="Model training data">
          <h4>MODEL TRAINING DATA</h4>
          <dl className="fi-evidence-block">
            <dt>Model:</dt>
            <dd>{modelName}</dd>
            <dt>Training observations:</dt>
            <dd>
              {trainingObservations !== undefined
                ? String(trainingObservations)
                : 'Not available'}
            </dd>
          </dl>
        </section>

        <section className="fi-context-block card" aria-label="Current project history">
          <h4>CURRENT PROJECT HISTORY</h4>
          <dl className="fi-evidence-block">
            <dt>Current project reviews:</dt>
            <dd>{reviewCount !== undefined ? String(reviewCount) : 'Not available'}</dd>
            <dt>Current project transitions:</dt>
            <dd>
              {transitionCount !== undefined ? String(transitionCount) : 'Not available'}
            </dd>
            <dt>Findings in latest review:</dt>
            <dd>
              {latestFindings !== undefined ? String(latestFindings) : 'Not available'}
            </dd>
            <dt>Observed categories:</dt>
            <dd>{observed.length ? observed.map(pretty).join(', ') : 'None recorded'}</dd>
            {evidence?.note ? (
              <>
                <dt>Note</dt>
                <dd>{String(evidence.note)}</dd>
              </>
            ) : null}
          </dl>
        </section>
      </div>

      <p className="fi-prediction-context">{PREDICTION_CONTEXT}</p>

      {features.length > 0 && (
        <details className="fi-features card">
          <summary>Show technical model features</summary>
          <ul>
            {features.map(feature => (
              <li key={feature.feature}>
                <span>
                  {pretty(feature.feature)}: {formatFeatureValue(feature.value)}
                </span>
                <small>
                  {feature.direction} · contribution {feature.contribution}
                  {feature.description ? ` — ${feature.description}` : ''}
                </small>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="fi-disclaimer">
        {prediction.disclaimer ||
          'Predictions come from a trained artifact and describe historical association. They are not certainties and do not imply causation.'}
      </p>
    </div>
  )
}

export function MistiqFailureIntelligence({
  projectId,
  source,
  sseState,
  failureDna,
  refreshToken,
}: MistiqFailureIntelligenceProps) {
  const [history, setHistory] = useState<FailureHistoryResponse | null>(null)
  const [trajectory, setTrajectory] = useState<TrajectoryResponse | null>(null)
  const [researchStatus, setResearchStatus] = useState<ResearchStatus | null>(null)
  const [prediction, setPrediction] = useState<ResearchPrediction | null>(null)
  const [errors, setErrors] = useState<{
    history?: string
    trajectory?: string
    status?: string
    prediction?: string
  }>({})
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null)
  const [onDemandCodeIntel, setOnDemandCodeIntel] = useState<CodeIntelligencePreview | null>(null)
  const [codeIntelLoading, setCodeIntelLoading] = useState(false)
  const [remediationResult, setRemediationResult] = useState<RemediationResponse | null>(null)
  const [remediationBusy, setRemediationBusy] = useState(false)
  const [remediationError, setRemediationError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const settle = <T,>(promise: Promise<T>) =>
      promise
        .then(value => ({ value }))
        .catch((error: unknown) => ({
          error: error instanceof Error ? error.message : 'Request failed.',
        }))
    Promise.all([
      settle(getFailureHistory(projectId)),
      settle(getTrajectory(projectId)),
      settle(getResearchStatus()),
      settle(getResearchPrediction(projectId)),
    ]).then(([historyResult, trajectoryResult, statusResult, predictionResult]) => {
      if (cancelled) return
      setHistory('value' in historyResult ? historyResult.value : null)
      setTrajectory('value' in trajectoryResult ? trajectoryResult.value : null)
      setResearchStatus('value' in statusResult ? statusResult.value : null)
      setPrediction('value' in predictionResult ? predictionResult.value : null)
      setErrors({
        history: 'error' in historyResult ? historyResult.error : undefined,
        trajectory: 'error' in trajectoryResult ? trajectoryResult.error : undefined,
        status: 'error' in statusResult ? statusResult.error : undefined,
        prediction: 'error' in predictionResult ? predictionResult.error : undefined,
      })
      setRefreshedAt(new Date().toLocaleTimeString())
    })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshToken])

  const findings = history?.findings ?? []
  const summary = history?.summary
  const openFindings = useMemo(
    () => findings.filter(item => item.status !== 'RESOLVED'),
    [findings]
  )
  const countsByCategory = useMemo(() => {
    const counts: Record<string, { open: number; resolved: number }> = {}
    for (const item of findings) {
      const entry = counts[item.category] || { open: 0, resolved: 0 }
      if (item.status === 'RESOLVED') entry.resolved += 1
      else entry.open += 1
      counts[item.category] = entry
    }
    return counts
  }, [findings])

  const dataError = errors.history || errors.status || errors.prediction
  const modelTrained = researchStatus?.model_status === 'TRAINED'
  const state: PredictionState = dataError
    ? 'E'
    : !summary || summary.distinct_failure_count === 0
    ? 'A'
    : !modelTrained
    ? 'B'
    : prediction?.available
    ? 'C'
    : 'D'

  const repositoryPath = history?.project.repository_path.toLowerCase() || ''
  const synthetic =
    repositoryPath.includes('showcase') || repositoryPath.includes('synthetic')
  const liveLabel =
    sseState === 'CONNECTED'
      ? 'LIVE · SSE CONNECTED'
      : sseState === 'STOPPED'
      ? 'MONITORING STOPPED'
      : sseState === 'DISCONNECTED'
      ? 'LIVE FEED DISCONNECTED'
      : `LIVE · ${sseState}`

  const topPredicted =
    state === 'C' && prediction?.predicted_category
      ? prediction.predicted_category
      : state === 'C' && prediction?.predictions?.length
      ? prediction.predictions[0].category
      : null
  const connectedFindings = topPredicted
    ? openFindings.filter(item => item.category === topPredicted).slice(0, 5)
    : []

  const activeCodeIntel = onDemandCodeIntel || prediction?.code_intelligence || null
  const riskRegions: CodeIntelligenceRiskRegion[] = activeCodeIntel?.top_risk_regions || []

  async function handleLoadCodeIntelligence() {
    setCodeIntelLoading(true)
    try {
      const res = await getCodeIntelligence(projectId)
      setOnDemandCodeIntel({
        available: res.available,
        summary: res.summary,
        top_risk_regions: res.risk_regions || res.top_risk_regions || [],
      })
    } catch {
      // Ignore error if unavailable
    } finally {
      setCodeIntelLoading(false)
    }
  }

  async function handleRemediateRegion(region: CodeIntelligenceRiskRegion) {
    setRemediationBusy(true)
    setRemediationError(null)
    try {
      const res = await requestRemediation(projectId, {
        file: region.file,
        start_line: region.start_line,
        end_line: region.end_line,
        category: region.category,
        title: region.title,
        explanation: region.explanation,
        state: region.state,
      })
      setRemediationResult(res)
    } catch (err) {
      setRemediationError(err instanceof Error ? err.message : 'Unable to generate remediation.')
    } finally {
      setRemediationBusy(false)
    }
  }

  async function handleRemediateFinding(finding: FailureHistoryRow) {
    setRemediationBusy(true)
    setRemediationError(null)
    try {
      const res = await requestRemediation(projectId, {
        file: finding.file,
        start_line: finding.line,
        end_line: finding.line,
        category: finding.category,
        title: `${pretty(finding.category)} finding`,
        explanation: finding.evidence,
        state: finding.file && finding.line ? 'verified_finding' : 'unknown_insufficient_evidence',
      })
      setRemediationResult(res)
    } catch (err) {
      setRemediationError(err instanceof Error ? err.message : 'Unable to generate remediation.')
    } finally {
      setRemediationBusy(false)
    }
  }

  if (!history && !errors.history) {
    return (
      <section className="card fi-card" aria-label="Apex-APR Failure Intelligence">
        <div className="fi-loading-box">
          <span className="card-kicker">Apex-APR</span>
          <h2>Failure Intelligence</h2>
          <p className="fi-intro">{PREDICTION_INTRO}</p>
          <div className="loading-state">
            <span className="loading-dot" aria-hidden="true" />
            <p className="live-empty">Loading persisted failure history…</p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="card fi-card" aria-label="Apex-APR Failure Intelligence">
      <header className="fi-header">
        <div>
          <span className="card-kicker">Apex-APR</span>
          <h2>Failure Intelligence</h2>
          <p className="fi-intro">{PREDICTION_INTRO}</p>
        </div>
        <div className="fi-badges">
          <span className={`fi-mode ${synthetic ? 'synthetic' : 'live'}`}>
            {synthetic ? 'SHOWCASE · SYNTHETIC DATA' : 'LIVE · ANALYZED REPOSITORY'}
          </span>
          <span className={`fi-live fi-${sseState.toLowerCase()}`}>{liveLabel}</span>
        </div>
      </header>

      <p className="fi-freshness">
        Source: {source === 'github' ? 'GitHub repository' : 'Local folder'} · failure
        history last reviewed {summary ? when(summary.last_review_at) : 'Not available'} ·
        data refreshed {refreshedAt || 'Not available'}
      </p>

      {summary ? (
        <div className="fi-stats-grid">
          <div className="fi-stat-card card">
            <span>Open failures</span>
            <strong>{summary.open_failure_count}</strong>
          </div>
          <div className="fi-stat-card card">
            <span>Resolved failures</span>
            <strong>{summary.resolved_failure_count}</strong>
          </div>
          <div className="fi-stat-card card">
            <span>Reviews observed</span>
            <strong>{summary.review_count}</strong>
          </div>
          <div className="fi-stat-card card">
            <span>Failure categories</span>
            <strong>{summary.categories.length}</strong>
          </div>
        </div>
      ) : (
        <div className="fi-error" role="alert">
          <strong>Failure history unavailable</strong>
          <p>{errors.history}</p>
        </div>
      )}

      {/* PIPELINE DATA PATH */}
      <div className="fi-flow-block card">
        <h3>From active findings to next-failure prediction</h3>
        <ol className="fi-flow">
          <li className={openFindings.length ? 'ok' : 'empty'}>
            <span>Active findings</span>
            <strong>{openFindings.length} open</strong>
          </li>
          <li className={summary && summary.review_count > 1 ? 'ok' : 'empty'}>
            <span>Failure history</span>
            <strong>{summary ? summary.review_count : 'Not available'} reviews</strong>
          </li>
          <li
            className={
              researchStatus &&
              researchStatus.evaluation_requirements &&
              researchStatus.training_observations >=
                researchStatus.evaluation_requirements.min_observations
                ? 'ok'
                : 'warn'
            }
          >
            <span>Training dataset</span>
            <strong>
              {researchStatus
                ? `${researchStatus.training_observations} observations`
                : 'Not available'}
            </strong>
          </li>
          <li className={state === 'C' ? 'ok' : state === 'E' ? 'error' : 'warn'}>
            <span>Next-failure prediction</span>
            <strong>{STATE_FLOW_LABEL[state]}</strong>
          </li>
        </ol>
        <p className="fi-note">
          Each stage shows persisted counts only. The stages are a data path, not a causal chain.
        </p>
      </div>

      {/* SECTION 1: FAILURE HISTORY */}
      <div className="fi-section">
        <div className="fi-section-head">
          <h3>FAILURE HISTORY</h3>
          <span className="fi-note">chronological · persisted reviews</span>
        </div>
        {errors.history ? (
          <div className="fi-error" role="alert">
            <strong>Failure history unavailable</strong>
            <p>{errors.history}</p>
          </div>
        ) : findings.length ? (
          <div className="fi-timeline">
            {findings.map(finding => (
              <TimelineItem
                key={finding.fingerprint}
                finding={finding}
                reviewCount={summary?.review_count || findings.length}
                onRemediate={handleRemediateFinding}
              />
            ))}
          </div>
        ) : (
          <p className="live-empty">{history?.message || 'No persisted failure history yet.'}</p>
        )}
      </div>

      {/* SECTION 2: FAILURE PATTERNS */}
      <div className="fi-section">
        <div className="fi-section-head">
          <h3>FAILURE PATTERNS</h3>
        </div>
        {errors.trajectory ? (
          <div className="fi-error" role="alert">
            <strong>Transition data unavailable</strong>
            <p>{errors.trajectory}</p>
          </div>
        ) : (
          <>
            {trajectory?.transitions.length ? (
              <div className="fi-transitions">
                {trajectory.transitions.map((edge, index) => (
                  <div
                    className="fi-transition-card card"
                    key={`${edge.from}-${edge.to}-${index}`}
                  >
                    <small className="fi-transition-kind">Observed historical pattern</small>
                    <div className="fi-transition-arrow-row">
                      <strong className="cat-pill">{pretty(edge.from)}</strong>
                      <b className="arrow-char">→</b>
                      <strong className="cat-pill">{pretty(edge.to)}</strong>
                    </div>
                    <span className="fi-transition-count">
                      observed {edge.count} time{edge.count === 1 ? '' : 's'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="live-empty">
                {trajectory?.message ||
                  'Insufficient historical evidence for transition analysis.'}
              </p>
            )}

            <p className="fi-disclaimer">
              Observed failure transitions come from persisted review sequences. Patterns show association, not causation.
            </p>

            {trajectory?.loops.length ? (
              <div className="fi-loops card">
                <h4>Recurring patterns</h4>
                {trajectory.loops.map((loop, index) => (
                  <p key={`${loop.pattern}-${index}`}>
                    {loop.pattern}{' '}
                    <span>
                      observed {loop.occurrence_count} time{loop.occurrence_count === 1 ? '' : 's'}
                    </span>
                  </p>
                ))}
              </div>
            ) : null}

            {findings.filter(item => item.occurrences > 1).length ? (
              <div className="fi-loops card">
                <h4>Repeat failures</h4>
                {findings
                  .filter(item => item.occurrences > 1)
                  .map(item => (
                    <p key={item.fingerprint}>
                      {pretty(item.category)}{' '}
                      <span>
                        in {item.occurrences} of {summary?.review_count || '—'} reviews
                      </span>
                    </p>
                  ))}
              </div>
            ) : null}
          </>
        )}
      </div>

      {/* SECTION 3: FAILURE DNA */}
      <div className="fi-section">
        <div className="fi-section-head">
          <h3>FAILURE DNA</h3>
          <p className="fi-note">
            Levels are computed from persisted finding counts per category. Engine ratios are deterministic analyzer output, not probabilities. No percentages are invented: exact counts are shown next to every level.
          </p>
        </div>

        <div className="fi-dna">
          {Object.entries(failureDna).map(([dimension, engineRatio]) => {
            const category = DNA_CATEGORY[dimension] || dimension
            const counts = countsByCategory[category] || { open: 0, resolved: 0 }
            const total = counts.open + counts.resolved
            const level = evidenceLevel(total)
            const empty = level.segments === 0
            return (
              <div
                className={`fi-dna-row card ${empty ? 'fi-dna-row-empty' : ''}`}
                key={dimension}
              >
                <div className="fi-dna-head">
                  <span className="fi-dna-dim-title">{dimensionLabel(dimension)}</span>
                  <b className={`fi-level fi-level-${level.key}`}>{level.label}</b>
                </div>

                <div className="fi-dna-meter" aria-hidden="true">
                  {Array.from({ length: 10 }, (_, index) => (
                    <i key={index} className={index < level.segments ? 'on' : ''} />
                  ))}
                </div>

                <div className="fi-dna-counts-row">
                  <small className="fi-dna-counts">
                    {counts.open} open · {counts.resolved} resolved
                  </small>
                  <small className="fi-dna-observations">
                    {total} supporting observation{total === 1 ? '' : 's'} in {pretty(category)}
                  </small>
                </div>

                {empty && (
                  <small className="fi-dna-empty-note">
                    No evidence currently supports this risk dimension.
                  </small>
                )}

                {(total > 0 || engineRatio > 0) && (
                  <small className="fi-dna-ratio">
                    Engine ratio {engineRatio.toFixed(2)} is deterministic analyzer output, not a probability.
                  </small>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* SECTION 4: NEXT FAILURE PREDICTION */}
      <div className={`fi-section fi-prediction-card fi-state-${state.toLowerCase()}`}>
        <div className="fi-section-head">
          <h3>
            NEXT FAILURE PREDICTION{' '}
            <span className={`fi-state-badge fi-state-badge-${state.toLowerCase()}`}>
              {STATE_LABEL[state]}
            </span>
          </h3>
        </div>

        {state === 'E' && (
          <div className="fi-error" role="alert">
            <strong>Prediction data could not be loaded.</strong>
            <p>This is an error state, not an insufficient-data state. The actual errors:</p>
            <ul>
              {errors.history && <li>Failure history: {errors.history}</li>}
              {errors.status && <li>Research status: {errors.status}</li>}
              {errors.prediction && <li>Next-failure prediction: {errors.prediction}</li>}
            </ul>
          </div>
        )}

        {state === 'A' && (
          <div className="fi-state-content card">
            <p className="fi-state-message">
              No failure has been persisted for this project yet. This is an observation state, not a training-data state: there is no failure evidence recorded, so there is nothing to predict from.
            </p>
            <p className="fi-state-message">{NO_HISTORY_YET}</p>
            {researchStatus && (
              <p className="fi-meta">
                Apex-APR model: {researchStatus.model_status}
                {researchStatus.model_detail ? ` — ${researchStatus.model_detail}` : ''} ·
                dataset {researchStatus.status}
              </p>
            )}
            {prediction?.available && <PredictionOutput prediction={prediction} />}
            {!prediction?.available && prediction?.reason && (
              <p className="fi-meta">Prediction for this project: {prediction.reason}</p>
            )}
          </div>
        )}

        {state === 'B' && researchStatus && (
          <div className="fi-state-content card">
            <p className="fi-state-message">
              Failure history exists ({summary?.open_failure_count ?? 0} open,{' '}
              {summary?.resolved_failure_count ?? 0} resolved across{' '}
              {summary?.review_count ?? 0} reviews), but no trained Apex-APR model is available for this dataset, so next-failure prediction is withheld rather than guessed.
            </p>
            <RequirementList status={researchStatus} />
          </div>
        )}

        {state === 'C' && prediction && <PredictionOutput prediction={prediction} />}

        {state === 'D' && prediction && (
          <div className="fi-state-content card">
            <p className="fi-state-message">Not available yet</p>
            <p className="fi-state-message">
              A trained Apex-APR artifact exists, but no prediction could be produced for this project.
            </p>
            <p className="fi-state-message">{NO_HISTORY_YET}</p>
            <ul className="fi-requirements">
              <li>
                Reason: <strong>{prediction.reason || 'Not available'}</strong>
              </li>
              <li>{prediction.message || 'No additional detail was returned.'}</li>
              {researchStatus && (
                <li>
                  Model status: <strong>{researchStatus.model_status}</strong>
                  {researchStatus.model_detail ? ` — ${researchStatus.model_detail}` : ''}
                </li>
              )}
            </ul>
          </div>
        )}

        <div className="fi-connection card">
          <h4>Evidence connected to the prediction</h4>
          {state === 'C' && topPredicted ? (
            connectedFindings.length ? (
              <>
                <p className="fi-note">
                  Open findings matched to the top predicted category ({pretty(topPredicted)}) by category only. This is an observed association, not causation.
                </p>
                <ul className="fi-connected-list">
                  {connectedFindings.map(item => (
                    <li key={item.fingerprint}>
                      <Badge value={item.severity} />
                      <strong>{pretty(item.category)}</strong>
                      <span>{locationOf(item)}</span>
                      <small>
                        {item.occurrences} of {summary?.review_count || '—'} reviews ·{' '}
                        {item.evidence}
                      </small>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="fi-note">
                No open finding currently matches the top predicted category ({pretty(topPredicted)}).
              </p>
            )
          ) : state === 'A' ? (
            <p className="fi-note">
              Nothing to connect: no failure has been recorded for this project.
            </p>
          ) : state === 'B' ? (
            <p className="fi-note">
              The data path stops at the training dataset:{' '}
              {researchStatus
                ? `${researchStatus.training_observations} of ${
                    researchStatus.evaluation_requirements?.min_observations ?? 'Not available'
                  } required observations`
                : 'research status unavailable'}
              .
            </p>
          ) : state === 'D' ? (
            <p className="fi-note">
              The model exists but returned no prediction for this project:{' '}
              {prediction?.reason || 'Not available'}
            </p>
          ) : (
            <p className="fi-note">Connection unknown while prediction data fails to load.</p>
          )}
        </div>
      </div>

      {/* SECTION 5: CODE-LEVEL RISK LOCALIZATION & AI-ASSISTED REMEDIATION */}
      {(activeCodeIntel?.available || remediationResult || remediationBusy || remediationError) && (
        <div className="fi-section">
          <div className="fi-section-head">
            <h3>CODE-LEVEL RISK LOCALIZATION & AI REMEDIATION</h3>
            {!activeCodeIntel?.available && (
              <button
                type="button"
                className="button secondary"
                disabled={codeIntelLoading}
                onClick={handleLoadCodeIntelligence}
              >
                {codeIntelLoading ? 'Indexing repository…' : 'Scan source lines'}
              </button>
            )}
          </div>

          {activeCodeIntel?.summary && (
            <p className="fi-note">
              Indexed {activeCodeIntel.summary.indexed_files} files ({activeCodeIntel.summary.total_lines} lines,{' '}
              {activeCodeIntel.summary.total_symbols} symbols) ·{' '}
              {activeCodeIntel.summary.verified_line_findings_count} verified line findings ·{' '}
              {activeCodeIntel.summary.localized_risk_regions_count} localized review candidates.
            </p>
          )}

          {riskRegions.length > 0 && (
            <div className="fi-timeline" style={{ marginTop: '0.75rem' }}>
              {riskRegions.map((region, idx) => (
                <details className="fi-timeline-item card" key={`${region.file}:${region.start_line}:${idx}`}>
                  <summary className="fi-timeline-summary">
                    <div className="fi-summary-badges">
                      <Badge value={region.severity} />
                      <span className="live-badge">
                        {EVIDENCE_STATE_LABEL[region.state] || pretty(region.state)}
                      </span>
                    </div>
                    <strong className="fi-summary-category">
                      {region.file}:{region.start_line}
                      {region.end_line && region.end_line !== region.start_line ? `–${region.end_line}` : ''}
                    </strong>
                    <span className="fi-occurrence">{region.title}</span>
                    <span className="fi-summary-chevron">▾</span>
                  </summary>
                  <div className="fi-timeline-body">
                    <p>{region.explanation}</p>
                    {region.signals && region.signals.length > 0 && (
                      <ul>
                        {region.signals.map(sig => (
                          <li key={sig}>{sig}</li>
                        ))}
                      </ul>
                    )}
                    {region.code_excerpt && (
                      <pre style={{ overflowX: 'auto', padding: '0.5rem', fontSize: '0.8rem' }}>
                        <code>{region.code_excerpt}</code>
                      </pre>
                    )}
                    <button
                      type="button"
                      className="button secondary"
                      disabled={remediationBusy}
                      onClick={() => handleRemediateRegion(region)}
                    >
                      {remediationBusy ? 'Generating remediation…' : 'Generate AI Remediation'}
                    </button>
                  </div>
                </details>
              ))}
            </div>
          )}

          {remediationError && (
            <div className="fi-error" role="alert" style={{ marginTop: '0.75rem' }}>
              <strong>Remediation error</strong>
              <p>{remediationError}</p>
            </div>
          )}

          {remediationResult && (
            <div className="card" style={{ marginTop: '1rem', padding: '1rem' }} aria-label="AI-assisted remediation">
              <h4>
                AI-ASSISTED REMEDIATION ({remediationResult.provider === 'groq' ? `Groq · ${remediationResult.model}` : 'Deterministic Evidence Fallback'})
              </h4>
              <p className="fi-note">{remediationResult.message}</p>
              <dl>
                <dt>Summary</dt>
                <dd>{remediationResult.remediation.summary}</dd>
                <dt>Why it matters</dt>
                <dd>{remediationResult.remediation.why_it_matters}</dd>
                <dt>Evidence references</dt>
                <dd>{remediationResult.remediation.evidence_references.join(', ') || 'Project scope'}</dd>
                <dt>Suggested fix</dt>
                <dd>{remediationResult.remediation.suggested_fix}</dd>
              </dl>
              {remediationResult.remediation.patch && (
                <div style={{ marginTop: '0.75rem' }}>
                  <strong>Suggested Patch Preview (Human Review Only · Auto-Applied: No)</strong>
                  <pre style={{ overflowX: 'auto', padding: '0.75rem', fontSize: '0.8rem' }}>
                    <code>{remediationResult.remediation.patch}</code>
                  </pre>
                  <small className="fi-note">
                    Patch validation: {remediationResult.patch_validation.status} · Grounding verified:{' '}
                    {remediationResult.grounding_validation.passed ? 'Yes' : 'No'}
                  </small>
                </div>
              )}
              {remediationResult.remediation.tests_to_add.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <strong>Tests to add:</strong>
                  <ul>
                    {remediationResult.remediation.tests_to_add.map(t => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {remediationResult.remediation.validation_steps.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <strong>Validation steps:</strong>
                  <ul>
                    {remediationResult.remediation.validation_steps.map(step => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
