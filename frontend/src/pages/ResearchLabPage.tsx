import { useEffect, useState } from 'react'
import {
  getResearchDataset,
  getResearchEvaluation,
  getResearchPrediction,
  getResearchStatus,
  promoteCandidateModel,
  rollbackProductionModel,
} from '../services/projectReviewApi'
import type {
  AblationRow,
  RegistrySummary,
  ResearchEvaluationResponse,
  ResearchPrediction,
  ResearchStatus,
} from '../types/projectReview'
import '../styles/projectReview.css'
import '../styles/researchLab.css'

const pretty = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())
const num = (value?: number | null) => (typeof value === 'number' ? value.toFixed(4) : '—')

const BASELINE_ORDER = ['Majority Class', 'Latest Failure', 'Static Logistic Regression', 'Random Forest', 'MISTIQ-APR']
const BASELINE_LABELS: Record<string, string> = {
  'Majority Class': 'Majority',
  'Latest Failure': 'Latest Failure',
  'Static Logistic Regression': 'Static Logistic',
  'Random Forest': 'Random Forest',
  'MISTIQ-APR': 'Apex-APR',
}

export const PREDICTION_DISCLAIMER = 'Prediction is based on historical project observations and is not a certainty.'

export function ResearchLabPage() {
  const [status, setStatus] = useState<ResearchStatus | null>(null)
  const [projects, setProjects] = useState<Array<{ id: number; name: string }>>([])
  const [evaluation, setEvaluation] = useState<ResearchEvaluationResponse | null>(null)
  const [error, setError] = useState('')
  const [projectId, setProjectId] = useState('')
  const [prediction, setPrediction] = useState<ResearchPrediction | null>(null)
  const [predictionBusy, setPredictionBusy] = useState(false)
  const [predictionError, setPredictionError] = useState('')
  const [registryMessage, setRegistryMessage] = useState('')

  useEffect(() => {
    Promise.all([getResearchStatus(), getResearchDataset(), getResearchEvaluation()])
      .then(([nextStatus, dataset, nextEvaluation]) => {
        setStatus(nextStatus)
        setProjects(dataset.project_list)
        setEvaluation(nextEvaluation)
      })
      .catch(err => setError(err instanceof Error ? err.message : 'Unable to load the Apex-APR Research Lab.'))
  }, [])

  async function predict() {
    if (!projectId) return
    setPredictionBusy(true)
    setPredictionError('')
    setPrediction(null)
    try {
      setPrediction(await getResearchPrediction(Number(projectId)))
    } catch (err) {
      setPredictionError(err instanceof Error ? err.message : 'Prediction request failed.')
    } finally {
      setPredictionBusy(false)
    }
  }

  async function handlePromote(candidateId: string) {
    setRegistryMessage('')
    try {
      const res = await promoteCandidateModel(candidateId)
      if (res.promoted) {
        setRegistryMessage(`Promoted ${candidateId} to active production.`)
        const updatedStatus = await getResearchStatus()
        setStatus(updatedStatus)
      } else {
        setRegistryMessage(`Promotion refused: ${String(res.reason || 'Criteria not met')}`)
      }
    } catch (err) {
      setRegistryMessage(err instanceof Error ? err.message : 'Promotion failed.')
    }
  }

  async function handleRollback(targetCandidateId?: string) {
    setRegistryMessage('')
    try {
      const res = await rollbackProductionModel(targetCandidateId)
      if (res.rolled_back) {
        setRegistryMessage(`Rolled back production to ${String(res.active_candidate_id || 'v1.0')}.`)
        const updatedStatus = await getResearchStatus()
        setStatus(updatedStatus)
      }
    } catch (err) {
      setRegistryMessage(err instanceof Error ? err.message : 'Rollback failed.')
    }
  }

  if (error) return <div className="lab-page"><div className="error" role="alert">{error}</div></div>
  if (!status || !evaluation) return <div className="lab-page"><p className="muted">Loading the Apex-APR Research Lab…</p></div>

  const registry = status.registry || evaluation.registry

  return <div className="lab-page">
    <header className="lab-header">
      <span className="eyebrow">Apex-APR · Research infrastructure</span>
      <h1>Apex-APR Research Lab</h1>
      <p>Walk-forward temporal evaluation, automated leakage validation, ablation, calibration, immutable model registry, and artifact-backed prediction — reported only when real chronological review history supports them.</p>
    </header>

    <div className="lab-grid">
      <DatasetPanel status={status} />
      <ModelPanel status={status} />
      <LeakagePanel status={status} />
      <BaselinePanel evaluation={evaluation} />
    </div>

    {registry && (
      <ModelRegistryPanel
        registry={registry}
        message={registryMessage}
        onPromote={handlePromote}
        onRollback={handleRollback}
      />
    )}

    <WalkForwardPanel evaluation={evaluation} />
    <div className="lab-grid">
      <AblationPanel evaluation={evaluation} />
      <CalibrationPanel evaluation={evaluation} />
    </div>

    <PredictionPanel
      projects={projects}
      projectId={projectId}
      setProjectId={setProjectId}
      prediction={prediction}
      busy={predictionBusy}
      error={predictionError}
      predict={predict}
    />
  </div>
}

