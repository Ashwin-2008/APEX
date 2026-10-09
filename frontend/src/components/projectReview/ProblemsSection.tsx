import { useState } from 'react'
import {
  categoryNoun,
  categoryTitle,
  severityLabel,
  severitySymbol,
  statusLabel,
  whyItMatters,
} from '../../utils/labels'
import { findingDisplayKey, type DedupableFinding } from '../../utils/findingDedup'
import type { FailureHistoryRow } from '../../types/projectReview'
import { FindingLocation } from './FindingLocation'
import { FilterIcon, ShieldIcon } from '../ui/Icons'

function formatWhen(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export interface ProblemCardProps {
  finding: DedupableFinding
  history?: FailureHistoryRow
}

export function ProblemCard({ finding, history }: ProblemCardProps) {
  const status = statusLabel(finding.status)
  const firstDetected = formatWhen(history?.first_seen)
  const seenBefore = history && history.occurrences > 1
  const sevKey = String(finding.severity || 'medium').toLowerCase()

  return (
    <article className={`pr-problem card pr-problem-card sev-border-${sevKey}`} aria-label={categoryTitle(finding)}>
      <div className="pr-problem-head">
        <div className="pr-problem-badges">
          <span className={`pr-sev pr-sev-${sevKey}`}>
            <span aria-hidden="true" className="sev-dot-icon">{severitySymbol(finding.severity)}</span>{' '}
            {severityLabel(finding.severity)}
          </span>
          <span className={`live-badge live-${status.toLowerCase()}`}>{status}</span>
        </div>
        <span className="pr-problem-cat-tag">{categoryNoun(finding.category)}</span>
      </div>

      <h3 className="pr-problem-title">{categoryTitle(finding)}</h3>

      <div className="pr-problem-loc-box">
        <FindingLocation finding={finding} showHeading />
      </div>

      <dl className="pr-problem-body">
        <div className="pr-dl-item">
          <dt>Why this matters</dt>
          <dd>{whyItMatters(finding)}</dd>
        </div>

        {finding.remediation && (
          <div className="pr-dl-item pr-dl-remediation">
            <dt>What to do</dt>
            <dd>{finding.remediation}</dd>
          </div>
        )}

        {firstDetected && (
          <div className="pr-dl-item">
            <dt>First detected</dt>
            <dd>{firstDetected}</dd>
          </div>
        )}

        {history && (
          <div className="pr-dl-item">
            <dt>Seen before</dt>
            <dd>
              {seenBefore
                ? `Seen in ${history.occurrences} reviews (reviews ${history.review_numbers.join(', ')})`
                : 'First appearance in the recorded history'}
            </dd>
          </div>
        )}

        <div className="pr-dl-item pr-dl-source">
          <dt>Source analyzer</dt>
          <dd><code>{finding.analyzer_source}</code></dd>
        </div>
      </dl>

      <details className="pr-evidence">
        <summary>View evidence</summary>
        <div className="pr-evidence-box">
          <p className="pr-evidence-text">
            {finding.evidence || 'No additional evidence text was stored for this issue.'}
          </p>
          <p className="pr-evidence-meta">
            Category: {categoryNoun(finding.category)} · Confidence:{' '}
            {Math.round((finding.confidence ?? 0) * 100)}%
          </p>
        </div>
      </details>
    </article>
  )
}

export function ProblemsSection({
  findings,
  historyIndex,
}: {
  findings: DedupableFinding[]
  historyIndex: Map<string, FailureHistoryRow>
}) {
  const [filter, setFilter] = useState<string>('all')

  const filterTabs = [
    { id: 'all', label: 'All' },
    { id: 'critical', label: 'Critical' },
    { id: 'high', label: 'High' },
    { id: 'medium', label: 'Medium' },
    { id: 'low', label: 'Low' },
    { id: 'security', label: 'Security' },
    { id: 'testing', label: 'Testing' },
    { id: 'architecture', label: 'Architecture' },
  ]

  const filteredFindings = findings.filter(f => {
    if (filter === 'all') return true
    const sev = String(f.severity || '').toLowerCase()
    const cat = String(f.category || '').toLowerCase()
    if (['critical', 'high', 'medium', 'low'].includes(filter)) {
      return sev === filter
    }
    return cat === filter
  })

  return (
    <section className="card pr-section" aria-label="Problems to fix">
      <div className="pr-section-header-row">
        <div>
          <h2>PROBLEMS TO FIX</h2>
          <p className="pr-section-note">
            {findings.length
              ? `${findings.length} issue${findings.length === 1 ? '' : 's'} reported by the analyzers`
              : 'No issues reported by the analyzers'}
          </p>
        </div>
        <div className="pr-filter-badge">
          <FilterIcon size={12} className="inline mr-1 text-muted" />
          <span>Active filter: <strong className="capitalize">{filter}</strong></span>
        </div>
      </div>

      {findings.length > 0 && (
        <div className="pr-filters-bar" role="toolbar" aria-label="Filter problems">
          {filterTabs.map(tab => {
            const count =
              tab.id === 'all'
                ? findings.length
                : ['critical', 'high', 'medium', 'low'].includes(tab.id)
                ? findings.filter(f => String(f.severity || '').toLowerCase() === tab.id).length
                : findings.filter(f => String(f.category || '').toLowerCase() === tab.id).length
            return (
              <button
                key={tab.id}
                type="button"
                className={`filter-chip ${filter === tab.id ? 'active' : ''}`}
                onClick={() => setFilter(tab.id)}
              >
                <span>{tab.label}</span>
                <span className="filter-count">{count}</span>
              </button>
            )
          })}
        </div>
      )}

      {filteredFindings.length ? (
        <div className="pr-problems">
          {filteredFindings.map(finding => (
            <ProblemCard
              key={findingDisplayKey(finding)}
              finding={finding}
              history={historyIndex.get(findingDisplayKey(finding))}
            />
          ))}
        </div>
      ) : findings.length > 0 ? (
        <div className="pr-empty-filter">
          <p>No issues match the selected filter “{filter}”.</p>
          <button type="button" className="button button-secondary" onClick={() => setFilter('all')}>
            Clear filter
          </button>
        </div>
      ) : (
        <p className="pr-empty">
          Good news — no engineering issues were detected by the current analyzers.
        </p>
      )}
    </section>
  )
}