import { useEffect, useMemo, useState } from 'react'
import { getFailureHistory, getResearchPrediction, getResearchStatus, getTrajectory } from '../services/projectReviewApi'
import type { FailureHistoryResponse, FailureHistoryRow, ResearchPrediction, ResearchStatus, TrajectoryResponse } from '../types/projectReview'
import type { EventConnectionState } from '../hooks/useProjectEvents'

type PredictionState = 'A' | 'B' | 'C' | 'D' | 'E'

interface MistiqFailureIntelligenceProps {
  projectId: number
  source: 'local' | 'github'
  sseState: EventConnectionState
  failureDna: Record<string, number>
  refreshToken: number
}

const pretty = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
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

function evidenceLevel(total: number): { label: string; segments: number } {
  if (total <= 0) return { label: 'NO EVIDENCE', segments: 0 }
  if (total <= 2) return { label: 'LOW', segments: 1 }
  if (total <= 4) return { label: 'MEDIUM', segments: 2 }
  return { label: 'HIGH', segments: 3 }
}

function Badge({ value }: { value: string }) {
  return <span className={`live-badge live-${String(value).toLowerCase()}`}>{pretty(value)}</span>
}

function locationOf(finding: FailureHistoryRow): string {
  if (finding.file) return `${finding.file}${finding.line ? `:${finding.line}` : ''}`
  if (finding.component) return finding.component
  return 'Project scope'
}

function whyItMatters(finding: FailureHistoryRow, reviewCount: number): string {
  const recurrence = finding.occurrences > 1
    ? `Detected in ${finding.occurrences} of ${reviewCount} persisted reviews, so this is a repeat observation rather than a one-off.`
    : `Detected in 1 of ${reviewCount} persisted reviews so far.`
  const confidence = Number.isFinite(finding.confidence)
    ? ` Analyzer confidence ${Math.round(finding.confidence * 100)}%.`
    : ' Analyzer confidence not available.'
  const state = finding.status === 'RESOLVED'
    ? ' It is resolved now and is kept here as failure history.'
    : ' It is currently open.'
  return `${recurrence}${confidence}${state}`
}

function TimelineItem({ finding, reviewCount }: { finding: FailureHistoryRow; reviewCount: number }) {
  return (
    <details className="fi-timeline-item">
      <summary>
        <Badge value={finding.severity} />
        <Badge value={finding.status} />
        <strong>{pretty(finding.category)}</strong>
        <span className="fi-occurrence">{finding.occurrences} of {reviewCount} reviews</span>
      </summary>
      <div className="fi-timeline-body">
        <dl>
          <dt>What</dt>
          <dd>{pretty(finding.category)} failure · {pretty(finding.severity)} severity{Number.isFinite(finding.confidence) ? ` · ${Math.round(finding.confidence * 100)}% analyzer confidence` : ''}</dd>
          <dt>Where</dt>
          <dd>{locationOf(finding)}</dd>
          <dt>When</dt>
          <dd>First seen {when(finding.first_seen)} · Last seen {when(finding.last_seen)} · reviews {finding.review_numbers.join(', ') || 'Not available'}</dd>
          <dt>Evidence</dt>
          <dd>{finding.evidence} <small>(source: {finding.analyzer_source})</small></dd>
          <dt>Why it matters</dt>
          <dd>{whyItMatters(finding, reviewCount)}</dd>
          <dt>Recommended action</dt>
          <dd>{finding.remediation}</dd>
          {finding.status === 'RESOLVED' && <>
            <dt>Resolution</dt>
            <dd>{finding.resolution_evidence || 'No resolution evidence was recorded.'} · resolved {when(finding.resolved_at)}{finding.related_commit ? ` · commit ${finding.related_commit}` : ''}</dd>
          </>}
        </dl>
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
    return <p className="fi-meta">Evaluation requirements: Not available from the research status response.</p>
  }
  const moreObservations = Math.max(0, requirements.min_observations - observations)
  const moreCategories = Math.max(0, requirements.min_distinct_categories - categories)
  const moreTimepoints = timepoints === null ? null : Math.max(0, requirements.min_distinct_timepoints - timepoints)
  return (
    <ul className="fi-requirements">
      <li>Training observations: <strong>{observations}</strong> of {requirements.min_observations} required{moreObservations > 0 ? ` — ${moreObservations} more needed` : ' — requirement met'}</li>
      <li>Distinct failure categories: <strong>{categories}</strong> of {requirements.min_distinct_categories} required{moreCategories > 0 ? ` — ${moreCategories} more needed` : ' — requirement met'}</li>
      <li>Distinct review timepoints: <strong>{timepoints === null ? 'Not available' : timepoints}</strong> of {requirements.min_distinct_timepoints} required{moreTimepoints === null ? '' : moreTimepoints > 0 ? ` — ${moreTimepoints} more needed` : ' — requirement met'}</li>
      <li>Dataset status: <strong>{status.status}</strong></li>
      <li>Model status: <strong>{status.model_status}</strong>{status.model_detail ? ` — ${status.model_detail}` : ''}</li>
    </ul>
  )
}