function DatasetPanel({ status }: { status: ResearchStatus }) {
  const range = status.date_range
  const audit = status.quality_audit
  const ingestion = status.ingestion
  return <section className="card lab-panel" aria-label="Dataset status">
    <span className="card-kicker">Dataset status</span>
    <h2>Chronological review history</h2>
    <div className="lab-stat-grid">
      <div><span>Projects</span><strong>{status.projects}</strong></div>
      <div><span>Reviews</span><strong>{status.reviews}</strong></div>
      <div><span>Transitions</span><strong>{status.transitions}</strong></div>
      <div><span>Training observations</span><strong>{status.training_observations}</strong></div>
      <div><span>Failure categories</span><strong>{status.failure_categories}</strong></div>
      <div><span>Date range</span><strong className="lab-small">{range ? `${range.first} → ${range.last}` : '—'}</strong></div>
    </div>
    {audit && (
      <div className="lab-meta" style={{ marginTop: '0.5rem' }}>
        <p>Real repository groups: {audit.unique_real_repository_groups} ({audit.real_projects} real DB rows, {audit.synthetic_temp_projects} synthetic test rows)</p>
        <p>Unique feature vectors: {audit.unique_feature_vectors} · Duplicate rate in raw DB: {audit.duplicate_observation_percentage}%</p>
      </div>
    )}
    {ingestion && ingestion.curated_observations_count ? (
      <div className="lab-meta" style={{ marginTop: '0.5rem' }}>
        <p>Curated Git dataset ({ingestion.dataset_version}): {ingestion.curated_observations_count} non-duplicate observations across {ingestion.distinct_repository_groups_in_dataset} real repositories ({ingestion.secret_redactions_applied ?? 0} secret redactions)</p>
      </div>
    ) : null}
    <p className={`lab-badge ${status.status.startsWith('READY') ? 'ok' : 'warn'}`}>{status.status}</p>
    <p className="muted">{status.message}</p>
  </section>
}

function ModelPanel({ status }: { status: ResearchStatus }) {
  const tone = status.model_status === 'TRAINED' ? 'ok' : status.model_status === 'INSUFFICIENT DATA' ? 'warn' : 'fail'
  const metadata = status.artifact
  return <section className="card lab-panel" aria-label="Model status">
    <span className="card-kicker">Model status</span>
    <h2>Apex-APR artifact</h2>
    <p className={`lab-badge ${tone}`} data-testid="model-status">{status.model_status}</p>
    {status.model_detail && <p className="muted">{status.model_detail}</p>}
    {metadata && <div className="lab-meta">
      <p>Version: {String(metadata.version ?? '—')}</p>
      <p>Algorithm: {String(metadata.algorithm ?? 'logistic_regression')}</p>
      <p>Trained at: {String(metadata.trained_at ?? '—')}</p>
      <p>Training observations: {String(metadata.training_observations ?? '—')}</p>
      <p>Dataset hash: {String(metadata.dataset_hash ?? '—')}</p>
      <p>Protocol: {String(metadata.evaluation_protocol ?? '—')}</p>
    </div>}
  </section>
}

