import React, { useState } from 'react'
import {
  ShieldIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  ActivityIcon,
  ZapIcon,
  GitBranchIcon,
  GitCommitIcon,
  GithubIcon,
  FolderIcon,
  ArrowRightIcon,
} from './Icons'

export { Card } from './Card'

/* ==========================================================================
   1. METRIC CARD
   ========================================================================== */
export interface MetricCardProps {
  label: string
  value: string | number
  subtext?: string
  icon?: React.ReactNode
  trend?: { direction: 'up' | 'down' | 'neutral'; label: string }
  badge?: string
  badgeColor?: 'critical' | 'warning' | 'success' | 'info' | 'neutral'
  onClick?: () => void
  tooltip?: string
  className?: string
}

export function MetricCard({
  label,
  value,
  subtext,
  icon,
  trend,
  badge,
  badgeColor = 'neutral',
  onClick,
  tooltip,
  className = '',
}: MetricCardProps) {
  const isClickable = Boolean(onClick)
  return (
    <div
      className={`metric-box card interactive-card ${isClickable ? 'clickable' : ''} ${className}`}
      onClick={onClick}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.() } } : undefined}
      title={tooltip}
    >
      <div className="metric-box-head">
        <span className="metric-box-label">{label}</span>
        {icon && <span className="metric-box-icon" aria-hidden="true">{icon}</span>}
      </div>
      <div className="metric-box-main">
        <strong className="metric-box-value">{value}</strong>
        {badge && <span className={`badge badge-${badgeColor} ml-2`}>{badge}</span>}
      </div>
      {(subtext || trend) && (
        <div className="metric-box-footer">
          {trend && (
            <span className={`trend-indicator trend-${trend.direction}`}>
              {trend.direction === 'up' ? '↑' : trend.direction === 'down' ? '↓' : '→'} {trend.label}
            </span>
          )}
          {subtext && <span className="metric-box-sub">{subtext}</span>}
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   2. RISK CARD
   ========================================================================== */
export interface RiskCardProps {
  category: string
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  title: string
  location?: string | null
  whyItMatters: string
  whatToDo: string
  evidence?: string | null
  onClick?: () => void
}

export function RiskCard({
  category,
  severity,
  title,
  location,
  whyItMatters,
  whatToDo,
  evidence,
  onClick,
}: RiskCardProps) {
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const normSev = severity.toLowerCase()

  return (
    <div className={`eng-risk-card card interactive-card risk-border-${normSev}`} onClick={onClick}>
      <div className="risk-card-head">
        <span className={`badge badge-${normSev}`}>{severity.toUpperCase()}</span>
        <span className="risk-category-tag">{category.toUpperCase()}</span>
        {location && <code className="risk-location" title={location}>{location}</code>}
      </div>
      <h4 className="risk-card-title">{title}</h4>

      <div className="risk-section-block">
        <span className="risk-sub-heading">WHY THIS MATTERS</span>
        <p className="risk-explanation">{whyItMatters}</p>
      </div>

      <div className="risk-section-block">
        <span className="risk-sub-heading">WHAT TO DO</span>
        <p className="risk-remediation">{whatToDo}</p>
      </div>

      {evidence && (
        <div className="risk-evidence-wrap">
          <button
            type="button"
            className="evidence-toggle-btn"
            onClick={e => {
              e.stopPropagation()
              setEvidenceOpen(v => !v)
            }}
            aria-expanded={evidenceOpen}
          >
            {evidenceOpen ? 'Hide evidence ▴' : 'View evidence ▾'}
          </button>
          {evidenceOpen && (
            <pre className="risk-evidence-box">
              <code>{evidence}</code>
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   3. CATEGORY / TAXONOMY CARD
   ========================================================================== */
export interface CategoryCardProps {
  category: string
  occurrences: number
  activeCount?: number
  resolvedCount?: number
  percentage: number
  isSelected?: boolean
  onClick?: () => void
}

export function CategoryCard({
  category,
  occurrences,
  activeCount,
  resolvedCount,
  percentage,
  isSelected = false,
  onClick,
}: CategoryCardProps) {
  return (
    <div
      className={`category-item-card card interactive-card ${isSelected ? 'selected' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.() } } : undefined}
    >
      <div className="category-card-top">
        <strong>{category}</strong>
        <span className="category-count">{occurrences} occurrences</span>
      </div>
      <div className="analytics-bar" role="img" aria-label={`${category}: ${percentage}%`}>
        <span style={{ width: `${Math.min(100, Math.max(0, percentage))}%` }} />
      </div>
      {(activeCount != null || resolvedCount != null) && (
        <div className="category-card-meta">
          {activeCount != null && <span className="text-warning">{activeCount} active</span>}
          {resolvedCount != null && <span className="text-success">{resolvedCount} resolved</span>}
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   4. MODEL INSIGHT CARD
   ========================================================================== */
export interface InsightCardProps {
  kicker: string
  title: string
  value?: string | number
  explanation: string
  disclaimer?: string
  icon?: React.ReactNode
}

export function InsightCard({
  kicker,
  title,
  value,
  explanation,
  disclaimer,
  icon,
}: InsightCardProps) {
  return (
    <div className="insight-card card interactive-card">
      <div className="insight-card-head">
        <span className="card-kicker">{kicker}</span>
        {icon && <span className="insight-icon" aria-hidden="true">{icon}</span>}
      </div>
      <h3 className="insight-title">{title}</h3>
      {value != null && <div className="insight-value">{value}</div>}
      <p className="insight-body">{explanation}</p>
      {disclaimer && <small className="insight-disclaimer">{disclaimer}</small>}
    </div>
  )
}

/* ==========================================================================
   5. CHART CARD
   ========================================================================== */
export interface ChartCardProps {
  title: string
  kicker?: string
  subtitle?: string
  legend?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}

export function ChartCard({
  title,
  kicker,
  subtitle,
  legend,
  actions,
  children,
  className = '',
}: ChartCardProps) {
  return (
    <div className={`eng-chart-card card ${className}`}>
      <div className="chart-card-header">
        <div>
          {kicker && <span className="card-kicker">{kicker}</span>}
          <h3 className="chart-card-title">{title}</h3>
          {subtitle && <p className="chart-card-sub">{subtitle}</p>}
        </div>
        {(legend || actions) && (
          <div className="chart-card-actions">
            {legend}
            {actions}
          </div>
        )}
      </div>
      <div className="chart-canvas-wrap">{children}</div>
    </div>
  )
}

/* ==========================================================================
   6. TIMELINE CARD
   ========================================================================== */
export interface TimelineItem {
  id: string | number
  timestamp: string
  title: string
  subtitle?: string
  tag?: string
  tagColor?: string
  icon?: React.ReactNode
}

export interface TimelineCardProps {
  title: string
  kicker?: string
  items: TimelineItem[]
  emptyMessage?: string
}

export function TimelineCard({
  title,
  kicker,
  items,
  emptyMessage = 'No timeline activity recorded yet.',
}: TimelineCardProps) {
  return (
    <div className="timeline-card card">
      <div className="section-heading">
        <div>
          {kicker && <span className="card-kicker">{kicker}</span>}
          <h3>{title}</h3>
        </div>
        <span className="count-label">{items.length} events</span>
      </div>
      {items.length === 0 ? (
        <p className="analytics-empty">{emptyMessage}</p>
      ) : (
        <ol className="activity-timeline-list">
          {items.map((item, idx) => (
            <li key={item.id || idx} className="activity-timeline-item">
              <span className="timeline-node" aria-hidden="true" />
              <div className="timeline-content">
                <div className="timeline-title-row">
                  <strong className="timeline-title">{item.title}</strong>
                  {item.tag && (
                    <span className={`badge badge-${item.tagColor || 'neutral'}`}>{item.tag}</span>
                  )}
                  <time className="timeline-time">{item.timestamp}</time>
                </div>
                {item.subtitle && <p className="timeline-sub">{item.subtitle}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/* ==========================================================================
   7. RECOMMENDATION CARD
   ========================================================================== */
export interface RecommendationCardProps {
  priorityRank: number
  severity: string
  category: string
  actionTitle: string
  reason: string
  location?: string | null
  onAction?: () => void
  actionLabel?: string
}

export function RecommendationCard({
  priorityRank,
  severity,
  category,
  actionTitle,
  reason,
  location,
  onAction,
  actionLabel = 'Review finding',
}: RecommendationCardProps) {
  const normSev = severity.toLowerCase()
  return (
    <div className="action-rank-card card interactive-card">
      <div className="action-rank-badge">
        <span className="rank-num">#{String(priorityRank).padStart(2, '0')}</span>
        <span className={`badge badge-${normSev}`}>{severity.toUpperCase()}</span>
        <span className="action-cat-pill">{category.toUpperCase()}</span>
      </div>
      <h4 className="action-title">{actionTitle}</h4>
      <p className="action-reason">{reason}</p>
      {location && (
        <div className="action-loc">
          <span>Scope: <code>{location}</code></span>
        </div>
      )}
      {onAction && (
        <div className="action-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onAction}>
            {actionLabel} <ArrowRightIcon size={12} className="inline ml-1" />
          </button>
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   8. PROJECT STATUS CARD
   ========================================================================== */
export interface ProjectStatusCardProps {
  projectName: string
  source: 'local' | 'github' | string
  branch?: string | null
  commitSha?: string | null
  monitoringStatus?: string
  lastChecked?: string | null
  reviewCount?: number
  onManage?: () => void
}

export function ProjectStatusCard({
  projectName,
  source,
  branch,
  commitSha,
  monitoringStatus = 'active',
  lastChecked,
  reviewCount,
  onManage,
}: ProjectStatusCardProps) {
  const isLive = monitoringStatus === 'active'
  return (
    <div className="project-status-card card interactive-card">
      <div className="project-status-head">
        <div>
          <span className="card-kicker">CONNECTED WORKSPACE</span>
          <h3 className="project-status-name">{projectName}</h3>
        </div>
        <div className={`live-monitoring-pill ${isLive ? 'live-active' : 'live-paused'}`}>
          <span className="pulse-indicator" aria-hidden="true" />
          <span>{isLive ? 'LIVE MONITORING' : 'MONITORING PAUSED'}</span>
        </div>
      </div>
      <div className="project-meta-pills">
        <span className="meta-chip">
          {source === 'github' ? <GithubIcon size={12} className="mr-1 inline" /> : <FolderIcon size={12} className="mr-1 inline" />}
          {source === 'github' ? 'GitHub' : 'Local'}
        </span>
        {branch && (
          <span className="meta-chip">
            <GitBranchIcon size={12} className="mr-1 inline text-primary" />
            <code>{branch}</code>
          </span>
        )}
        {commitSha && (
          <span className="meta-chip">
            <GitCommitIcon size={12} className="mr-1 inline text-muted" />
            <code>{commitSha.slice(0, 7)}</code>
          </span>
        )}
        {reviewCount != null && (
          <span className="meta-chip">
            <strong>{reviewCount}</strong> reviews recorded
          </span>
        )}
      </div>
      {lastChecked && (
        <span className="project-last-checked">Last synchronized: {lastChecked}</span>
      )}
      {onManage && (
        <div className="project-status-actions">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onManage}>
            Inspect Project
          </button>
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   9. REQUIREMENT CARD
   ========================================================================== */
export interface RequirementCardProps {
  requirementKey: string
  title: string
  priority?: string
  status: 'COVERED' | 'PARTIALLY_COVERED' | 'UNKNOWN' | string
  evidence: string
  implementationFiles?: string[]
  testFiles?: string[]
}

export function RequirementCard({
  requirementKey,
  title,
  priority,
  status,
  evidence,
  implementationFiles,
  testFiles,
}: RequirementCardProps) {
  const [open, setOpen] = useState(false)
  const normStatus = status.toUpperCase()
  const statusColor = normStatus === 'COVERED' ? 'success' : normStatus === 'PARTIALLY_COVERED' ? 'warning' : 'neutral'

  return (
    <div className="requirement-item-card card interactive-card">
      <div className="req-card-head">
        <div>
          <span className="req-key">{requirementKey}</span>
          {priority && <span className="req-priority">Priority {priority}</span>}
        </div>
        <span className={`badge badge-${statusColor}`}>{normStatus.replace('_', ' ')}</span>
      </div>
      <h4 className="req-title">{title}</h4>
      <p className="req-evidence">{evidence}</p>

      {((implementationFiles && implementationFiles.length > 0) || (testFiles && testFiles.length > 0)) && (
        <div className="req-expand-block">
          <button
            type="button"
            className="evidence-toggle-btn"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
          >
            {open ? 'Hide implementation mapping ▴' : 'Show implementation mapping ▾'}
          </button>
          {open && (
            <div className="req-files-grid">
              {implementationFiles && implementationFiles.length > 0 && (
                <div>
                  <strong>Implementation files:</strong>
                  <ul>
                    {implementationFiles.map(f => (
                      <li key={f}><code>{f}</code></li>
                    ))}
                  </ul>
                </div>
              )}
              {testFiles && testFiles.length > 0 && (
                <div>
                  <strong>Test files:</strong>
                  <ul>
                    {testFiles.map(f => (
                      <li key={f}><code>{f}</code></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   10. EMPTY STATE CARD
   ========================================================================== */
export interface EmptyStateCardProps {
  glyph?: React.ReactNode
  title: string
  description: string
  actionLabel?: string
  actionLink?: string
  onAction?: () => void
}

export function EmptyStateCard({
  glyph = '🔍',
  title,
  description,
  actionLabel,
  actionLink,
  onAction,
}: EmptyStateCardProps) {
  return (
    <div className="empty-state-card card">
      <div className="empty-state-content">
        <div className="empty-glyph" aria-hidden="true">{glyph}</div>
        <h3 className="empty-title">{title}</h3>
        <p className="empty-desc">{description}</p>
        {actionLabel && (
          actionLink ? (
            <a href={actionLink} className="button btn">
              {actionLabel} <ArrowRightIcon size={12} className="inline ml-1" />
            </a>
          ) : onAction ? (
            <button type="button" className="button btn" onClick={onAction}>
              {actionLabel} <ArrowRightIcon size={12} className="inline ml-1" />
            </button>
          ) : null
        )}
      </div>
    </div>
  )
}

/* ==========================================================================
   11. PREDICTION DISPLAY CARD
   ========================================================================== */
export interface PredictionDisplayCardProps {
  category: string
  probability: number
  confidence: number
  whyThisPrediction: string
  disclaimer?: string
  features?: Array<{ name: string; value: number; direction: string }>
}

export function PredictionDisplayCard({
  category,
  probability,
  confidence,
  whyThisPrediction,
  disclaimer = 'Prediction is based on historical project observations and current project state. It is not a certainty or causal estimate.',
  features,
}: PredictionDisplayCardProps) {
  const [showFeatures, setShowFeatures] = useState(false)
  const pct = Math.round(probability * 100)

  return (
    <div className="prediction-display-card card interactive-card">
      <div className="prediction-card-head">
        <span className="card-kicker">Apex-APR NEXT ISSUE FORECAST</span>
        <span className="badge badge-info">Confidence {Math.round(confidence * 100)}%</span>
      </div>
      <div className="prediction-main-row">
        <div>
          <span className="prediction-cat-label">Most likely next issue</span>
          <h2 className="prediction-cat-name">{category.toUpperCase()}</h2>
        </div>
        <div className="prediction-prob-badge">
          <strong>{pct}%</strong>
          <span>probability</span>
        </div>
      </div>

      <div className="analytics-bar prediction-bar" role="img" aria-label={`Forecast probability: ${pct}%`}>
        <span style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
      </div>

      <div className="prediction-rationale">
        <span className="risk-sub-heading">WHY THIS PREDICTION</span>
        <p>{whyThisPrediction}</p>
      </div>

      {features && features.length > 0 && (
        <div className="prediction-features-wrap">
          <button
            type="button"
            className="evidence-toggle-btn"
            onClick={() => setShowFeatures(v => !v)}
            aria-expanded={showFeatures}
          >
            {showFeatures ? 'Hide technical model features ▴' : 'Show technical model features ▾'}
          </button>
          {showFeatures && (
            <div className="features-table-wrap">
              <table className="features-table">
                <thead>
                  <tr>
                    <th>Feature</th>
                    <th>Value</th>
                    <th>Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {features.map(f => (
                    <tr key={f.name}>
                      <td><code>{f.name}</code></td>
                      <td>{typeof f.value === 'number' ? f.value.toFixed(3) : f.value}</td>
                      <td>{f.direction}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {disclaimer && <p className="prediction-disclaimer-note">{disclaimer}</p>}
    </div>
  )
}

/* ==========================================================================
   12. EVIDENCE CARD
   ========================================================================== */
export interface EvidenceCardProps {
  file?: string | null
  line?: number | null
  component?: string | null
  analyzer?: string | null
  evidence: string
  remediation?: string | null
}

export function EvidenceCard({
  file,
  line,
  component,
  analyzer,
  evidence,
  remediation,
}: EvidenceCardProps) {
  return (
    <div className="evidence-card card">
      <div className="evidence-card-head">
        {file && (
          <code className="evidence-filepath">
            {file}{line ? `:${line}` : ''}
          </code>
        )}
        {component && <span className="evidence-component-chip">{component}</span>}
        {analyzer && <span className="evidence-analyzer-chip">Analyzer: {analyzer}</span>}
      </div>
      <pre className="evidence-code-block">
        <code>{evidence}</code>
      </pre>
      {remediation && (
        <div className="evidence-remediation">
          <strong>Recommended remediation:</strong>
          <p>{remediation}</p>
        </div>
      )}
    </div>
  )
}
