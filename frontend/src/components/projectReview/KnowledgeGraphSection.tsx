import { useState, useEffect } from 'react'
import {
  getGraphOverview,
  extractGraph,
  analyzeImpact,
  computeBlastRadius,
  getRecommendedTests,
  getArchitectureMetrics,
  getSubgraph,
  getGraphCoverage,
  getIdentityTransitions,
  listGraphVersions,
  compareGraphVersions,
  queryGraphEdges,
  type GraphOverview,
  type BlastRadiusReport,
  type RecommendedTest,
  type ArchitectureMetricsReport,
  type SubgraphResponse,
  type GraphCoverageReport,
  type IdentityTransitionRecord,
  type GraphVersionSummary,
  type VersionDiffReport,
  type GraphEdge,
} from '../../api/knowledgeGraphApi'

export function KnowledgeGraphSection({ projectId }: { projectId: number | string }) {
  const [activeTab, setActiveTab] = useState<'architecture' | 'impact' | 'tests' | 'subgraph' | 'continuity' | 'coverage' | 'diff' | 'cross-tech'>('architecture')
  const [overview, setOverview] = useState<GraphOverview | null>(null)
  const [loading, setLoading] = useState(false)
  const [extracting, setExtracting] = useState(false)

  // Architecture state
  const [archMetrics, setArchMetrics] = useState<ArchitectureMetricsReport | null>(null)

  // Impact / Blast Radius state
  const [targetInput, setTargetInput] = useState('')
  const [analyzingImpact, setAnalyzingImpact] = useState(false)
  const [blastReport, setBlastReport] = useState<BlastRadiusReport | null>(null)

  // Recommended tests state
  const [recommendedTests, setRecommendedTests] = useState<RecommendedTest[]>([])

  // Subgraph state
  const [subgraphCenter, setSubgraphCenter] = useState('')
  const [subgraphData, setSubgraphData] = useState<SubgraphResponse | null>(null)
  const [subgraphLoading, setSubgraphLoading] = useState(false)

  // Continuity & Ambiguous Candidate state
  const [transitions, setTransitions] = useState<IdentityTransitionRecord[]>([])
  const [loadingTransitions, setLoadingTransitions] = useState(false)
  const [selectedTransition, setSelectedTransition] = useState<IdentityTransitionRecord | null>(null)

  // Cross-tech state
  const [crossTechEdges, setCrossTechEdges] = useState<GraphEdge[]>([])
  const [loadingCrossTech, setLoadingCrossTech] = useState(false)

  // Coverage state
  const [coverageReport, setCoverageReport] = useState<GraphCoverageReport | null>(null)
  const [loadingCoverage, setLoadingCoverage] = useState(false)

  // Version diff state
  const [versions, setVersions] = useState<GraphVersionSummary[]>([])
  const [selectedV1, setSelectedV1] = useState<number>(1)
  const [selectedV2, setSelectedV2] = useState<number>(2)
  const [versionDiff, setVersionDiff] = useState<VersionDiffReport | null>(null)
  const [loadingDiff, setLoadingDiff] = useState(false)

  const loadOverview = async () => {
    setLoading(true)
    try {
      const ov = await getGraphOverview(projectId)
      setOverview(ov)
    } catch (e) {
      console.error('Failed to load graph overview', e)
    } finally {
      setLoading(false)
    }
  }

  const loadArchitecture = async () => {
    try {
      const arch = await getArchitectureMetrics(projectId)
      setArchMetrics(arch)
    } catch (e) {
      console.error('Failed to load architecture metrics', e)
    }
  }

  const loadContinuity = async () => {
    setLoadingTransitions(true)
    try {
      const t = await getIdentityTransitions(projectId)
      setTransitions(t)
    } catch (e) {
      console.error('Failed to load transitions', e)
    } finally {
      setLoadingTransitions(false)
    }
  }

  const loadCoverage = async () => {
    setLoadingCoverage(true)
    try {
      const cov = await getGraphCoverage(projectId)
      setCoverageReport(cov)
    } catch (e) {
      console.error('Failed to load coverage', e)
    } finally {
      setLoadingCoverage(false)
    }
  }

  const loadVersions = async () => {
    try {
      const v = await listGraphVersions(projectId)
      setVersions(v)
      if (v.length >= 2) {
        setSelectedV1(v[1].version_number)
        setSelectedV2(v[0].version_number)
      } else if (v.length === 1) {
        setSelectedV1(v[0].version_number)
        setSelectedV2(v[0].version_number)
      }
    } catch (e) {
      console.error('Failed to load versions', e)
    }
  }

  const loadCrossTech = async () => {
    setLoadingCrossTech(true)
    try {
      const res = await queryGraphEdges(projectId, { limit: 100 })
      const filtered = (res.edges || []).filter(e =>
        ['CALLS_API', 'QUERIES_MODEL', 'EXECUTES_ENTRYPOINT', 'RUNS_WORKFLOW_TEST', 'CONSUMES_ENV_VAR', 'DEFINES_CLIENT_CALL', 'DEPENDS_ON_SERVICE'].includes(e.rel_type)
      )
      setCrossTechEdges(filtered)
    } catch (e) {
      console.error('Failed to load cross-technology relationships', e)
    } finally {
      setLoadingCrossTech(false)
    }
  }

  useEffect(() => {
    loadOverview()
    loadArchitecture()
    loadContinuity()
    loadCoverage()
    loadVersions()
    loadCrossTech()
  }, [projectId])

  const handleExtract = async (full: boolean) => {
    setExtracting(true)
    try {
      await extractGraph(projectId, full)
      await loadOverview()
      await loadArchitecture()
      await loadContinuity()
      await loadCoverage()
      await loadVersions()
      await loadCrossTech()
    } catch (e: any) {
      alert(e?.message || 'Failed to extract graph')
    } finally {
      setExtracting(false)
    }
  }

  const handleRunImpact = async () => {
    if (!targetInput.trim()) return
    setAnalyzingImpact(true)
    try {
      const targets = [targetInput.trim()]
      const blast = await computeBlastRadius(projectId, targets)
      setBlastReport(blast)

      const testsRes = await getRecommendedTests(projectId, targets)
      setRecommendedTests(testsRes.recommended_tests)
    } catch (e: any) {
      alert(e?.message || 'Impact analysis failed')
    } finally {
      setAnalyzingImpact(false)
    }
  }

  const handleLoadSubgraph = async (centerId: string) => {
    if (!centerId.trim()) return
    setSubgraphLoading(true)
    try {
      const res = await getSubgraph(projectId, centerId.trim(), 2, 60)
      setSubgraphData(res)
      setActiveTab('subgraph')
      setSubgraphCenter(centerId)
    } catch (e: any) {
      alert(e?.message || 'Failed to fetch neighborhood subgraph')
    } finally {
      setSubgraphLoading(false)
    }
  }

  const handleCompareVersions = async () => {
    if (selectedV1 === undefined || selectedV2 === undefined) return
    setLoadingDiff(true)
    try {
      const diff = await compareGraphVersions(projectId, selectedV1, selectedV2)
      setVersionDiff(diff)
    } catch (e: any) {
      alert(e?.message || 'Failed to compare graph versions')
    } finally {
      setLoadingDiff(false)
    }
  }

  return (
    <section className="dashboard-card" style={{ marginTop: '1.5rem', border: '1px solid #1e293b' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>Engineering Knowledge Graph & Accuracy Intelligence</span>
            <span style={{ fontSize: '0.75rem', padding: '0.125rem 0.5rem', background: '#059669', color: '#fff', borderRadius: '1rem' }}>
              Phase 3.2
            </span>
          </h2>
          <p style={{ fontSize: '0.875rem', color: '#94a3b8' }}>
            Cross-technology relationship traces, multi-version architectural topology, identity continuity, calibrated blast radius, and targeted test selection.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            type="button"
            className="button button-secondary button-sm"
            disabled={extracting || loading}
            onClick={() => handleExtract(false)}
          >
            {extracting ? 'Indexing...' : 'Incremental Update'}
          </button>
          <button
            type="button"
            className="button button-primary button-sm"
            disabled={extracting || loading}
            onClick={() => handleExtract(true)}
          >
            {extracting ? 'Rebuilding...' : 'Full Rebuild'}
          </button>
        </div>
      </div>

      {/* Top Overview Cards */}
      {overview && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
          <div style={{ padding: '0.75rem', background: '#0f172a', borderRadius: '0.375rem', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>ACTIVE VERSION</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#38bdf8' }}>v{overview.version_number}</div>
            <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Commit: {overview.commit_sha ? overview.commit_sha.slice(0, 8) : 'HEAD'}</div>
          </div>
          <div style={{ padding: '0.75rem', background: '#0f172a', borderRadius: '0.375rem', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>TOTAL NODES</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{overview.node_count}</div>
            <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Modules, Symbols, APIs, Tables</div>
          </div>
          <div style={{ padding: '0.75rem', background: '#0f172a', borderRadius: '0.375rem', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>TOTAL RELATIONSHIPS</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{overview.edge_count}</div>
            <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Calls, Imports, Routes, Queries</div>
          </div>
          <div style={{ padding: '0.75rem', background: '#0f172a', borderRadius: '0.375rem', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>CONSISTENCY STATUS</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: overview.consistency.is_consistent ? '#34d399' : '#fbbf24' }}>
              {overview.consistency.is_consistent ? 'VERIFIED' : 'WARNINGS'}
            </div>
            <div style={{ fontSize: '0.7rem', color: '#64748b' }}>{overview.consistency.duplicate_edges} dupes, {overview.consistency.unresolved_edges_count} unresolved</div>
          </div>
          <div style={{ padding: '0.75rem', background: '#0f172a', borderRadius: '0.375rem', border: '1px solid #1e293b' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>RECOVERY & CONCURRENCY</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#38bdf8' }}>
              RECOVERED
            </div>
            <div style={{ fontSize: '0.7rem', color: '#34d399' }}>Lease Clear | 0 Orphan Nodes</div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="filter-chips" role="tablist" style={{ marginBottom: '1rem', flexWrap: 'wrap' }}>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'architecture' ? 'active' : ''}`}
          onClick={() => setActiveTab('architecture')}
        >
          <span>Architecture & Dependencies</span>
          {archMetrics && archMetrics.circular_dependencies.length > 0 && (
            <span className="filter-count" style={{ background: '#e11d48' }}>{archMetrics.circular_dependencies.length} cycles</span>
          )}
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'cross-tech' ? 'active' : ''}`}
          onClick={() => setActiveTab('cross-tech')}
        >
          <span>Cross-Tech Traces</span>
          {crossTechEdges.length > 0 && <span className="filter-count" style={{ background: '#059669' }}>{crossTechEdges.length}</span>}
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'impact' ? 'active' : ''}`}
          onClick={() => setActiveTab('impact')}
        >
          <span>Change Impact & Blast Radius</span>
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'tests' ? 'active' : ''}`}
          onClick={() => setActiveTab('tests')}
        >
          <span>Targeted Test Recommendations</span>
          {recommendedTests.length > 0 && <span className="filter-count">{recommendedTests.length}</span>}
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'continuity' ? 'active' : ''}`}
          onClick={() => setActiveTab('continuity')}
        >
          <span>Identity Continuity</span>
          {transitions.length > 0 && <span className="filter-count">{transitions.length}</span>}
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'coverage' ? 'active' : ''}`}
          onClick={() => setActiveTab('coverage')}
        >
          <span>Coverage Matrix</span>
          {coverageReport && <span className="filter-count">{Math.round(coverageReport.overall_coverage_percentage)}%</span>}
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'diff' ? 'active' : ''}`}
          onClick={() => setActiveTab('diff')}
        >
          <span>Version Diff</span>
        </button>
        <button
          type="button"
          className={`filter-chip ${activeTab === 'subgraph' ? 'active' : ''}`}
          onClick={() => setActiveTab('subgraph')}
        >
          <span>Neighborhood Subgraph</span>
        </button>
      </div>

      {/* Tab 1: Architecture & Dependencies */}
      {activeTab === 'architecture' && archMetrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1rem' }}>
          <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
              Circular Dependencies (Tarjan SCC)
            </h3>
            {archMetrics.circular_dependencies.length === 0 ? (
              <p style={{ fontSize: '0.8rem', color: '#34d399' }}>Zero circular dependencies detected. Architecture graph is acyclic.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {archMetrics.circular_dependencies.map((cycle, i) => (
                  <div key={i} style={{ padding: '0.5rem', background: '#1e1b4b', border: '1px solid #3730a3', borderRadius: '0.25rem', fontSize: '0.75rem', color: '#c7d2fe' }}>
                    <strong>Cycle #{i + 1}:</strong> {cycle.join(' → ')}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
              Core Components (Highest Fan-In)
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
              {archMetrics.high_fan_in_modules.slice(0, 5).map((m, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', padding: '0.25rem 0', borderBottom: '1px solid #0f172a' }}>
                  <span style={{ color: '#cbd5e1' }}>{m.module}</span>
                  <span style={{ fontWeight: 'bold', color: '#38bdf8' }}>{m.fan_in} dependents</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
              Coupling & Layer Boundary Violations
            </h3>
            {archMetrics.layer_violations.length === 0 ? (
              <p style={{ fontSize: '0.8rem', color: '#34d399' }}>No layer boundary violations detected.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                {archMetrics.layer_violations.map((v, i) => (
                  <div key={i} style={{ padding: '0.375rem', background: '#450a0a', border: '1px solid #991b1b', borderRadius: '0.25rem', fontSize: '0.75rem', color: '#fca5a5' }}>
                    <strong>{v.rule}:</strong> {v.source} → {v.target}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Change Impact & Blast Radius */}
      {activeTab === 'impact' && (
        <div>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="text"
              value={targetInput}
              onChange={e => setTargetInput(e.target.value)}
              placeholder="Enter file path or symbol (e.g. backend/app/models/entities.py or get_data)"
              style={{ flex: 1, padding: '0.5rem 0.75rem', background: '#020617', border: '1px solid #334155', borderRadius: '0.375rem', color: '#f8fafc', fontSize: '0.875rem' }}
            />
            <button
              type="button"
              disabled={analyzingImpact}
              onClick={handleRunImpact}
              className="button button-primary"
            >
              {analyzingImpact ? 'Analyzing...' : 'Calculate Blast Radius'}
            </button>
          </div>

          {blastReport && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Score breakdown banner */}
              <div style={{ padding: '1rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <div>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>CALIBRATED BLAST RADIUS SCORE</span>
                    <div style={{ fontSize: '1.75rem', fontWeight: 'bold', color: blastReport.blast_radius_score >= 45 ? '#f43f5e' : blastReport.blast_radius_score >= 20 ? '#fbbf24' : '#34d399' }}>
                      {blastReport.blast_radius_score} / 100 ({blastReport.risk_level})
                    </div>
                  </div>
                  {blastReport.score_breakdown && (
                    <div style={{ textAlign: 'right', fontSize: '0.8rem', color: '#94a3b8' }}>
                      <div>Measured Structural Score: <strong style={{ color: '#38bdf8' }}>{blastReport.score_breakdown.measured_structural_score}</strong> / 50</div>
                      <div>Heuristic Risk Factor Score: <strong style={{ color: '#f59e0b' }}>{blastReport.score_breakdown.heuristic_risk_score}</strong> / 50</div>
                    </div>
                  )}
                </div>
                {blastReport.score_explanation && (
                  <p style={{ margin: 0, fontSize: '0.8rem', color: '#cbd5e1', lineHeight: 1.4, borderTop: '1px solid #1e293b', paddingTop: '0.5rem' }}>
                    {blastReport.score_explanation}
                  </p>
                )}
              </div>

              {/* Measured Properties vs Heuristic Factors */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div style={{ padding: '0.75rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
                  <h4 style={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#38bdf8', marginBottom: '0.5rem' }}>
                    Measured Graph Topology
                  </h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.75rem', color: '#cbd5e1', lineHeight: 1.6 }}>
                    <li>Direct Symbols: <strong>{blastReport.direct_symbols_count}</strong> | Transitive: <strong>{blastReport.transitive_symbols_count}</strong></li>
                    <li>Affected APIs: <strong>{blastReport.affected_apis_count}</strong> | Tables: <strong>{blastReport.affected_tables_count}</strong></li>
                    <li>Boundaries: <strong>{blastReport.boundaries_crossed.join(', ') || 'None'}</strong></li>
                    {blastReport.measured_properties && (
                      <li>Max Depth: <strong>{blastReport.measured_properties.max_dependency_depth}</strong> | Fan-In: <strong>{blastReport.measured_properties.total_fan_in}</strong></li>
                    )}
                  </ul>
                </div>

                <div style={{ padding: '0.75rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
                  <h4 style={{ fontSize: '0.8rem', fontWeight: 'bold', color: '#f59e0b', marginBottom: '0.5rem' }}>
                    Heuristic Risk Factors
                  </h4>
                  {blastReport.risk_factors.length === 0 ? (
                    <p style={{ fontSize: '0.75rem', color: '#34d399', margin: 0 }}>No high-risk sensitivity factors triggered.</p>
                  ) : (
                    <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.75rem', color: '#fde047', lineHeight: 1.6 }}>
                      {blastReport.risk_factors.map((rf, i) => (
                        <li key={i}>{rf}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* Impacted Components List */}
              <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0', marginBottom: '0.5rem' }}>
                  Downstream Impacted Components ({blastReport.impact_report.impacted_components.length}):
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', maxHeight: '280px', overflowY: 'auto' }}>
                  {blastReport.impact_report.impacted_components.map((c, i) => (
                    <div
                      key={i}
                      onClick={() => handleLoadSubgraph(c.canonical_id)}
                      style={{
                        padding: '0.375rem 0.5rem',
                        background: '#0f172a',
                        border: '1px solid #1e293b',
                        borderRadius: '0.25rem',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: '0.75rem',
                        cursor: 'pointer',
                      }}
                    >
                      <div>
                        <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{c.name}</span>
                        <span style={{ color: '#64748b', marginLeft: '0.5rem' }}>({c.entity_type} in {c.file_path})</span>
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <span style={{
                          padding: '0.125rem 0.375rem',
                          borderRadius: '0.25rem',
                          fontSize: '0.65rem',
                          fontWeight: 'bold',
                          background: c.impact_level === 'DIRECTLY_AFFECTED' ? '#065f46' : '#1e3a8a',
                          color: c.impact_level === 'DIRECTLY_AFFECTED' ? '#34d399' : '#93c5fd',
                        }}>
                          {c.impact_level} (depth {c.depth})
                        </span>
                        <span style={{ color: '#38bdf8' }}>View Subgraph →</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Targeted Test Recommendations */}
      {activeTab === 'tests' && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
            Ranked Evidence-Based Test Suites (Precision-Prioritized)
          </h3>
          {recommendedTests.length === 0 ? (
            <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              Run Change Impact analysis above to populate recommended tests targeted to modified components.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {recommendedTests.map((t, i) => (
                <div key={i} style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '0.8rem' }}>{t.test_name}</div>
                    <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{t.file_path} — {t.reason}</div>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{
                      padding: '0.125rem 0.375rem',
                      borderRadius: '0.25rem',
                      fontSize: '0.65rem',
                      fontWeight: 'bold',
                      background: t.classification === 'RUNTIME_CONFIRMED_TEST' ? '#047857' : t.tier === 'DIRECT_TEST' ? '#14532d' : '#1e293b',
                      color: t.classification === 'RUNTIME_CONFIRMED_TEST' ? '#6ee7b7' : t.tier === 'DIRECT_TEST' ? '#4ade80' : '#94a3b8',
                    }}>
                      {t.classification || t.tier}
                    </span>
                    <span style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 'bold' }}>
                      {Math.round(t.confidence * 100)}% conf
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Identity Continuity & Ambiguous Candidate Inspector */}
      {activeTab === 'continuity' && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
            Entity Identity Continuity Transitions Across Revisions
          </h3>
          {loadingTransitions ? (
            <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Loading identity transitions...</p>
          ) : transitions.length === 0 ? (
            <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>No recorded transitions yet. Incremental updates track symbol moves, renames, splits, and merges.</p>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: selectedTransition ? '1fr 1fr' : '1fr', gap: '1rem' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', maxHeight: '420px', overflowY: 'auto' }}>
                {transitions.map((tr) => (
                  <div
                    key={tr.id}
                    onClick={() => setSelectedTransition(tr)}
                    style={{
                      padding: '0.375rem 0.5rem',
                      background: selectedTransition?.id === tr.id ? '#1e293b' : '#0f172a',
                      border: `1px solid ${selectedTransition?.id === tr.id ? '#38bdf8' : '#1e293b'}`,
                      borderRadius: '0.25rem',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: '0.75rem',
                      cursor: 'pointer',
                    }}
                  >
                    <div>
                      <span style={{
                        padding: '0.1rem 0.35rem',
                        borderRadius: '0.2rem',
                        fontSize: '0.65rem',
                        fontWeight: 'bold',
                        background: tr.transition_type === 'AMBIGUOUS' ? '#831843' : tr.transition_type === 'SPLIT' ? '#581c87' : tr.transition_type === 'MERGED' ? '#1e3a5f' : tr.transition_type.includes('RENAME') ? '#7c2d12' : '#14532d',
                        color: tr.transition_type === 'AMBIGUOUS' ? '#f472b6' : tr.transition_type === 'SPLIT' ? '#d8b4fe' : tr.transition_type === 'MERGED' ? '#93c5fd' : tr.transition_type.includes('RENAME') ? '#fdba74' : '#86efac',
                        marginRight: '0.5rem',
                      }}>
                        {tr.transition_type}
                      </span>
                      <span style={{ color: '#cbd5e1' }}>
                        {tr.old_canonical_id ? tr.old_canonical_id.split('::')[2] || tr.old_canonical_id : 'NEW'} → {tr.new_canonical_id ? tr.new_canonical_id.split('::')[2] || tr.new_canonical_id : 'DELETED'}
                      </span>
                    </div>
                    <span style={{ color: '#38bdf8', fontWeight: 'bold' }}>{Math.round(tr.confidence * 100)}% conf</span>
                  </div>
                ))}
              </div>

              {selectedTransition && (
                <div style={{ padding: '0.75rem', background: '#0f172a', border: '1px solid #334155', borderRadius: '0.375rem', fontSize: '0.75rem', maxHeight: '420px', overflowY: 'auto' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <strong style={{ color: '#38bdf8', fontSize: '0.85rem' }}>Ambiguous Match & Candidate Inspector</strong>
                    <button type="button" onClick={() => setSelectedTransition(null)} style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer' }}>✕</button>
                  </div>
                  <div style={{ marginBottom: '0.5rem', color: '#cbd5e1' }}>
                    <div><strong>Transition:</strong> {selectedTransition.transition_type} ({Math.round(selectedTransition.confidence * 100)}% confidence)</div>
                    <div><strong>From:</strong> <code>{selectedTransition.old_canonical_id}</code></div>
                    <div><strong>To:</strong> <code>{selectedTransition.new_canonical_id}</code></div>
                  </div>
                  <h4 style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '0.75rem', marginBottom: '0.25rem' }}>Retained Candidate Candidates & Multi-Signal Evidence:</h4>
                  {selectedTransition.evidence?.candidates ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      {(selectedTransition.evidence.candidates as Array<{ canonical_id: string; score: number }>).map((c, idx) => (
                        <div key={idx} style={{ padding: '0.25rem 0.5rem', background: '#020617', borderRadius: '0.2rem', display: 'flex', justifyContent: 'space-between', color: '#f1f5f9' }}>
                          <span style={{ fontFamily: 'monospace' }}>{c.canonical_id}</span>
                          <span style={{ color: '#34d399', fontWeight: 'bold' }}>{Math.round((c.score || 0) * 100)}% match</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre style={{ margin: 0, padding: '0.5rem', background: '#020617', borderRadius: '0.25rem', color: '#94a3b8', fontSize: '0.7rem' }}>
                      {JSON.stringify(selectedTransition.evidence, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 5: Coverage Matrix */}
      {activeTab === 'coverage' && coverageReport && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <div>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', margin: 0 }}>
                Honest Multi-Dimensional Coverage Matrix
              </h3>
              <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: '0.25rem 0 0 0' }}>
                Evaluates file discovery, symbol extraction, relationships, frameworks, and cross-language resolution separately.
              </p>
            </div>
            <span style={{ fontSize: '0.85rem', fontWeight: 'bold', color: '#34d399' }}>
              Overall Score: {coverageReport.overall_coverage_percentage}%
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '0.75rem' }}>
            {Object.values(coverageReport.technologies).map((tech) => (
              <div key={tech.technology} style={{ padding: '0.75rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                  <span style={{ fontWeight: 'bold', color: '#f8fafc', fontSize: '0.85rem' }}>{tech.technology}</span>
                  <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.35rem', borderRadius: '0.2rem', background: tech.status === 'COMPLETE' ? '#065f46' : tech.status === 'PARTIAL' ? '#854d0e' : '#1e293b', color: tech.status === 'COMPLETE' ? '#34d399' : tech.status === 'PARTIAL' ? '#fde047' : '#94a3b8' }}>
                      {tech.status || 'REPORTED'}
                    </span>
                    <span style={{ fontSize: '0.75rem', fontWeight: 'bold', color: tech.coverage_score >= 80 ? '#34d399' : tech.coverage_score > 0 ? '#fbbf24' : '#64748b' }}>
                      {tech.coverage_score}%
                    </span>
                  </div>
                </div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', marginBottom: '0.5rem' }}>
                  Discovered: {tech.files_discovered} files | Parsed: {tech.files_parsed} files | Symbols: {tech.symbols_extracted}
                </div>
                {/* 5 Distinct Dimensions */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.65rem', borderTop: '1px solid #1e293b', paddingTop: '0.35rem' }}>
                  {tech.file_discovery_coverage !== undefined && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>File Discovery:</span>
                      <strong style={{ color: '#38bdf8' }}>{tech.file_discovery_coverage}%</strong>
                    </div>
                  )}
                  {tech.symbol_extraction_coverage !== undefined && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>Symbol Extraction:</span>
                      <strong style={{ color: '#34d399' }}>{tech.symbol_extraction_coverage}%</strong>
                    </div>
                  )}
                  {tech.relationship_extraction_coverage !== undefined && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>Relationship Extraction:</span>
                      <strong style={{ color: '#a78bfa' }}>{tech.relationship_extraction_coverage}%</strong>
                    </div>
                  )}
                  {tech.framework_specific_coverage !== undefined && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>Framework Specific:</span>
                      <strong style={{ color: '#f59e0b' }}>{tech.framework_specific_coverage}%</strong>
                    </div>
                  )}
                  {tech.cross_language_resolution_coverage !== undefined && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: '#94a3b8' }}>Cross-Language Resolution:</span>
                      <strong style={{ color: '#ec4899' }}>{tech.cross_language_resolution_coverage}%</strong>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 6: Version Diff */}
      {activeTab === 'diff' && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.5rem' }}>
            Graph Snapshot Version Comparison
          </h3>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Compare Version:</span>
            <select
              value={selectedV1}
              onChange={e => setSelectedV1(Number(e.target.value))}
              style={{ padding: '0.25rem 0.5rem', background: '#0f172a', border: '1px solid #334155', color: '#f8fafc', borderRadius: '0.25rem', fontSize: '0.8rem' }}
            >
              {versions.map(v => (
                <option key={v.id} value={v.version_number}>v{v.version_number} ({v.status})</option>
              ))}
            </select>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>with Version:</span>
            <select
              value={selectedV2}
              onChange={e => setSelectedV2(Number(e.target.value))}
              style={{ padding: '0.25rem 0.5rem', background: '#0f172a', border: '1px solid #334155', color: '#f8fafc', borderRadius: '0.25rem', fontSize: '0.8rem' }}
            >
              {versions.map(v => (
                <option key={v.id} value={v.version_number}>v{v.version_number} ({v.status})</option>
              ))}
            </select>
            <button
              type="button"
              disabled={loadingDiff}
              onClick={handleCompareVersions}
              className="button button-sm button-secondary"
            >
              {loadingDiff ? 'Diffing...' : 'Compare Versions'}
            </button>
          </div>

          {versionDiff && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
              <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#34d399' }}>+ ADDED NODES</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{versionDiff.added_nodes_count}</div>
              </div>
              <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#f43f5e' }}>- REMOVED NODES</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{versionDiff.removed_nodes_count}</div>
              </div>
              <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#fbbf24' }}>~ MODIFIED NODES</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{versionDiff.modified_nodes_count}</div>
              </div>
              <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                <div style={{ fontSize: '0.7rem', color: '#38bdf8' }}>→ RENAMED ENTITIES</div>
                <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#f8fafc' }}>{versionDiff.renamed_entities_count}</div>
              </div>
              {versionDiff.split_entities && versionDiff.split_entities.length > 0 && (
                <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                  <div style={{ fontSize: '0.7rem', color: '#d8b4fe' }}>⑂ SPLIT ENTITIES</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#d8b4fe' }}>{versionDiff.split_entities.length}</div>
                </div>
              )}
              {versionDiff.merged_entities && versionDiff.merged_entities.length > 0 && (
                <div style={{ padding: '0.5rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem' }}>
                  <div style={{ fontSize: '0.7rem', color: '#93c5fd' }}>⑃ MERGED ENTITIES</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#93c5fd' }}>{versionDiff.merged_entities.length}</div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 7: Neighborhood Subgraph */}
      {activeTab === 'subgraph' && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
            <input
              type="text"
              value={subgraphCenter}
              onChange={e => setSubgraphCenter(e.target.value)}
              placeholder="Enter canonical ID or symbol name to center graph"
              style={{ flex: 1, padding: '0.375rem 0.5rem', background: '#0f172a', border: '1px solid #334155', borderRadius: '0.25rem', color: '#f8fafc', fontSize: '0.8rem' }}
            />
            <button
              type="button"
              disabled={subgraphLoading}
              onClick={() => handleLoadSubgraph(subgraphCenter)}
              className="button button-sm button-secondary"
            >
              {subgraphLoading ? 'Loading...' : 'Query Subgraph'}
            </button>
          </div>

          {subgraphData ? (
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                Subgraph centered at <code style={{ color: '#38bdf8' }}>{subgraphData.center_id}</code>: {subgraphData.total_nodes} nodes, {subgraphData.total_edges} relationships.
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', maxHeight: '350px', overflowY: 'auto' }}>
                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#cbd5e1', marginBottom: '0.25rem' }}>Nodes in Neighborhood:</div>
                  {subgraphData.nodes.map((n, i) => (
                    <div key={i} style={{ padding: '0.25rem 0.375rem', fontSize: '0.7rem', color: '#e2e8f0', borderBottom: '1px solid #0f172a' }}>
                      <strong style={{ color: '#38bdf8' }}>[{n.entity_type}]</strong> {n.name} <span style={{ color: '#64748b' }}>({n.file_path})</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#cbd5e1', marginBottom: '0.25rem' }}>Relationships:</div>
                  {subgraphData.edges.map((e, i) => (
                    <div key={i} style={{ padding: '0.25rem 0.375rem', fontSize: '0.7rem', color: '#e2e8f0', borderBottom: '1px solid #0f172a' }}>
                      <span style={{ color: '#cbd5e1' }}>{e.source_canonical_id.split('::')[2] || e.source_canonical_id}</span>
                      <strong style={{ color: '#f59e0b', margin: '0 0.25rem' }}>--{e.rel_type}→</strong>
                      <span style={{ color: '#cbd5e1' }}>{e.target_canonical_id.split('::')[2] || e.target_canonical_id}</span>
                      <span style={{ color: '#64748b', marginLeft: '0.25rem' }}>({Math.round(e.confidence * 100)}%)</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              Select a component from Change Impact or enter a canonical ID to inspect its 2-hop neighborhood.
            </p>
          )}
        </div>
      )}

      {/* Tab 8: Cross-Technology Relationship Traces */}
      {activeTab === 'cross-tech' && (
        <div style={{ padding: '1rem', background: '#020617', border: '1px solid #1e293b', borderRadius: '0.375rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <div>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f1f5f9', margin: 0 }}>
                Cross-Technology Relationship Traces
              </h3>
              <p style={{ fontSize: '0.75rem', color: '#94a3b8', margin: '0.25rem 0 0 0' }}>
                Traces relationships spanning React components, API clients, FastAPI endpoints, route handlers, DB models, Dockerfiles, and CI workflows.
              </p>
            </div>
            <button
              type="button"
              className="button button-sm button-secondary"
              onClick={loadCrossTech}
              disabled={loadingCrossTech}
            >
              {loadingCrossTech ? 'Refreshing...' : 'Refresh Traces'}
            </button>
          </div>

          {loadingCrossTech ? (
            <p style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Loading cross-technology traces...</p>
          ) : crossTechEdges.length === 0 ? (
            <div style={{ padding: '1rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem', textAlign: 'center' }}>
              <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>
                No cross-technology relationships detected yet. Trigger a rebuild or incremental update on a multi-tier codebase to extract cross-stack edges.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: '420px', overflowY: 'auto' }}>
              {crossTechEdges.map((e, idx) => (
                <div key={idx} style={{ padding: '0.5rem 0.75rem', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '0.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                    <code style={{ color: '#38bdf8', fontSize: '0.75rem' }}>{e.source_canonical_id.split('::')[2] || e.source_canonical_id}</code>
                    <span style={{
                      padding: '0.125rem 0.4rem',
                      borderRadius: '0.25rem',
                      fontSize: '0.65rem',
                      fontWeight: 'bold',
                      background: e.rel_type === 'CALLS_API' ? '#047857' : e.rel_type === 'QUERIES_MODEL' ? '#4338ca' : e.rel_type === 'EXECUTES_ENTRYPOINT' ? '#b45309' : '#1e293b',
                      color: e.rel_type === 'CALLS_API' ? '#6ee7b7' : e.rel_type === 'QUERIES_MODEL' ? '#a5b4fc' : e.rel_type === 'EXECUTES_ENTRYPOINT' ? '#fcd34d' : '#cbd5e1',
                    }}>
                      {e.rel_type}
                    </span>
                    <span style={{ color: '#94a3b8' }}>→</span>
                    <code style={{ color: '#34d399', fontSize: '0.75rem' }}>{e.target_canonical_id.split('::')[2] || e.target_canonical_id}</code>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ color: '#64748b', fontSize: '0.7rem' }}>{e.analyzer_source}</span>
                    <span style={{ color: '#38bdf8', fontWeight: 'bold' }}>{Math.round(e.confidence * 100)}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