function ModelRegistryPanel({
  registry,
  message,
  onPromote,
  onRollback,
}: {
  registry: RegistrySummary
  message: string
  onPromote: (candidateId: string) => void
  onRollback: (targetCandidateId?: string) => void
}) {
  return (
    <section className="card lab-panel" aria-label="Model registry">
      <span className="card-kicker">Immutable model registry</span>
      <h2>Production, Candidate & Archived Models</h2>
      <div className="lab-meta">
        <p>
          <strong>Active Production:</strong> {registry.production.active_candidate_id} (v
          {registry.production.active_version}) · SHA-256:{' '}
          <code>{registry.production.active_model_sha256?.slice(0, 16) || '—'}…</code>
        </p>
      </div>
      {message && <p className="lab-badge ok">{message}</p>}
      {registry.candidates.length > 0 && (
        <table className="lab-table">
          <thead>
            <tr>
              <th>Candidate ID</th>
              <th>Algorithm</th>
              <th>Stage</th>
              <th>Obs</th>
              <th>WF Acc</th>
              <th>WF Macro F1</th>
              <th>Unseen-Repo Acc</th>
              <th>Unseen-Repo Top-2</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {registry.candidates.map(cand => (
              <tr key={cand.candidate_id}>
                <td>{cand.candidate_id}</td>
                <td>{pretty(cand.algorithm)}</td>
                <td>{cand.stage.toUpperCase()}</td>
                <td>{cand.training_observations ?? '—'}</td>
                <td>{num(cand.primary_metrics?.accuracy)}</td>
                <td>{num(cand.primary_metrics?.macro_f1)}</td>
                <td>{num(cand.unseen_repository_metrics?.accuracy)}</td>
                <td>{num(cand.unseen_repository_metrics?.top_2_accuracy)}</td>
                <td>
                  {cand.stage !== 'production' ? (
                    <button
                      type="button"
                      className="button secondary"
                      onClick={() => onPromote(cand.candidate_id)}
                    >
                      Promote
                    </button>
                  ) : (
                    <span>Active</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {registry.production.active_candidate_id !== 'model_v1.0_original' && (
        <div style={{ marginTop: '0.75rem' }}>
          <button
            type="button"
            className="button secondary"
            onClick={() => onRollback('model_v1.0_original')}
          >
            Rollback to Original v1.0 Model
          </button>
        </div>
      )}
    </section>
  )
}

function LeakagePanel({ status }: { status: ResearchStatus }) {
  const leakage = status.leakage
  return <section className="card lab-panel" aria-label="Leakage status">
    <span className="card-kicker">Leakage status</span>
    <h2>Automated data-leakage checks</h2>
    <p className={`lab-badge ${leakage.passed ? 'ok' : 'fail'}`} data-testid="leakage-status">{leakage.passed ? 'PASSED' : 'FAILED'}</p>
    <ul className="lab-checks">
      {leakage.checks.map(check => <li key={check.name} className={check.status}>
        <strong>{pretty(check.name)}</strong>
        <b>{check.status}</b>
        <small>{check.detail}</small>
      </li>)}
    </ul>
    {leakage.errors.length > 0 && <div className="error" role="alert">{leakage.errors.length} critical leakage error(s) detected; evaluation is refused.</div>}
    {leakage.warnings.map(warning => <p className="muted" key={warning}>{warning}</p>)}
  </section>
}

function BaselinePanel({ evaluation }: { evaluation: ResearchEvaluationResponse }) {
  const results = evaluation.evaluation.results
  return <section className="card lab-panel" aria-label="Baseline comparison">
    <span className="card-kicker">Baseline comparison</span>
    <h2>Walk-forward model comparison</h2>
    <p className={`lab-badge ${evaluation.evaluation.status.startsWith('VALID') ? 'ok' : 'warn'}`}>{evaluation.evaluation.status}</p>
    <table className="lab-table">
      <thead><tr><th>Model</th><th title="Proportion of next-failure predictions matching empirical outcomes.">Accuracy ⓘ</th><th title="Unweighted average of F1 across all failure categories, penalizing majority class bias.">Macro F1 ⓘ</th><th title="Empirical accuracy when counting true outcome within top 3 predicted categories.">Top-3 ⓘ</th></tr></thead>
      <tbody>
        {BASELINE_ORDER.map(name => {
          const row = results.find(result => result.model === name)
          const metrics = row?.metrics ?? null
          return <tr key={name}>
            <th>{BASELINE_LABELS[name]}</th>
            <td>{num(metrics?.accuracy)}</td>
            <td>{num(metrics?.macro_f1)}</td>
            <td>{num(metrics?.top_3_accuracy)}</td>
          </tr>
        })}
      </tbody>
    </table>
    {!results.length && <p className="muted">No evaluation has been run: an em dash means no measurement exists, not a score of zero.</p>}
  </section>
}

function WalkForwardPanel({ evaluation }: { evaluation: ResearchEvaluationResponse }) {
  const walk = evaluation.evaluation.walk_forward
  return <section className="card lab-panel" aria-label="Walk-forward results">
    <span className="card-kicker">Temporal evaluation</span>
    <h2>Walk-forward cutoffs</h2>
    <p className={`lab-badge ${walk.status === 'COMPLETED' ? 'ok' : 'warn'}`}>{walk.status}</p>
    <p className="muted">{walk.message}</p>
    {walk.cutoffs.length > 0 && <table className="lab-table">
      <thead><tr><th title="Sequential chronological partition boundary.">Cutoff ⓘ</th><th title="Number of historical observations before cutoff used for training.">Train size ⓘ</th><th title="Number of test observations evaluated.">Test size ⓘ</th><th>Train time range</th><th>Test time range</th><th title="Macro F1 on test window.">Macro F1 ⓘ</th></tr></thead>
      <tbody>
        {walk.cutoffs.map(cutoff => <tr key={cutoff.cutoff}>
          <td>{cutoff.cutoff}</td>
          <td>{cutoff.train_size}</td>
          <td>{cutoff.test_size}</td>
          <td className="lab-small">{cutoff.train_time_range.start} → {cutoff.train_time_range.end}</td>
          <td className="lab-small">{cutoff.test_time_range.start} → {cutoff.test_time_range.end}</td>
          <td>{num(cutoff.metrics?.macro_f1)}</td>
        </tr>)}
      </tbody>
    </table>}
  </section>
}

function AblationPanel({ evaluation }: { evaluation: ResearchEvaluationResponse }) {
  const ablation = evaluation.evaluation.ablation
  const rows: AblationRow[] = ablation.results
  return <section className="card lab-panel" aria-label="Ablation results">
    <span className="card-kicker">Ablation study</span>
    <h2>Sequential feature contribution</h2>
    {rows.length === 0
      ? <p className="muted">{ablation.status || 'Ablation evaluation unavailable: insufficient chronological observations.'}</p>
      : <>
        <p className="muted">{ablation.message}</p>
        <table className="lab-table">
          <thead><tr><th>Variant</th><th>Removed</th><th title="Macro F1 without this feature group.">Macro F1 ⓘ</th><th title="Change in Macro F1 when this feature group is removed.">Δ vs full ⓘ</th></tr></thead>
          <tbody>
            {rows.map(row => <tr key={row.variant}>
              <td>{row.variant}</td>
              <td>{row.removed || '—'}</td>
              <td>{num(row.metrics.macro_f1)}</td>
              <td>{row.delta_macro_f1 === null ? '—' : `${row.delta_macro_f1 >= 0 ? '+' : ''}${row.delta_macro_f1.toFixed(4)}`}</td>
            </tr>)}
          </tbody>
        </table>
      </>}
  </section>
}

function CalibrationPanel({ evaluation }: { evaluation: ResearchEvaluationResponse }) {
  const calibration = evaluation.evaluation.calibration
  return <section className="card lab-panel" aria-label="Calibration">
    <span className="card-kicker">Calibration</span>
    <h2>Probability reliability</h2>
    {!calibration.available
      ? <p className="muted">Calibration metrics are not reported. Reason: {calibration.reason}</p>
      : <>
        <p className="muted">{calibration.methodology}</p>
        <div className="lab-stat-grid">
          <div><span>Samples</span><strong>{calibration.sample_count}</strong></div>
          <div title="Mean squared difference between predicted probabilities and actual one-hot outcomes (0 is perfect)."><span>Brier score ⓘ</span><strong>{calibration.brier_score?.toFixed(4)}</strong></div>
          <div title="Expected Calibration Error: weighted difference between confidence and empirical accuracy."><span>ECE ⓘ</span><strong>{calibration.expected_calibration_error?.toFixed(4)}</strong></div>
        </div>
        <table className="lab-table">
          <thead><tr><th>Bin</th><th>Count</th><th>Mean predicted</th><th>Empirical accuracy</th></tr></thead>
          <tbody>
            {(calibration.reliability_bins || []).map(bin => <tr key={`${bin.lower}-${bin.upper}`}>
              <td>{bin.lower}–{bin.upper}</td>
              <td>{bin.count}</td>
              <td>{bin.mean_predicted_confidence === null ? '—' : bin.mean_predicted_confidence.toFixed(4)}</td>
              <td>{bin.empirical_accuracy === null ? '—' : bin.empirical_accuracy.toFixed(4)}</td>
            </tr>)}
          </tbody>
        </table>
      </>}
  </section>
}

function PredictionPanel({ projects, projectId, setProjectId, prediction, busy, error, predict }: { projects: Array<{ id: number; name: string }>; projectId: string; setProjectId: (value: string) => void; prediction: ResearchPrediction | null; busy: boolean; error: string; predict: () => void }) {
  return <section className="card lab-panel prediction-panel" aria-label="Apex-APR prediction">
    <span className="card-kicker">Artifact-backed prediction</span><h2>Predict the next failure category</h2>
    <p className="muted">Predictions are available only when a validated model artifact exists. They are historical risk estimates, not certainties.</p>
    <div className="prediction-controls"><select aria-label="Project" value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">Select a persisted project</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button className="button" disabled={!projectId || busy} onClick={predict}>{busy ? 'Loading prediction…' : 'Predict'}</button></div>
    {error && <div className="error" role="alert">{error}</div>}
    {!prediction && !busy && <p className="lab-empty">Select a project to inspect the saved model prediction.</p>}
    {prediction && !prediction.available && <div className="lab-unavailable"><strong>Prediction unavailable</strong><p>{prediction.message || prediction.reason || 'Insufficient historical data.'}</p></div>}
    {prediction?.available && <div className="prediction-result"><div className="prediction-primary"><span>Most likely next category</span><strong>{pretty(prediction.predicted_category || 'Unavailable')}</strong></div><div className="prediction-list">{(prediction.predictions || []).slice(0, 3).map(item => <div className="prediction-item" key={item.category}><strong>{pretty(item.category)}</strong><b>{(item.probability * 100).toFixed(1)}%</b><div className="prediction-bar"><i style={{ width: `${item.probability * 100}%` }} /></div></div>)}</div>{prediction.supporting_features && <details><summary>Supporting features</summary><ul>{prediction.supporting_features.slice(0, 8).map(feature => <li key={feature.feature}>{pretty(feature.feature)}: {feature.value.toFixed(4)} ({feature.direction})</li>)}</ul></details>}<div className="lab-meta">{prediction.model && <p>Model: {String(prediction.model.name || prediction.model.model || 'Apex-APR')}</p>}{prediction.training_metadata && <p>Training observations: {String(prediction.training_metadata.training_observations || '—')}</p>}</div><p className="prediction-disclaimer">{prediction.disclaimer || PREDICTION_DISCLAIMER}</p></div>}
  </section>
}
