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
import {
  generateFix,
  applyPatch,
  rollbackPatch,
  verifyBehavioral,
  type CodePatch,
  type PatchVerificationResult,
  type SemanticVerificationResult,
  type BehavioralVerificationResult,
  type PatchRecord,
} from '../../api/remediationApi'

function formatWhen(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export interface ProblemCardProps {
  finding: DedupableFinding
  history?: FailureHistoryRow
  projectId?: number | string
  onSuppress?: (finding: DedupableFinding) => void
}

export function ProblemCard({ finding, history, projectId, onSuppress }: ProblemCardProps) {
  const status = statusLabel(finding.status)
  const firstDetected = formatWhen(history?.first_seen)
  const seenBefore = history && history.occurrences > 1
  const sevKey = String(finding.severity || 'medium').toLowerCase()

  const [isFixGenerating, setIsFixGenerating] = useState(false)
  const [patchData, setPatchData] = useState<{
    patch: CodePatch
    verification: PatchVerificationResult
    provenance?: any
    semantic_verification?: SemanticVerificationResult
    record: PatchRecord
  } | null>(null)
  const [isApplying, setIsApplying] = useState(false)
  const [isRollingBack, setIsRollingBack] = useState(false)
  const [isBehavioralRunning, setIsBehavioralRunning] = useState(false)
  const [behavioralResult, setBehavioralResult] = useState<BehavioralVerificationResult | null>(null)
  const [showConfirmApply, setShowConfirmApply] = useState(false)
  const [showAuditTrail, setShowAuditTrail] = useState(false)
  const [patchState, setPatchState] = useState<string | null>(null)
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const handleGenerateFix = async () => {
    setIsFixGenerating(true)
    setFeedbackMsg(null)
    setBehavioralResult(null)
    setShowConfirmApply(false)
    try {
      const pId = projectId || 1
      const fId = String((finding as any).id || finding.fingerprint || finding.rule_id || 'issue')
      const res = await generateFix(pId, fId, finding)
      setPatchData(res)
      setPatchState(res.record.state)
      setFeedbackMsg({ type: 'success', text: 'Verified code patch synthesized with cryptographic provenance.' })
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err?.message || 'Failed to generate patch for this finding.' })
    } finally {
      setIsFixGenerating(false)
    }
  }

  const handleRunBehavioral = async () => {
    if (!patchData) return
    setIsBehavioralRunning(true)
    setFeedbackMsg(null)
    try {
      const pId = projectId || 1
      const res = await verifyBehavioral(pId, patchData.patch.patch_id)
      setBehavioralResult(res)
      setFeedbackMsg({
        type: res.valid ? 'success' : 'error',
        text: `Behavioral: ${res.summary}`,
      })
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err?.message || 'Behavioral test execution failed.' })
    } finally {
      setIsBehavioralRunning(false)
    }
  }

  const handleApplyPatch = async () => {
    if (!patchData) return
    setIsApplying(true)
    setShowConfirmApply(false)
    setFeedbackMsg(null)
    try {
      const pId = projectId || 1
      const res = await applyPatch(pId, patchData.patch.patch_id)
      if (res.success) {
        setPatchState('APPLIED')
        setFeedbackMsg({ type: 'success', text: 'Patch applied atomically with verified cryptographic backup.' })
      } else {
        setFeedbackMsg({ type: 'error', text: res.message || 'Patch application failed.' })
      }
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err?.message || 'Failed to apply patch.' })
    } finally {
      setIsApplying(false)
    }
  }

  const handleRollbackPatch = async () => {
    if (!patchData) return
    setIsRollingBack(true)
    setFeedbackMsg(null)
    try {
      const pId = projectId || 1
      const res = await rollbackPatch(pId, patchData.patch.patch_id)
      if (res.success) {
        setPatchState('ROLLED_BACK')
        setFeedbackMsg({ type: 'success', text: 'Patch rolled back cleanly to pre-modification state.' })
      } else {
        setFeedbackMsg({ type: 'error', text: res.message || 'Patch rollback failed.' })
      }
    } catch (err: any) {
      setFeedbackMsg({ type: 'error', text: err?.message || 'Failed to roll back patch.' })
    } finally {
      setIsRollingBack(false)
    }
  }

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
            {finding.metadata?.validation_state && (
              <span className="ml-2 font-semibold text-emerald-400">
                · Validation: {finding.metadata.validation_state}
              </span>
            )}
            {finding.metadata?.priority && (
              <span className="ml-2 font-semibold text-amber-400">
                · Priority: {finding.metadata.priority}
              </span>
            )}
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

      {finding.rule_id === 'TYPE-UNCHECKED-OPTIONAL-DEREFERENCE' && (
        <div className="mt-2 p-2 rounded bg-amber-950/40 border border-amber-800/60 text-xs text-amber-200 flex items-center gap-2">
          <span className="font-bold uppercase tracking-wider text-[10px] px-1.5 py-0.5 rounded bg-amber-900/80 text-amber-100">None-Safety Risk</span>
          <span>Unchecked dereference on Optional variable detected by PEP 484 type engine.</span>
        </div>
      )}

      {finding.rule_id === 'CONFIRMED-DEAD-CODE' && (
        <div className="mt-2 p-2 rounded bg-purple-950/40 border border-purple-800/60 text-xs text-purple-200 flex items-center gap-2">
          <span className="font-bold uppercase tracking-wider text-[10px] px-1.5 py-0.5 rounded bg-purple-900/80 text-purple-100">Dynamic Trace Verified</span>
          <span>Statically unreferenced symbol verified with 0 executions across test suite traces.</span>
        </div>
      )}

      {finding.rule_id === 'ASYNC-BLOCKING-IO-CALL' && (
        <div className="mt-2 p-2 rounded bg-rose-950/40 border border-rose-800/60 text-xs text-rose-200 flex items-center gap-2">
          <span className="font-bold uppercase tracking-wider text-[10px] px-1.5 py-0.5 rounded bg-rose-900/80 text-rose-100">Event Loop Starvation</span>
          <span>Synchronous blocking call in async coroutine blocks worker threads.</span>
        </div>
      )}

      {finding.evidence && finding.evidence.includes('[Correlated Test Failure]') && (
        <div className="mt-2 p-2 rounded bg-red-950/40 border border-red-800/60 text-xs text-red-200 flex items-center gap-2">
          <span className="font-bold uppercase tracking-wider text-[10px] px-1.5 py-0.5 rounded bg-red-900/80 text-red-100">Test Corroborated</span>
          <span>Failing test trace intersects with this code finding.</span>
        </div>
      )}

      {patchData && (
        <div className="mt-3 p-3 rounded bg-slate-950 border border-slate-800 text-xs font-mono">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800 flex-wrap gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-slate-200">{patchData.patch.summary}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                patchData.verification.valid ? 'bg-cyan-950 text-cyan-300 border border-cyan-800' : 'bg-red-950 text-red-300 border border-red-800'
              }`}>
                {patchData.verification.valid ? 'SYNTAX_VALID' : 'SYNTAX_ERROR'}
              </span>
              {patchData.semantic_verification && (
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                  patchData.semantic_verification.valid ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
                }`}>
                  {patchData.semantic_verification.valid ? 'SEMANTICALLY_VERIFIED' : patchData.semantic_verification.risk_level}
                </span>
              )}
              {behavioralResult && (
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                  behavioralResult.valid ? 'bg-sky-950 text-sky-300 border border-sky-800' : 'bg-rose-950 text-rose-300 border border-rose-800'
                }`}>
                  BEHAVIORAL_{behavioralResult.status}
                </span>
              )}
            </div>
            <span className="text-[10px] text-slate-400 font-sans">
              {patchData.patch.strategy}
            </span>
          </div>

          <p className="text-slate-300 font-sans text-xs mb-2">
            {patchData.patch.explanation}
          </p>

          <pre className="p-2 rounded bg-slate-900 overflow-x-auto text-[11px] leading-relaxed border border-slate-800 text-slate-200">
            {patchData.patch.unified_diff.split('\n').map((line, i) => {
              let color = 'text-slate-300'
              if (line.startsWith('+') && !line.startsWith('+++')) color = 'text-emerald-400 bg-emerald-950/30'
              else if (line.startsWith('-') && !line.startsWith('---')) color = 'text-rose-400 bg-rose-950/30'
              else if (line.startsWith('@@')) color = 'text-cyan-400'
              return <div key={i} className={color}>{line}</div>
            })}
          </pre>

          {showConfirmApply && (
            <div className="mt-2.5 p-2 rounded bg-amber-950/50 border border-amber-700 text-amber-200 text-xs">
              <p className="font-semibold mb-1">Confirm Disk Modification:</p>
              <p className="text-[11px] text-amber-300/90 mb-2">
                This operation will write the verified patch to disk. An atomic SHA-256 backup snapshot will be recorded in <code>.apex_backup/</code> before modification.
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={isApplying}
                  onClick={handleApplyPatch}
                  className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-sans text-xs font-semibold shadow disabled:opacity-50 cursor-pointer"
                >
                  {isApplying ? 'Applying...' : 'Confirm & Apply'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowConfirmApply(false)}
                  className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 font-sans text-xs cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {showAuditTrail && patchData.record?.audit_trail && (
            <div className="mt-2.5 p-2 rounded bg-slate-900 border border-slate-800 text-[11px]">
              <div className="font-semibold text-slate-300 mb-1">Patch Lifecycle Audit Trail:</div>
              <ul className="space-y-1 font-mono text-[10px] text-slate-400">
                {patchData.record.audit_trail.map((evt, idx) => (
                  <li key={idx} className="flex items-start gap-1.5">
                    <span className="text-slate-500">{new Date(evt.timestamp).toLocaleTimeString()}</span>
                    <span className="text-cyan-400">{evt.action}</span>
                    <span>[{evt.from_state} &rarr; {evt.to_state}]</span>
                    <span className="text-slate-400">({evt.details})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-2.5 flex items-center justify-between pt-2 border-t border-slate-800/80 flex-wrap gap-2">
            <div className="text-[11px] text-slate-400">
              Verification: {patchData.verification.details}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={isBehavioralRunning}
                onClick={handleRunBehavioral}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-300 font-sans text-xs border border-sky-800/60 cursor-pointer disabled:opacity-50"
                title="Execute isolated behavioral regression tests"
              >
                {isBehavioralRunning ? 'Testing...' : '🧪 Test Behavior'}
              </button>
              <button
                type="button"
                onClick={() => setShowAuditTrail(!showAuditTrail)}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 font-sans text-xs cursor-pointer"
                title="View patch lifecycle audit trail"
              >
                {showAuditTrail ? 'Hide History' : 'Timeline'}
              </button>
              {patchState !== 'APPLIED' ? (
                <button
                  type="button"
                  disabled={isApplying || !patchData.verification.valid || showConfirmApply}
                  onClick={() => setShowConfirmApply(true)}
                  className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-sans text-xs font-semibold shadow disabled:opacity-50 cursor-pointer"
                >
                  Apply Patch
                </button>
              ) : (
                <button
                  type="button"
                  disabled={isRollingBack}
                  onClick={handleRollbackPatch}
                  className="px-2.5 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white font-sans text-xs font-semibold shadow disabled:opacity-50 cursor-pointer"
                >
                  {isRollingBack ? 'Rolling back...' : 'Rollback Patch'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {feedbackMsg && (
        <div className={`mt-2 p-2 rounded text-xs ${feedbackMsg.type === 'success' ? 'bg-emerald-950/60 text-emerald-200 border border-emerald-800' : 'bg-red-950/60 text-red-200 border border-red-800'}`}>
          {feedbackMsg.text}
        </div>
      )}

      <div className="pr-card-actions" style={{ marginTop: '0.75rem', paddingTop: '0.5rem', borderTop: '1px solid var(--border-color, #334155)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          {!patchData ? (
            <button
              type="button"
              disabled={isFixGenerating}
              onClick={handleGenerateFix}
              className="button button-sm button-secondary"
              style={{ fontSize: '0.75rem', padding: '0.25rem 0.6rem' }}
              title="Synthesize and verify an automated code patch"
            >
              {isFixGenerating ? 'Generating Fix...' : '⚡ Generate Fix'}
            </button>
          ) : (
            <span className="text-[11px] text-emerald-400 font-medium">
              ✓ Patch Synthesized ({patchState})
            </span>
          )}
        </div>
        {onSuppress && (
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
        )}
      </div>
    </article>
  )
}

export function ProblemsSection({
  findings,
  historyIndex,
  projectId,
  onSuppress,
}: {
  findings: DedupableFinding[]
  historyIndex: Map<string, FailureHistoryRow>
  projectId?: number | string
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
              projectId={projectId}
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