function PredictionOutput({ prediction }: { prediction: ResearchPrediction }) {
  const evidence = prediction.historical_evidence as Record<string, unknown> | undefined
  const observed = Array.isArray(evidence?.observed_categories) ? (evidence.observed_categories as string[]) : []
  const model = prediction.model as Record<string, unknown> | undefined
  const training = prediction.training_metadata as Record<string, unknown> | undefined
  return (
    <div className="fi-prediction-output">
      <p className="fi-meta">Most likely next failure categories from the saved MISTIQ-APR artifact:</p>
      <div className="fi-prediction-list">
        {(prediction.predictions || []).map(item => (
          <div className="fi-prediction-row" key={item.category}>
            <div><strong>{pretty(item.category)}</strong><b>{percent(item.probability)}</b></div>
            <div className="fi-track"><i style={{ width: `${Math.min(100, Math.max(0, item.probability * 100))}%` }} /></div>
          </div>
        ))}
      </div>
      <p className="fi-meta">
        Model: {String(model?.name || model?.model || 'MISTIQ-APR')}
        {model?.version ? ` v${String(model.version)}` : ''}
        {training?.training_observations !== undefined ? ` · trained on ${String(training.training_observations)} observations` : ''}
      </p>
      {evidence && (
        <dl className="fi-evidence-block">
          <dt>Reviews observed</dt><dd>{String(evidence.review_count ?? 'Not available')}</dd>
          <dt>Findings in latest review</dt><dd>{String(evidence.findings_in_latest_review ?? 'Not available')}</dd>
          <dt>Observed categories</dt><dd>{observed.length ? observed.map(pretty).join(', ') : 'None recorded'}</dd>
          <dt>Transitions observed</dt><dd>{String(evidence.transition_count ?? 'Not available')}</dd>
          {evidence.note ? (<><dt>Note</dt><dd>{String(evidence.note)}</dd></>) : null}
        </dl>
      )}
      {Array.isArray(prediction.supporting_features) && prediction.supporting_features.length > 0 && (
        <details className="fi-features">
          <summary>Supporting features</summary>
          <ul>
            {prediction.supporting_features.slice(0, 8).map(feature => (
              <li key={feature.feature}>{pretty(feature.feature)}: {feature.value.toFixed(4)} ({feature.direction})</li>
            ))}
          </ul>
        </details>
      )}
      <p className="fi-disclaimer">{prediction.disclaimer || 'Predictions come from a trained artifact and describe historical association. They are not certainties and do not imply causation.'}</p>
    </div>
  )
}

