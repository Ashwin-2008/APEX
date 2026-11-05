import React, { useState, useEffect } from 'react'
import {
  listRemediationWorkflows,
  triggerRootCauseInvestigation,
  fetchInvestigationDetails,
  fetchRemediationPlans,
  generateRemediationPlans,
  selectPreferredPlan,
  separateFindingFromCluster,
  compareRemediationPlans,
  RemediationHypothesis,
  FindingCluster,
  RemediationPlan,
  PlanComparisonMatrix,
  RemediationWorkflowSummary,
} from '../../api/remediationApi'

interface RemediationPlanningSectionProps {
  projectId: number
  refreshToken?: number
}

export const RemediationPlanningSection: React.FC<RemediationPlanningSectionProps> = ({
  projectId,
  refreshToken,
}) => {
  const [workflows, setWorkflows] = useState<RemediationWorkflowSummary[]>([])
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')
  const [hypotheses, setHypotheses] = useState<RemediationHypothesis[]>([])
  const [clusters, setClusters] = useState<FindingCluster[]>([])
  const [plans, setPlans] = useState<RemediationPlan[]>([])
  const [comparison, setComparison] = useState<PlanComparisonMatrix | null>(null)
  const [activePlanId, setActivePlanId] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Separation modal state
  const [separatingClusterId, setSeparatingClusterId] = useState<string | null>(null)
  const [separateFindingId, setSeparateFindingId] = useState<number | ''>('')
  const [separateReason, setSeparateReason] = useState<string>('')

  // Load workflows
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRemediationWorkflows(projectId)
      .then((items: RemediationWorkflowSummary[]) => {
        if (!cancelled) {
          setWorkflows(items)
          if (items.length > 0 && !selectedWorkflowId) {
            setSelectedWorkflowId(items[0].workflow_id)
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load workflows')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshToken, selectedWorkflowId])

  // Load workflow investigation & plans when selected
  useEffect(() => {
    if (!selectedWorkflowId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.allSettled([
      fetchInvestigationDetails(projectId, selectedWorkflowId),
      fetchRemediationPlans(projectId, selectedWorkflowId),
      compareRemediationPlans(projectId, selectedWorkflowId),
    ])
      .then(([invResult, plansResult, compResult]) => {
        if (cancelled) return
        if (invResult.status === 'fulfilled') {
          setHypotheses(invResult.value.hypotheses || [])
          setClusters(invResult.value.clusters || [])
        }
        if (plansResult.status === 'fulfilled') {
          const loadedPlans = plansResult.value || []
          setPlans(loadedPlans)
          const preferred = loadedPlans.find((p) => p.is_preferred)
          if (preferred) {
            setActivePlanId(preferred.plan_id)
          } else if (loadedPlans.length > 0) {
            setActivePlanId(loadedPlans[0].plan_id)
          }
        }
        if (compResult.status === 'fulfilled') {
          setComparison(compResult.value)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [projectId, selectedWorkflowId])

  const handleInvestigate = async () => {
    if (!selectedWorkflowId) return
    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      await triggerRootCauseInvestigation(projectId, selectedWorkflowId)
      setSuccessMsg('Investigation completed! Multi-source hypotheses synthesized.')
      const details = await fetchInvestigationDetails(projectId, selectedWorkflowId)
      setHypotheses(details.hypotheses || [])
      setClusters(details.clusters || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Investigation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleGeneratePlans = async () => {
    if (!selectedWorkflowId) return
    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const generated = await generateRemediationPlans(projectId, selectedWorkflowId)
      setPlans(generated)
      const preferred = generated.find((p) => p.is_preferred)
      if (preferred) setActivePlanId(preferred.plan_id)
      const comp = await compareRemediationPlans(projectId, selectedWorkflowId)
      setComparison(comp)
      setSuccessMsg('Remediation plans generated and scored across 11 dimensions!')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Plan generation failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSelectPlan = async (planId: string) => {
    if (!selectedWorkflowId) return
    setLoading(true)
    setError(null)
    try {
      await selectPreferredPlan(projectId, selectedWorkflowId, planId)
      setActivePlanId(planId)
      const updated = await fetchRemediationPlans(projectId, selectedWorkflowId)
      setPlans(updated)
      setSuccessMsg(`Plan ${planId} selected as preferred candidate!`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to select plan')
    } finally {
      setLoading(false)
    }
  }

  const handleSeparateFinding = async () => {
    if (!selectedWorkflowId || !separatingClusterId || !separateFindingId || !separateReason.trim()) return
    setLoading(true)
    try {
      await separateFindingFromCluster(
        projectId,
        selectedWorkflowId,
        separatingClusterId,
        Number(separateFindingId),
        separateReason.trim()
      )
      setSeparatingClusterId(null)
      setSeparateFindingId('')
      setSeparateReason('')
      setSuccessMsg('Finding separated into its own cluster!')
      const details = await fetchInvestigationDetails(projectId, selectedWorkflowId)
      setClusters(details.clusters || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to separate finding')
    } finally {
      setLoading(false)
    }
  }

  const currentPlan = plans.find((p) => p.plan_id === activePlanId) || plans[0]

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'CONFIRMED':
        return '#10b981'
      case 'STRONGLY_SUPPORTED':
        return '#3b82f6'
      case 'INFERRED':
        return '#f59e0b'
      case 'INSUFFICIENT_EVIDENCE':
        return '#8b5cf6'
      case 'REJECTED':
        return '#ef4444'
      default:
        return '#6b7280'
    }
  }

  return (
    <div className="remediation-planning-section card" style={{ padding: '24px', margin: '16px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0 }}>
            Root Cause Investigation & Multi-Strategy Planning (Phase 5.2)
          </h2>
          <p style={{ color: '#6b7280', fontSize: '0.9rem', marginTop: '4px' }}>
            Evidence-driven causal synthesis, 11-dimension strategy ranking, and safe candidate proposals.
          </p>
        </div>

        {/* Workflow Switcher */}
        {workflows.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <label htmlFor="wf-select" style={{ fontSize: '0.85rem', fontWeight: 600 }}>Workflow:</label>
            <select
              id="wf-select"
              value={selectedWorkflowId}
              onChange={(e) => setSelectedWorkflowId(e.target.value)}
              style={{ padding: '6px 12px', borderRadius: '6px', border: '1px solid #d1d5db', background: '#fff' }}
            >
              {workflows.map((w) => (
                <option key={w.workflow_id} value={w.workflow_id}>
                  {w.workflow_id.slice(0, 16)}... ({w.state})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {error && (
        <div style={{ background: '#fef2f2', border: '1px solid #f87171', color: '#b91c1c', padding: '12px', borderRadius: '8px', marginBottom: '16px' }}>
          {error}
        </div>
      )}

      {successMsg && (
        <div style={{ background: '#ecfdf5', border: '1px solid #34d399', color: '#065f46', padding: '12px', borderRadius: '8px', marginBottom: '16px' }}>
          {successMsg}
        </div>
      )}

      {/* Action Toolbar */}
      <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
        <button
          type="button"
          onClick={handleInvestigate}
          disabled={loading || !selectedWorkflowId}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            background: '#2563eb',
            color: '#fff',
            border: 'none',
            fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Analyzing Evidence...' : '1. Investigate Root Causes (12 Sources)'}
        </button>

        <button
          type="button"
          onClick={handleGeneratePlans}
          disabled={loading || !selectedWorkflowId}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            background: '#059669',
            color: '#fff',
            border: 'none',
            fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Synthesizing...' : '2. Synthesize Multi-Strategy Plans'}
        </button>
      </div>

      {/* SECTION A: HYPOTHESES */}
      <div style={{ marginBottom: '28px' }}>
        <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '12px', borderBottom: '2px solid #e5e7eb', paddingBottom: '6px' }}>
          Root Cause Hypotheses ({hypotheses.length})
        </h3>
        {hypotheses.length === 0 ? (
          <p style={{ color: '#9ca3af', fontStyle: 'italic' }}>No hypotheses formulated yet. Click "Investigate Root Causes" above.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
            {hypotheses.map((h) => (
              <div
                key={h.hypothesis_id}
                style={{
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  padding: '16px',
                  background: '#fafafa',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 700,
                      color: '#fff',
                      background: getStatusColor(h.status),
                    }}
                  >
                    {h.status}
                  </span>
                  <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                    Confidence: {Math.round(h.confidence_score * 100)}%
                  </span>
                </div>
                <h4 style={{ margin: '0 0 6px 0', fontSize: '1rem', fontWeight: 600 }}>{h.title}</h4>
                <p style={{ fontSize: '0.85rem', color: '#4b5563', marginBottom: '10px' }}>{h.explanation}</p>
                <div style={{ fontSize: '0.8rem', color: '#374151', marginBottom: '8px' }}>
                  <strong>Category:</strong> {h.category} | <strong>Completeness:</strong> {Math.round(h.evidence_completeness_score * 100)}%
                </div>
                <div style={{ fontSize: '0.8rem', color: '#6b7280' }}>
                  <strong>Affected Files:</strong> {h.affected_files.join(', ') || 'N/A'}
                </div>
                {h.supporting_evidence.length > 0 && (
                  <div style={{ marginTop: '8px', borderTop: '1px solid #e5e7eb', paddingTop: '6px' }}>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#047857' }}>
                      Supporting Evidence ({h.supporting_evidence.length}):
                    </span>
                    <ul style={{ margin: '4px 0 0 16px', padding: 0, fontSize: '0.75rem', color: '#4b5563' }}>
                      {h.supporting_evidence.slice(0, 3).map((ev, i) => (
                        <li key={i}>[{ev.source_type}] {ev.summary}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SECTION B: FINDING CORRELATION CLUSTERS */}
      <div style={{ marginBottom: '28px' }}>
        <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '12px', borderBottom: '2px solid #e5e7eb', paddingBottom: '6px' }}>
          Cross-Finding Correlation Clusters ({clusters.length})
        </h3>
        {clusters.length === 0 ? (
          <p style={{ color: '#9ca3af', fontStyle: 'italic' }}>No finding clusters identified yet.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
            {clusters.map((c) => (
              <div
                key={c.cluster_id}
                style={{
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  padding: '16px',
                  background: '#f9fafb',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>{c.cluster_name}</h4>
                  {c.is_manually_adjusted && (
                    <span style={{ fontSize: '0.7rem', background: '#dbeafe', color: '#1d4ed8', padding: '2px 6px', borderRadius: '4px' }}>
                      Manually Adjusted
                    </span>
                  )}
                </div>
                <div style={{ fontSize: '0.8rem', color: '#6b7280', marginBottom: '6px' }}>
                  Category: <strong>{c.thematic_category}</strong> | Primary Finding: #{c.primary_finding_id}
                </div>
                <p style={{ fontSize: '0.85rem', color: '#4b5563', marginBottom: '10px' }}>
                  {c.correlation_rationale}
                </p>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: '#374151' }}>
                    Linked Findings: {c.finding_ids.map((id) => `#${id}`).join(', ')}
                  </span>
                  {c.finding_ids.length > 1 && (
                    <button
                      type="button"
                      onClick={() => {
                        setSeparatingClusterId(c.cluster_id)
                        setSeparateFindingId(c.finding_ids[1])
                      }}
                      style={{
                        padding: '4px 8px',
                        fontSize: '0.75rem',
                        borderRadius: '4px',
                        background: '#f3f4f6',
                        border: '1px solid #d1d5db',
                        cursor: 'pointer',
                      }}
                    >
                      Split Finding
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SEPARATION MODAL */}
      {separatingClusterId && (
        <div style={{ background: '#f8fafc', border: '1px solid #94a3b8', borderRadius: '8px', padding: '16px', marginBottom: '24px' }}>
          <h4 style={{ margin: '0 0 10px 0', fontSize: '0.95rem', fontWeight: 600 }}>Separate Finding from Cluster</h4>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '10px' }}>
            <label style={{ fontSize: '0.85rem' }}>Finding ID: #{separateFindingId}</label>
            <input
              type="text"
              placeholder="Reason for manual separation..."
              value={separateReason}
              onChange={(e) => setSeparateReason(e.target.value)}
              style={{ flex: 1, padding: '6px 10px', borderRadius: '4px', border: '1px solid #cbd5e1' }}
            />
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={handleSeparateFinding}
              disabled={!separateReason.trim()}
              style={{ padding: '6px 12px', background: '#dc2626', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
            >
              Confirm Separation
            </button>
            <button
              type="button"
              onClick={() => setSeparatingClusterId(null)}
              style={{ padding: '6px 12px', background: '#e2e8f0', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* SECTION C: MULTI-STRATEGY REMEDIATION PLANS & 11-DIMENSION RANKING */}
      <div style={{ marginBottom: '28px' }}>
        <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '12px', borderBottom: '2px solid #e5e7eb', paddingBottom: '6px' }}>
          Alternative Remediation Plans & 11-Dimension Scoring ({plans.length})
        </h3>

        {plans.length === 0 ? (
          <p style={{ color: '#9ca3af', fontStyle: 'italic' }}>No plans generated yet. Click "Synthesize Multi-Strategy Plans" above.</p>
        ) : (
          <div>
            {/* Plan selector tabs */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
              {plans.map((p) => (
                <button
                  key={p.plan_id}
                  type="button"
                  onClick={() => setActivePlanId(p.plan_id)}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '6px',
                    border: activePlanId === p.plan_id ? '2px solid #2563eb' : '1px solid #d1d5db',
                    background: activePlanId === p.plan_id ? '#eff6ff' : '#fff',
                    fontWeight: activePlanId === p.plan_id ? 700 : 500,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <span>{p.strategy_name}</span>
                  <span style={{ fontSize: '0.8rem', background: '#2563eb', color: '#fff', padding: '1px 6px', borderRadius: '10px' }}>
                    {p.plan_score}
                  </span>
                  {p.is_preferred && (
                    <span style={{ fontSize: '0.7rem', background: '#059669', color: '#fff', padding: '1px 6px', borderRadius: '4px' }}>
                      PREFERRED
                    </span>
                  )}
                  {p.abstain_reason && (
                    <span style={{ fontSize: '0.7rem', background: '#7c3aed', color: '#fff', padding: '1px 6px', borderRadius: '4px' }}>
                      ABSTAINED
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Active Plan Detail Card */}
            {currentPlan && (
              <div style={{ border: '1px solid #cbd5e1', borderRadius: '8px', padding: '20px', background: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <h4 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700 }}>
                      {currentPlan.strategy_name} — Score: {currentPlan.plan_score} / 100
                    </h4>
                    <p style={{ margin: '4px 0 0 0', color: '#6b7280', fontSize: '0.85rem' }}>
                      {currentPlan.strategy_description}
                    </p>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.8rem', padding: '4px 8px', borderRadius: '4px', background: '#f1f5f9', border: '1px solid #cbd5e1' }}>
                      Approval: <strong>{currentPlan.approval_tier_required}</strong>
                    </span>
                    <span style={{ fontSize: '0.8rem', padding: '4px 8px', borderRadius: '4px', background: '#f1f5f9', border: '1px solid #cbd5e1' }}>
                      Complexity: <strong>{currentPlan.estimated_complexity}</strong>
                    </span>
                    {!currentPlan.is_preferred && (
                      <button
                        type="button"
                        onClick={() => handleSelectPlan(currentPlan.plan_id)}
                        disabled={loading}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '6px',
                          background: '#2563eb',
                          color: '#fff',
                          border: 'none',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Set as Preferred
                      </button>
                    )}
                  </div>
                </div>

                {currentPlan.abstain_reason && (
                  <div style={{ background: '#f5f3ff', border: '1px solid #8b5cf6', color: '#5b21b6', padding: '10px 14px', borderRadius: '6px', marginBottom: '16px' }}>
                    <strong>ABSTENTION ADVISORY:</strong> {currentPlan.abstain_reason}
                  </div>
                )}

                {/* Ranking Explanation */}
                {currentPlan.ranking_explanation && (
                  <div style={{ background: '#f8fafc', padding: '10px 14px', borderRadius: '6px', fontSize: '0.85rem', color: '#334155', marginBottom: '16px' }}>
                    <strong>Ranking Explanation:</strong> {currentPlan.ranking_explanation}
                  </div>
                )}

                {/* 11-Dimension Breakdown Grid */}
                <div style={{ marginBottom: '20px' }}>
                  <h5 style={{ fontSize: '0.9rem', fontWeight: 600, margin: '0 0 10px 0' }}>11-Dimension Transparent Score Breakdown:</h5>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '8px' }}>
                    {Object.entries(currentPlan.score_breakdown || {}).map(([dim, val]) => (
                      <div key={dim} style={{ background: '#f9fafb', padding: '8px', borderRadius: '4px', border: '1px solid #e5e7eb' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: '2px' }}>
                          <span style={{ textTransform: 'capitalize' }}>{dim.replace(/_/g, ' ')}</span>
                          <strong>{Math.round(val * 100)}%</strong>
                        </div>
                        <div style={{ background: '#e5e7eb', height: '6px', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{ background: '#3b82f6', width: `${Math.round(val * 100)}%`, height: '100%' }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* CANDIDATE PATCH DIFF PREVIEW (SAFETY BOUNDARY) */}
                <div>
                  <h5 style={{ fontSize: '0.9rem', fontWeight: 600, margin: '0 0 8px 0' }}>Candidate Patch Representation:</h5>
                  <div
                    style={{
                      background: '#1e293b',
                      color: '#e2e8f0',
                      padding: '14px',
                      borderRadius: '6px',
                      fontFamily: 'Consolas, monospace',
                      fontSize: '0.8rem',
                      overflowX: 'auto',
                      whiteSpace: 'pre',
                      maxHeight: '300px',
                    }}
                  >
                    {currentPlan.risk_assessment?.candidate_patch_preview ||
                      `# UNVERIFIED — AWAITING PHASE 5.3 VALIDATION\n# Strategy: ${currentPlan.strategy_name}\n# Summary: ${currentPlan.proposed_changes_summary}`}
                  </div>
                  <p style={{ fontSize: '0.75rem', color: '#dc2626', fontWeight: 600, marginTop: '6px' }}>
                    * Strict Safety Guard: This patch candidate is UNVERIFIED and has NOT been executed or applied. Autonomous application is disabled.
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* SECTION D: PLAN COMPARISON MATRIX */}
      {comparison && comparison.comparison_matrix.length > 0 && (
        <div>
          <h3 style={{ fontSize: '1.15rem', fontWeight: 600, marginBottom: '12px', borderBottom: '2px solid #e5e7eb', paddingBottom: '6px' }}>
            Plan Comparison Matrix
          </h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0', textAlign: 'left' }}>
                  <th style={{ padding: '8px' }}>Strategy</th>
                  <th style={{ padding: '8px' }}>Score</th>
                  <th style={{ padding: '8px' }}>Blast Radius</th>
                  <th style={{ padding: '8px' }}>Complexity</th>
                  <th style={{ padding: '8px' }}>Approval Tier</th>
                  <th style={{ padding: '8px' }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {comparison.comparison_matrix.map((row) => (
                  <tr key={row.plan_id} style={{ borderBottom: '1px solid #f1f5f9', background: row.is_preferred ? '#f0fdf4' : '#fff' }}>
                    <td style={{ padding: '8px', fontWeight: 600 }}>{row.strategy_name}</td>
                    <td style={{ padding: '8px' }}>{row.score} / 100</td>
                    <td style={{ padding: '8px' }}>{row.blast_radius_score}</td>
                    <td style={{ padding: '8px' }}>{row.complexity}</td>
                    <td style={{ padding: '8px' }}>{row.approval_tier}</td>
                    <td style={{ padding: '8px' }}>
                      {row.is_preferred ? (
                        <span style={{ color: '#16a34a', fontWeight: 700 }}>PREFERRED</span>
                      ) : row.abstained ? (
                        <span style={{ color: '#7c3aed', fontWeight: 600 }}>ABSTAINED</span>
                      ) : (
                        <span style={{ color: '#64748b' }}>CANDIDATE</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
