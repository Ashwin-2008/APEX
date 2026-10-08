import { categoryNoun, categoryTitle, severityLabel, severitySymbol, statusLabel, whyItMatters } from '../../utils/labels'
import { findingDisplayKey, type DedupableFinding } from '../../utils/findingDedup'
import type { FailureHistoryRow } from '../../types/projectReview'
import { FindingLocation } from './FindingLocation'

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
  return (
    <article className="pr-problem" aria-label={categoryTitle(finding)}>
      <div className="pr-problem-head">
        <span className={`pr-sev pr-sev-${String(finding.severity || 'medium').toLowerCase()}`}>
          <span aria-hidden="true">{severitySymbol(finding.severity)}</span> {severityLabel(finding.severity)}
        </span>
        <span className={`live-badge live-${status.toLowerCase()}`}>{status}</span>
      </div>
      <h3>{categoryTitle(finding)}</h3>
      <FindingLocation finding={finding} showHeading />
      <dl className="pr-problem-body">
        <dt>Why this matters</dt>
        <dd>{whyItMatters(finding)}</dd>
        {finding.remediation && (<><dt>What to do</dt><dd>{finding.remediation}</dd></>)}
        {firstDetected && (<><dt>First detected</dt><dd>{firstDetected}</dd></>)}
        {history && (
          <>
            <dt>Seen before</dt>
            <dd>
              {seenBefore
                ? `Seen in ${history.occurrences} reviews (reviews ${history.review_numbers.join(', ')})`
                : 'First appearance in the recorded history'}
            </dd>
          </>
        )}
        <dt>Source analyzer</dt>
        <dd>{finding.analyzer_source}</dd>
      </dl>
      <details className="pr-evidence">
        <summary>View evidence</summary>
        <p className="pr-evidence-text">{finding.evidence || 'No additional evidence text was stored for this issue.'}</p>
        <p className="pr-evidence-meta">
          Category: {categoryNoun(finding.category)} · Confidence: {Math.round((finding.confidence ?? 0) * 100)}%
        </p>
      </details>
    </article>
  )
}

export function ProblemsSection({ findings, historyIndex }: { findings: DedupableFinding[]; historyIndex: Map<string, FailureHistoryRow> }) {
  return (
    <section className="card pr-section" aria-label="Problems to fix">
      <h2>PROBLEMS TO FIX</h2>
      <p className="pr-section-note">{findings.length ? `${findings.length} issue${findings.length === 1 ? '' : 's'} reported by the analyzers` : 'No issues reported by the analyzers'}</p>
      {findings.length ? (
        <div className="pr-problems">
          {findings.map(finding => (
            <ProblemCard key={findingDisplayKey(finding)} finding={finding} history={historyIndex.get(findingDisplayKey(finding))} />
          ))}
        </div>
      ) : (
        <p className="pr-empty">Good news — no engineering issues were detected by the current analyzers.</p>
      )}
    </section>
  )
}