export function MistiqFailureIntelligence({ projectId, source, sseState, failureDna, refreshToken }: MistiqFailureIntelligenceProps) {
  const [history, setHistory] = useState<FailureHistoryResponse | null>(null)
  const [trajectory, setTrajectory] = useState<TrajectoryResponse | null>(null)
  const [researchStatus, setResearchStatus] = useState<ResearchStatus | null>(null)
  const [prediction, setPrediction] = useState<ResearchPrediction | null>(null)
  const [errors, setErrors] = useState<{ history?: string; trajectory?: string; status?: string; prediction?: string }>({})
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const settle = <T,>(promise: Promise<T>) => promise.then(value => ({ value })).catch((error: unknown) => ({ error: error instanceof Error ? error.message : 'Request failed.' }))
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
    return () => { cancelled = true }
  }, [projectId, refreshToken])

  const findings = history?.findings ?? []
  const summary = history?.summary
  const openFindings = useMemo(() => findings.filter(item => item.status !== 'RESOLVED'), [findings])
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
  const synthetic = repositoryPath.includes('showcase') || repositoryPath.includes('synthetic')
  const liveLabel = sseState === 'CONNECTED'
    ? 'LIVE · SSE CONNECTED'
    : sseState === 'STOPPED'
      ? 'MONITORING STOPPED'
      : sseState === 'DISCONNECTED'
        ? 'LIVE FEED DISCONNECTED'
        : `LIVE · ${sseState}`

  const topPredicted = state === 'C' && prediction?.predicted_category
    ? prediction.predicted_category
    : state === 'C' && prediction?.predictions?.length
      ? prediction.predictions[0].category
      : null
  const connectedFindings = topPredicted ? openFindings.filter(item => item.category === topPredicted).slice(0, 5) : []

  if (!history && !errors.history) {
    return (
      <section className="card fi-card" aria-label="MISTIQ-APR Failure Intelligence">
        <span className="card-kicker">MISTIQ-APR · Failure Intelligence</span>
        <h2>What failed, where, when, and what the model knows</h2>
        <p className="live-empty">Loading persisted failure history…</p>
      </section>
    )
  }

  return (
    <section className="card fi-card" aria-label="MISTIQ-APR Failure Intelligence">
      <header className="fi-header">
        <div>
          <span className="card-kicker">MISTIQ-APR · Failure Intelligence</span>
          <h2>What failed, where, when, and what the model knows</h2>
        </div>
        <div className="fi-badges">
          <span className={`fi-mode ${synthetic ? 'synthetic' : 'live'}`}>{synthetic ? 'SHOWCASE · SYNTHETIC DATA' : 'LIVE · ANALYZED REPOSITORY'}</span>
          <span className={`fi-live fi-${sseState.toLowerCase()}`}>{liveLabel}</span>
        </div>
      </header>

      <p className="fi-freshness">
        Source: {source === 'github' ? 'GitHub repository' : 'Local folder'} ·
        failure history last reviewed {summary ? when(summary.last_review_at) : 'Not available'} ·
        data refreshed {refreshedAt || 'Not available'}
      </p>

      {summary ? (
        <div className="fi-stats">
          <div><span>Open failures</span><strong>{summary.open_failure_count}</strong></div>
          <div><span>Resolved failures</span><strong>{summary.resolved_failure_count}</strong></div>
          <div><span>Reviews observed</span><strong>{summary.review_count}</strong></div>
          <div><span>Failure categories</span><strong>{summary.categories.length}</strong></div>
        </div>
      ) : (
        <div className="fi-error" role="alert">
          <strong>Failure history unavailable</strong>
          <p>{errors.history}</p>
        </div>
      )}

      <div className="fi-flow-block">
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
          <li className={researchStatus && researchStatus.evaluation_requirements && researchStatus.training_observations >= researchStatus.evaluation_requirements.min_observations ? 'ok' : 'warn'}>
            <span>Training dataset</span>
            <strong>{researchStatus ? `${researchStatus.training_observations} observations` : 'Not available'}</strong>
          </li>
          <li className={state === 'C' ? 'ok' : state === 'E' ? 'error' : 'warn'}>
            <span>Next-failure prediction</span>
            <strong>{STATE_FLOW_LABEL[state]}</strong>
          </li>
        </ol>
        <p className="fi-note">Each stage shows persisted counts only. The stages are a data path, not a causal chain.</p>
      </div>

      <div className="fi-section">
        <h3>Failure history timeline <span className="fi-note">chronological · persisted reviews</span></h3>
        {errors.history ? (
          <div className="fi-error" role="alert"><strong>Failure history unavailable</strong><p>{errors.history}</p></div>
        ) : findings.length ? (
          <div className="fi-timeline">
            {findings.map(finding => <TimelineItem key={finding.fingerprint} finding={finding} reviewCount={summary?.review_count || findings.length} />)}
          </div>
        ) : (
          <p className="live-empty">{history?.message || 'No persisted failure history yet.'}</p>
        )}
      </div>

      <div className="fi-section">
        <h3>Observed failure transitions</h3>
        {errors.trajectory ? (
          <div className="fi-error" role="alert"><strong>Transition data unavailable</strong><p>{errors.trajectory}</p></div>
        ) : (
          <>
            {trajectory?.transitions.length ? (
              <div className="fi-transitions">
                {trajectory.transitions.map((edge, index) => (
                  <div key={`${edge.from}-${edge.to}-${index}`}>
                    <strong>{pretty(edge.from)}</strong><b>→</b><strong>{pretty(edge.to)}</strong>
                    <span>observed {edge.count} time{edge.count === 1 ? '' : 's'}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="live-empty">{trajectory?.message || 'Insufficient historical evidence for transition analysis.'}</p>
            )}
            <p className="fi-disclaimer">Observed failure transitions come from persisted review sequences. They describe what was recorded, and do not imply causation.</p>
            {trajectory?.loops.length ? (
              <div className="fi-loops">
                <h4>Recurring patterns</h4>
                {trajectory.loops.map((loop, index) => (
                  <p key={`${loop.pattern}-${index}`}>{loop.pattern} <span>observed {loop.occurrence_count} time{loop.occurrence_count === 1 ? '' : 's'}</span></p>
                ))}
              </div>
            ) : null}
            {findings.filter(item => item.occurrences > 1).length ? (
              <div className="fi-loops">
                <h4>Repeat failures</h4>
                {findings.filter(item => item.occurrences > 1).map(item => (
                  <p key={item.fingerprint}>{pretty(item.category)} <span>in {item.occurrences} of {summary?.review_count || '—'} reviews</span></p>
                ))}
              </div>
            ) : null}
          </>
        )}
      </div>

      <div className="fi-section">
        <h3>Failure DNA evidence</h3>
        <p className="fi-note">Levels are computed from persisted finding counts per category. No percentages are invented: exact counts are shown next to every level.</p>
        <div className="fi-dna">
          {Object.entries(failureDna).map(([dimension, engineRatio]) => {
            const category = DNA_CATEGORY[dimension] || dimension
            const counts = countsByCategory[category] || { open: 0, resolved: 0 }
            const level = evidenceLevel(counts.open + counts.resolved)
            return (
              <div className="fi-dna-row" key={dimension}>
                <div className="fi-dna-head">
                  <span>{pretty(dimension)}</span>
                  <b className={`fi-level fi-level-${level.label.toLowerCase().replace(' ', '-')}`}>{level.label}</b>
                </div>
                <div className="fi-dna-meter" aria-hidden="true">
                  {[0, 1, 2, 3].map(index => <i key={index} className={index < level.segments ? 'on' : ''} />)}
                </div>
                <small>
                  {counts.open} open · {counts.resolved} resolved observations in {pretty(category)}
                  {typeof engineRatio === 'number' ? ` · engine ratio ${engineRatio.toFixed(2)} (deterministic analyzer output, not a probability)` : ''}
                </small>
              </div>
            )
          })}
        </div>
      </div>

      <div className={`fi-section fi-prediction-card fi-state-${state.toLowerCase()}`}>
        <h3>Next-failure prediction <span className={`fi-state-badge fi-state-badge-${state.toLowerCase()}`}>{STATE_LABEL[state]}</span></h3>

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
          <>
            <p className="fi-state-message">No failure has been persisted for this project yet. This is an observation state, not a training-data state: there is no failure evidence recorded, so there is nothing to predict from.</p>
            {researchStatus && <p className="fi-meta">MISTIQ-APR model: {researchStatus.model_status}{researchStatus.model_detail ? ` — ${researchStatus.model_detail}` : ''} · dataset {researchStatus.status}</p>}
            {prediction?.available && <PredictionOutput prediction={prediction} />}
            {!prediction?.available && prediction?.reason && <p className="fi-meta">Prediction for this project: {prediction.reason}</p>}
          </>
        )}

        {state === 'B' && researchStatus && (
          <>
            <p className="fi-state-message">Failure history exists ({summary?.open_failure_count ?? 0} open, {summary?.resolved_failure_count ?? 0} resolved across {summary?.review_count ?? 0} reviews), but no trained MISTIQ-APR model is available for this dataset, so next-failure prediction is withheld rather than guessed.</p>
            <RequirementList status={researchStatus} />
          </>
        )}

        {state === 'C' && prediction && <PredictionOutput prediction={prediction} />}

        {state === 'D' && prediction && (
          <>
            <p className="fi-state-message">A trained MISTIQ-APR artifact exists, but no prediction could be produced for this project.</p>
            <ul className="fi-requirements">
              <li>Reason: <strong>{prediction.reason || 'Not available'}</strong></li>
              <li>{prediction.message || 'No additional detail was returned.'}</li>
              {researchStatus && <li>Model status: <strong>{researchStatus.model_status}</strong>{researchStatus.model_detail ? ` — ${researchStatus.model_detail}` : ''}</li>}
            </ul>
          </>
        )}

        <div className="fi-connection">
          <h4>Evidence connected to the prediction</h4>
          {state === 'C' && topPredicted ? (
            connectedFindings.length ? (
              <>
                <p className="fi-note">Open findings matched to the top predicted category ({pretty(topPredicted)}) by category only. This is an observed association, not causation.</p>
                <ul className="fi-connected-list">
                  {connectedFindings.map(item => (
                    <li key={item.fingerprint}><Badge value={item.severity} /><strong>{pretty(item.category)}</strong><span>{locationOf(item)}</span><small>{item.occurrences} of {summary?.review_count || '—'} reviews · {item.evidence}</small></li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="fi-note">No open finding currently matches the top predicted category ({pretty(topPredicted)}).</p>
            )
          ) : state === 'A' ? (
            <p className="fi-note">Nothing to connect: no failure has been recorded for this project.</p>
          ) : state === 'B' ? (
            <p className="fi-note">The data path stops at the training dataset: {researchStatus ? `${researchStatus.training_observations} of ${researchStatus.evaluation_requirements?.min_observations ?? 'Not available'} required observations` : 'research status unavailable'}.</p>
          ) : state === 'D' ? (
            <p className="fi-note">The model exists but returned no prediction for this project: {prediction?.reason || 'Not available'}</p>
          ) : (
            <p className="fi-note">Connection unknown while prediction data fails to load.</p>
          )}
        </div>
      </div>
    </section>
  )
}
