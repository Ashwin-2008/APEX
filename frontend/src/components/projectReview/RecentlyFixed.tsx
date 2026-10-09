import { categoryTitle, severityLabel, severitySymbol } from '../../utils/labels'
import type { FailureHistoryRow } from '../../types/projectReview'
import type { LocationSource } from '../../utils/findingDedup'
import { FindingLocation } from './FindingLocation'
import { CheckCircleIcon, GitCommitIcon } from '../ui/Icons'

export interface ResolvedView {
  title: string
  location: LocationSource
  severity: string
  resolvedAt: string | null
  howResolved: string | null
  relatedCommit: string | null
  key: string
}

function formatTime(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export function resolvedFromHistory(rows: FailureHistoryRow[]): ResolvedView[] {
  return rows
    .filter(row => String(row.status || '').toUpperCase() === 'RESOLVED')
    .sort((a, b) => String(b.resolved_at || '').localeCompare(String(a.resolved_at || '')))
    .map(row => ({
      key: row.fingerprint || `${row.category}|${row.evidence}`,
      title: categoryTitle(row),
      location: row,
      severity: severityLabel(row.severity),
      resolvedAt: formatTime(row.resolved_at),
      howResolved: row.resolution_evidence,
      relatedCommit: row.related_commit,
    }))
}

export function RecentlyFixed({ items }: { items: ResolvedView[] }) {
  return (
    <section className="card pr-section" aria-label="Recently fixed">
      <div className="pr-section-header-row">
        <div>
          <h2>RECENTLY FIXED</h2>
          <p className="pr-section-note">
            {items.length
              ? `${items.length} issue${items.length === 1 ? '' : 's'} resolved in the recorded history`
              : 'No resolved issues yet'}
          </p>
        </div>
        <div className="resolved-summary-chip">
          <CheckCircleIcon size={13} className="text-success inline mr-1" />
          <span>{items.length} Resolved</span>
        </div>
      </div>

      {items.length ? (
        <ul className="pr-fixed">
          {items.map(item => (
            <li key={item.key} className="pr-fixed-card card">
              <div className="pr-fixed-head">
                <span className="pr-fixed-title">
                  <span aria-hidden="true" className="resolved-check-icon">✓</span>{' '}
                  <span aria-hidden="true" className="sev-dot">{severitySymbol(item.severity)}</span>{' '}
                  {item.title}
                </span>
                <span className="resolved-badge">✓ RESOLVED</span>
              </div>

              <div className="pr-fixed-location">
                <FindingLocation finding={item.location} />
              </div>

              <dl className="pr-fixed-meta">
                <div className="fixed-meta-item">
                  <dt>Severity</dt>
                  <dd><span className={`fixed-sev-pill sev-${item.severity.toLowerCase()}`}>{item.severity}</span></dd>
                </div>

                <div className="fixed-meta-item">
                  <dt>Resolved</dt>
                  <dd>{item.resolvedAt || 'Not recorded'}</dd>
                </div>

                <div className="fixed-meta-item fixed-meta-how">
                  <dt>How it was resolved</dt>
                  <dd>{item.howResolved || 'No resolution note was stored for this issue.'}</dd>
                </div>

                {item.relatedCommit && (
                  <div className="fixed-meta-item">
                    <dt>Related commit</dt>
                    <dd>
                      <GitCommitIcon size={12} className="inline mr-1 text-muted" />
                      <code>{item.relatedCommit.slice(0, 7)}</code>
                    </dd>
                  </div>
                )}
              </dl>
            </li>
          ))}
        </ul>
      ) : (
        <p className="pr-empty">
          No issues have been resolved in the recorded project history yet.
        </p>
      )}
    </section>
  )
}