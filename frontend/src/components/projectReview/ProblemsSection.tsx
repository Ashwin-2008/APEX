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
import { ShieldIcon } from '../ui/Icons'

function formatWhen(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export interface ProblemCardProps {
  finding: DedupableFinding
  history?: FailureHistoryRow
  onSuppress?: (finding: DedupableFinding) => void
}

export function ProblemCard({ finding, history, onSuppress }: ProblemCardProps) {
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

      {finding.data_flow && finding.data_flow.length > 0 && (
        <details className="pr-evidence" style={{ marginTop: '0.5rem' }} open>
          <summary style={{ fontWeight: 600, color: '#38bdf8' }}>
            Taint Flow & Call Trace ({finding.data_flow.length} steps)
          </summary>
          <div className="pr-evidence-box" style={{ background: '#020617', border: '1px solid #1e293b' }}>
            <div className="space-y-1.5 text-xs font-mono">
              {finding.data_flow.map((step, idx) => (
                <div key={idx} className="flex items-start gap-2 p-1.5 rounded bg-slate-900/90 border border-slate-800">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                    step.role === 'source' ? 'bg-rose-900/80 text-rose-200' :
                    step.role === 'sink' ? 'bg-red-900/90 text-red-100 font-black' :
                    step.role === 'call' ? 'bg-sky-900/80 text-sky-200' :
                    step.role === 'parameter' ? 'bg-amber-900/80 text-amber-200' :
                    'bg-slate-800 text-slate-300'
                  }`}>
                    #{step.step} {step.role || 'step'}
                  </span>
                  <div className="flex-1 overflow-x-auto">
                    <div className="text-slate-400 font-sans text-[11px]">
                      {step.file ? `${step.file}${step.line ? `:${step.line}` : ''}` : step.module || ''}
                      {step.symbol ? ` · ${step.symbol}()` : ''}
                    </div>
                    {step.expression && (
                      <div className="text-emerald-400 text-[11px] mt-0.5 whitespace-pre-wrap">
                        {step.expression}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </details>
      )}

      {finding.metadata?.cycle && (
        <div className="mt-2 p-2 rounded bg-indigo-950/40 border border-indigo-800/60 text-xs">
          <div className="font-semibold text-indigo-300 mb-1">Circular Dependency Chain:</div>
          <div className="font-mono text-[11px] text-slate-300 flex flex-wrap items-center gap-1">
            {(finding.metadata.cycle as string[]).map((node, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700">{node}</span>
                {i < (finding.metadata?.cycle as string[]).length - 1 && <span className="text-indigo-400">→</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {finding.metadata?.complexity !== undefined && (
        <div className="mt-2 inline-flex items-center gap-2 px-2.5 py-1 rounded bg-slate-900 border border-slate-700 text-xs text-slate-300">
          <span className="text-slate-400">McCabe Complexity:</span>
          <span className="font-bold text-amber-400">{finding.metadata.complexity}</span>
          {finding.metadata.line_span && (
            <>
              <span className="text-slate-500">|</span>
              <span className="text-slate-400">Span:</span>
              <span className="font-semibold text-slate-200">{finding.metadata.line_span} lines</span>
            </>
          )}
        </div>
      )}

      {onSuppress && (
        <div className="pr-card-actions" style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--border-color, #334155)', display: 'flex', justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={() => onSuppress(finding)}
            className="button button-sm button-ghost"
            style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', color: '#94a3b8' }}
            title="Mark false positive or suppress with engineering justification"
          >
            <ShieldIcon size={12} className="inline mr-1" />
            Suppress / False Positive
          </button>
        </div>
      )}
    </article>
  )
}

export function ProblemsSection({
  findings,
  historyIndex,
  onSuppress,
}: {
  findings: DedupableFinding[]
  historyIndex: Map<string, FailureHistoryRow>
  onSuppress?: (finding: DedupableFinding) => void
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
            {findings.length === 0
              ? 'No active issues detected.'
              : `${findings.length} issue${findings.length === 1 ? '' : 's'} requiring engineer attention.`}
          </p>
        </div>
      </div>

      {findings.length > 0 && (
        <div className="filter-chips" role="tablist" aria-label="Filter issues by severity or category">
          {filterTabs.map(tab => {
            const count = findings.filter(f => {
              if (tab.id === 'all') return true
              const sev = String(f.severity || '').toLowerCase()
              const cat = String(f.category || '').toLowerCase()
              if (['critical', 'high', 'medium', 'low'].includes(tab.id)) {
                return sev === tab.id
              }
              return cat === tab.id
            }).length

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
              onSuppress={onSuppress}
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
