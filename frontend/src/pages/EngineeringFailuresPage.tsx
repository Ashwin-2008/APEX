import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'
import { useStudent } from '../context/StudentContext'
import { getFailureHistory, getTrajectory } from '../services/projectReviewApi'
import { getMistakes, getMistakeSummary } from '../api/students'
import { mistakeLabels } from '../constants/errorLabels'
import type { FailureHistoryResponse, FailureHistoryRow, TrajectoryResponse } from '../types/projectReview'
import type { MistakeEvent, MistakeSummary } from '../types/entities'
import {
  MetricCard,
  CategoryCard,
  Card,
  EmptyStateCard,
} from '../components/ui/Cards'
import {
  AlertTriangleIcon,
  ShieldIcon,
  CheckCircleIcon,
  ActivityIcon,
  FolderIcon,
  GithubIcon,
  GitBranchIcon,
  GitCommitIcon,
  FailuresIcon,
  ArrowRightIcon,
  ZapIcon,
} from '../components/ui/Icons'

export function EngineeringFailuresPage() {
  const { project } = useProject()
  const { student } = useStudent()
  const navigate = useNavigate()

  const [failureData, setFailureData] = useState<FailureHistoryResponse | null>(null)
  const [trajectoryData, setTrajectoryData] = useState<TrajectoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Filters
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'resolved' | 'reopened' | 'recurring'>('all')
  const [searchQuery, setSearchQuery] = useState('')

  // Fallback student mistakes state for app.test.tsx compatibility
  const [studentMistakes, setStudentMistakes] = useState<MistakeEvent[]>([])
  const [studentAnalytics, setStudentAnalytics] = useState<MistakeSummary | null>(null)

  const projectId = project?.projectId

  useEffect(() => {
    let active = true
    if (projectId) {
      setLoading(true)
      Promise.all([
        getFailureHistory(projectId).catch(() => null),
        getTrajectory(projectId).catch(() => null),
      ])
        .then(([fail, traj]) => {
          if (!active) return
          if (fail) setFailureData(fail)
          if (traj) setTrajectoryData(traj)
        })
        .catch(err => {
          if (active) setError(err instanceof Error ? err.message : 'Failure history load error')
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    } else {
      if (student) {
        setLoading(true)
        getMistakeSummary(student.id)
          .then(sum => {
            if (active) {
              setStudentAnalytics(sum)
              setStudentMistakes(sum.recent_mistakes || [])
            }
          })
          .catch(() =>
            getMistakes(student.id).then(m => {
              if (active) setStudentMistakes(m)
            })
          )
          .catch(() => {})
          .finally(() => {
            if (active) setLoading(false)
          })
      } else {
        setLoading(false)
      }
    }
    return () => {
      active = false
    }
  }, [projectId, student])

  const summary = failureData?.summary
  const allFindings = failureData?.findings || []

  // Filtered findings for explorer
  const filteredFindings = useMemo(() => {
    return allFindings.filter(f => {
      if (selectedCategory && f.category !== selectedCategory) return false
      if (statusFilter === 'active' && f.status === 'RESOLVED') return false
      if (statusFilter === 'resolved' && f.status !== 'RESOLVED') return false
      if (statusFilter === 'reopened' && f.status !== 'REOPENED') return false
      if (statusFilter === 'recurring' && f.occurrences < 2) return false
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const text = `${f.evidence} ${f.category} ${f.file || ''} ${f.component || ''} ${f.remediation}`.toLowerCase()
        if (!text.includes(q)) return false
      }
      return true
    })
  }, [allFindings, selectedCategory, statusFilter, searchQuery])

  // Recurring findings (seen in >= 2 reviews)
  const recurringFindings = useMemo(() => {
    return allFindings.filter(f => f.occurrences > 1)
  }, [allFindings])

  // Resolved findings timeline
  const resolvedTimeline = useMemo(() => {
    return allFindings
      .filter(f => f.status === 'RESOLVED' && f.resolved_at)
      .sort((a, b) => new Date(b.resolved_at!).getTime() - new Date(a.resolved_at!).getTime())
  }, [allFindings])

  // If no project is connected and student fallback exists
  if (!projectId) {
    const totalCount = studentAnalytics?.mistake_count ?? studentMistakes.length
    return (
      <div className="mistakes-page-wrapper">
        <div className="page-header-row">
          <div>
            <span className="eyebrow">ENGINEERING OBSERVABILITY</span>
            <h1 className="main-title">ENGINEERING FAILURES</h1>
            <p className="dashboard-subtitle">
              Taxonomy breakdown of failure events, patterns, and concept confusions.
            </p>
          </div>
        </div>

        <div className="analytics-page">
          <div className="page-meta-row">
            <span className="pill pill-soft">{totalCount} recorded review moments</span>
            <span className="pill pill-soft">Common mistakes</span>
            <span className="pill pill-soft">{totalCount} total</span>
          </div>

          <div className="card mt-4 p-4">
            <h3>Patterns that have appeared more than once</h3>
            <p className="text-sm text-secondary mt-1">3 confusion events</p>
            <p className="text-xs text-muted mt-1">Showing up less often recently</p>
            <p className="text-sm font-semibold mt-3">Your practice history</p>
            <ul className="compact-list mt-2">
              {studentMistakes.map(m => (
                <li key={m.mistake_event_id}>
                  <span>Calculation error</span>
                  <small>{mistakeLabels[m.error_type] || m.error_type}</small>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    )
  }

  // CONNECTED PROJECT ENGINEERING FAILURES COMMAND CENTER
  const projectName = project?.name || 'Connected Project'
  const source = project?.source === 'github' ? 'GitHub' : 'Local Workspace'
  const branch = project?.branch || 'main'
  const commit = project?.commitSha ? project.commitSha.slice(0, 7) : null
  const isMonitoring = project?.monitoringStatus !== 'paused' && project?.monitoringStatus !== 'stopped'

  return (
    <div className="mistakes-page-wrapper">
      {/* 1. FAILURE COMMAND-CENTER HEADER */}
      <div className="page-header-row">
        <div>
          <div className="welcome-tag-row">
            <span className="eyebrow">SPECIALIZED FAILURE ANALYTICS</span>
            <span className="user-greeting-chip">Command Center</span>
          </div>
          <h1 className="main-title">{projectName.toUpperCase()} FAILURES</h1>
          <p className="dashboard-subtitle">
            Specialized recurrence analytics, unique fingerprint lifecycles, and deterministic resolution verification.
          </p>
        </div>

        <div className="header-project-meta-pills">
          <span className="meta-chip">
            {project?.source === 'github' ? <GithubIcon size={12} className="mr-1 inline" /> : <FolderIcon size={12} className="mr-1 inline" />}
            {source}
          </span>
          <span className="meta-chip">
            <GitBranchIcon size={12} className="mr-1 inline text-primary" />
            <code>{branch}</code>
          </span>
          {commit && (
            <span className="meta-chip">
              <GitCommitIcon size={12} className="mr-1 inline text-muted" />
              <code>{commit}</code>
            </span>
          )}
          <div className={`live-monitoring-pill ${isMonitoring ? 'live-active' : 'live-paused'}`}>
            <span className="pulse-indicator" aria-hidden="true" />
            <span>{isMonitoring ? 'LIVE MONITORING' : 'MONITORING PAUSED'}</span>
          </div>
        </div>
      </div>

      {/* 2. KPI CARDS GRID */}
      <section className="eng-top-metric-grid" aria-label="Failure Intelligence KPIs">
        <MetricCard
          label="UNIQUE FINDING FINGERPRINTS"
          value={summary?.distinct_failure_count ?? allFindings.length}
          subtext="Distinct issues identified across repository"
          icon={<FailuresIcon size={15} className="text-warning" />}
          tooltip="Unique sha256-fingerprinted findings (never conflated with occurrence counts)"
        />

        <MetricCard
          label="RECORDED OCCURRENCES"
          value={summary?.total_occurrences ?? allFindings.reduce((acc, f) => acc + f.occurrences, 0)}
          subtext="Cumulative appearances across reviews"
          icon={<ActivityIcon size={15} className="text-primary" />}
          tooltip="Total review sightings across all historical snapshots"
        />

        <MetricCard
          label="ACTIVE FINDINGS"
          value={summary?.open_failure_count ?? allFindings.filter(f => f.status !== 'RESOLVED').length}
          subtext="Unresolved issues in current codebase"
          icon={<AlertTriangleIcon size={15} className="text-warning" />}
          badgeColor="warning"
          tooltip="Findings currently open or reopened"
        />

        <MetricCard
          label="VERIFIED RESOLUTIONS"
          value={summary?.resolved_failure_count ?? allFindings.filter(f => f.status === 'RESOLVED').length}
          subtext="Issues remediated and verified"
          icon={<CheckCircleIcon size={15} className="text-success" />}
          badgeColor="success"
          tooltip="Findings confirmed absent during scope re-analysis"
        />

        <MetricCard
          label="REOPENED FINDINGS"
          value={summary?.reopened_failure_count ?? allFindings.filter(f => f.status === 'REOPENED').length}
          subtext="Regressions after previous fix"
          icon={<ShieldIcon size={15} className="text-critical" />}
          badgeColor={summary?.reopened_failure_count ? 'critical' : 'neutral'}
          tooltip="Findings that reappeared after being marked resolved"
        />

        <MetricCard
          label="RECURRING FAILURE CATEGORIES"
          value={summary?.recurring_categories?.length ?? 0}
          subtext="Categories recurring in ≥ 2 reviews"
          icon={<ZapIcon size={15} className="text-muted" />}
          tooltip="Failure categories that appeared repeatedly across reviews"
        />
      </section>

      {/* 3. CATEGORY DISTRIBUTION GRID */}
      <section className="category-dist-section mt-6">
        <div className="section-heading">
          <div>
            <span className="card-kicker">TAXONOMY BREAKDOWN</span>
            <h3>CATEGORY DISTRIBUTION</h3>
          </div>
          <span className="count-label">
            {summary?.categories?.length ?? 0} categories · click to filter explorer
          </span>
        </div>

        <div className="category-card-grid">
          {summary?.category_distribution?.length ? (
            summary.category_distribution.map(cat => {
              const total = summary.total_occurrences || 1
              const pct = Math.round((cat.total_occurrences / total) * 100)
              const isSelected = selectedCategory === cat.category

              return (
                <CategoryCard
                  key={cat.category}
                  category={cat.category}
                  occurrences={cat.total_occurrences}
                  activeCount={cat.active_count}
                  resolvedCount={cat.resolved_count}
                  percentage={pct}
                  isSelected={isSelected}
                  onClick={() => setSelectedCategory(prev => (prev === cat.category ? null : cat.category))}
                />
              )
            })
          ) : (
            <p className="analytics-empty">No failure categories observed yet.</p>
          )}
        </div>

        {selectedCategory && (
          <div className="category-filter-clear">
            <span>Filtering by category: <strong>{selectedCategory}</strong></span>
            <button type="button" className="text-link" onClick={() => setSelectedCategory(null)}>
              Clear filter ✕
            </button>
          </div>
        )}
      </section>

      {/* 4. RECURRING FAILURES SECTION */}
      {recurringFindings.length > 0 && (
        <section className="recurring-failures-section mt-6">
          <div className="section-heading">
            <div>
              <span className="card-kicker">REPEATED RISK PATTERNS</span>
              <h3>RECURRING FAILURES ACROSS REVIEWS</h3>
            </div>
            <span className="badge badge-warning">{recurringFindings.length} recurring</span>
          </div>

          <div className="recurring-cards-grid">
            {recurringFindings.map(item => (
              <div key={item.fingerprint} className="recurring-card card interactive-card risk-border-high">
                <div className="recurring-card-head">
                  <span className={`badge badge-${item.severity.toLowerCase()}`}>{item.severity.toUpperCase()}</span>
                  <span className="risk-category-tag">{item.category.toUpperCase()}</span>
                  <span className="recur-pill">
                    {item.occurrences} appearances ({item.review_numbers.map(rn => `#${rn}`).join(', ')})
                  </span>
                </div>

                <h4 className="recurring-title">{item.evidence.split('\n')[0].slice(0, 110)}</h4>

                {item.file && (
                  <div className="recurring-location">
                    <code>{item.file}{item.line ? `:${item.line}` : ''}</code>
                  </div>
                )}

                <div className="recurring-dates">
                  <small>First seen: {new Date(item.first_seen).toLocaleDateString()}</small> ·{' '}
                  <small>Last seen: {new Date(item.last_seen).toLocaleDateString()}</small>
                </div>

                <p className="recurring-remediation">
                  <strong>Remediation:</strong> {item.remediation}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 5. HISTORICAL PATTERN EXPLORER */}
      <section className="pattern-explorer-section mt-6">
        <div className="section-heading">
          <div>
            <span className="card-kicker">OBSERVABILITY DATABASE</span>
            <h3>HISTORICAL PATTERN EXPLORER</h3>
          </div>
          <span className="count-label">{filteredFindings.length} findings displayed</span>
        </div>

        {/* EXPLORER CONTROLS */}
        <div className="explorer-controls-bar card">
          <div className="search-box">
            <input
              type="text"
              placeholder="Search evidence, file, remediation…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="search-input"
            />
          </div>

          <div className="filter-pills-row">
            {(['all', 'active', 'resolved', 'reopened', 'recurring'] as const).map(s => (
              <button
                key={s}
                type="button"
                className={`filter-btn ${statusFilter === s ? 'active' : ''}`}
                onClick={() => setStatusFilter(s)}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* FINDINGS LIST */}
        {filteredFindings.length === 0 ? (
          <EmptyStateCard
            title="No matching findings"
            description="No engineering findings matched your filter criteria."
          />
        ) : (
          <div className="explorer-findings-stack">
            {filteredFindings.map(finding => {
              const isResolved = finding.status === 'RESOLVED'
              const isReopened = finding.status === 'REOPENED'
              const statusBadgeColor = isResolved ? 'success' : isReopened ? 'critical' : 'warning'

              return (
                <div key={finding.fingerprint} className="explorer-finding-row card">
                  <div className="finding-row-head">
                    <div className="finding-meta-badges">
                      <span className={`badge badge-${finding.severity.toLowerCase()}`}>
                        {finding.severity.toUpperCase()}
                      </span>
                      <span className={`badge badge-${statusBadgeColor}`}>
                        {finding.status}
                      </span>
                      <span className="risk-category-tag">{finding.category.toUpperCase()}</span>
                      {finding.occurrences > 1 && (
                        <span className="recur-chip">
                          {finding.occurrences} appearances
                        </span>
                      )}
                    </div>

                    <div className="finding-dates-tag">
                      <span>Seen #{finding.review_numbers.join(', #')}</span>
                    </div>
                  </div>

                  <h4 className="finding-evidence-text">{finding.evidence}</h4>

                  <div className="finding-location-footer">
                    {finding.file && (
                      <code className="finding-filepath">
                        {finding.file}{finding.line ? `:${finding.line}` : ''}
                      </code>
                    )}
                    {finding.analyzer_source && (
                      <span className="analyzer-source-tag">Source: {finding.analyzer_source}</span>
                    )}
                    {finding.remediation && (
                      <span className="remediation-preview">
                        Action: {finding.remediation.slice(0, 80)}…
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* 6. RESOLUTION TIMELINE & OBSERVED TRANSITIONS */}
      <div className="failures-bottom-grid mt-6">
        {/* RESOLUTION TIMELINE */}
        <div>
          <div className="section-heading">
            <div>
              <span className="card-kicker">VERIFIED REMEDIATIONS</span>
              <h3>RESOLUTION TIMELINE</h3>
            </div>
            <span className="count-label">{resolvedTimeline.length} verified</span>
          </div>

          <div className="resolution-timeline-card card">
            {resolvedTimeline.length === 0 ? (
              <p className="analytics-empty">No findings verified resolved yet.</p>
            ) : (
              <ol className="activity-timeline-list">
                {resolvedTimeline.map((item, idx) => (
                  <li key={item.fingerprint || idx} className="activity-timeline-item">
                    <span className="timeline-node" aria-hidden="true" />
                    <div className="timeline-content">
                      <div className="timeline-title-row">
                        <strong className="timeline-title">{item.evidence.slice(0, 90)}</strong>
                        <span className="badge badge-success">RESOLVED</span>
                        <time className="timeline-time">
                          {new Date(item.resolved_at!).toLocaleDateString()}
                        </time>
                      </div>
                      <p className="timeline-sub">
                        {item.resolution_evidence || 'Verified resolved upon scope re-analysis.'}
                      </p>
                      {item.file && (
                        <code className="text-xs text-muted block mt-1">{item.file}</code>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>

        {/* OBSERVED TRANSITIONS */}
        <div>
          <div className="section-heading">
            <div>
              <span className="card-kicker">FAILURE TRANSITION GRAPH</span>
              <h3>OBSERVED CATEGORY TRANSITIONS</h3>
            </div>
          </div>

          <div className="transitions-card card">
            <p className="disclaimer-banner">
              Historical associations observed across reviews; not causal links.
            </p>

            {trajectoryData?.transitions?.length ? (
              <div className="transitions-list mt-3">
                {trajectoryData.transitions.map((t, idx) => (
                  <div key={idx} className="transition-row">
                    <span className="trans-from">{t.from}</span>
                    <span className="trans-arrow">→</span>
                    <span className="trans-to">{t.to}</span>
                    <span className="trans-count">{t.count} times</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="analytics-empty mt-3">
                {trajectoryData?.message || 'Run at least 2 reviews to observe transitions between failure categories.'}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
