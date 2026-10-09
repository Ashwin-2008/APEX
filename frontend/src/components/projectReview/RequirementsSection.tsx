import { useEffect, useState } from 'react'
import { getRequirements } from '../../services/projectReviewApi'
import type { RequirementReport } from '../../types/projectReview'
import { CheckCircleIcon, AlertCircleIcon, ShieldIcon } from '../ui/Icons'

const STATUS_LABELS: Record<string, string> = {
  COVERED: 'Covered',
  PARTIALLY_COVERED: 'Partially covered',
  UNKNOWN: 'Unknown',
}

const STATUS_ORDER = ['COVERED', 'PARTIALLY_COVERED', 'UNKNOWN']

function statusOf(entry: RequirementReport['requirements'][number]): string {
  return String(entry.coverage?.status || 'UNKNOWN').toUpperCase()
}

function statusLabelFor(status: string): string {
  if (STATUS_LABELS[status]) return STATUS_LABELS[status]
  return status.replace(/_/g, ' ').toLowerCase().replace(/^(.)/, match => match.toUpperCase())
}

export function RequirementsSection({
  projectId,
  refreshToken,
}: {
  projectId: number
  refreshToken: number
}) {
  const [report, setReport] = useState<RequirementReport>()
  const [failed, setFailed] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getRequirements(projectId)
      .then(result => {
        if (!cancelled) {
          setReport(result)
          setFailed('')
        }
      })
      .catch(error => {
        if (!cancelled)
          setFailed(error instanceof Error ? error.message : 'Requirements could not be loaded.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshToken])

  const requirements = report?.requirements ?? []
  const presentStatuses = new Set(requirements.map(statusOf))
  const buckets = [...new Set([...STATUS_ORDER, ...presentStatuses])].map(status => ({
    status,
    label: statusLabelFor(status),
    count: requirements.filter(entry => statusOf(entry) === status).length,
  }))
  const uncovered = requirements.filter(entry => statusOf(entry) !== 'COVERED')

  return (
    <section className="card pr-section pr-requirements-section" aria-label="Requirements">
      <div className="pr-section-header-row">
        <div>
          <h2>REQUIREMENTS</h2>
          <p className="pr-section-note">
            Requirement coverage reported by the requirements analyzer
          </p>
        </div>
        <div className="pr-req-badge">
          <ShieldIcon size={12} className="inline mr-1 text-primary" />
          <span>Deterministic Specification Trace</span>
        </div>
      </div>

      {failed && <p className="pr-error" role="alert">{failed}</p>}
      {!failed && loading && !report && (
        <div className="pr-loading-state">
          <span className="loading-dot" aria-hidden="true" />
          <p className="pr-empty">Loading requirement coverage…</p>
        </div>
      )}
      {!failed && report && requirements.length === 0 && (
        <p className="pr-empty">
          {report.message || 'No structured requirements were detected.'}
        </p>
      )}

      {requirements.length > 0 && (
        <>
          <div className="pr-req-summary-card">
            <ul className="pr-req-counts" aria-label="Coverage counts">
              {buckets.map(bucket => {
                const s = bucket.status.toLowerCase()
                return (
                  <li key={bucket.status} className={`pr-req-count pr-req-${s}`}>
                    <div className="req-count-header">
                      <span className="req-count-dot" />
                      <span>{bucket.label}</span>
                    </div>
                    <strong>{bucket.count}</strong>
                  </li>
                )
              })}
            </ul>
          </div>

          <ul className="pr-req-list">
            {uncovered.map(entry => {
              const st = statusOf(entry).toLowerCase()
              return (
                <li key={entry.requirement_key || entry.title} className="pr-req-card card">
                  <div className="pr-req-item-head">
                    <span className={`pr-req-status pr-req-${st}`}>
                      {statusLabelFor(statusOf(entry))}
                    </span>
                    <span className="pr-req-source-tag">Source: {entry.source || 'spec'}</span>
                  </div>

                  <h4 className="pr-req-title">{entry.title || entry.requirement_key}</h4>

                  <details className="pr-evidence">
                    <summary>View evidence</summary>
                    <div className="pr-evidence-box">
                      <p className="pr-evidence-text">
                        {entry.coverage?.evidence ||
                          'No coverage evidence text was stored for this requirement.'}
                      </p>
                      {entry.coverage?.implementation?.files?.length ? (
                        <p className="pr-evidence-meta">
                          Implementation: {entry.coverage.implementation.files.join(', ')}
                        </p>
                      ) : null}
                      {entry.coverage?.tests?.files?.length ? (
                        <p className="pr-evidence-meta">
                          Tests: {entry.coverage.tests.files.join(', ')}
                        </p>
                      ) : null}
                    </div>
                  </details>
                </li>
              )
            })}
          </ul>

          {uncovered.length === 0 && (
            <div className="pr-req-all-covered card">
              <CheckCircleIcon size={20} className="text-success inline mb-2" />
              <p className="pr-empty">All detected requirements are covered.</p>
              <small className="text-muted">Test suites and source implementations verify all declared specifications.</small>
            </div>
          )}
        </>
      )}
    </section>
  )
}