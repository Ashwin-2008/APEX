import { GitBranchIcon, GitCommitIcon, FolderIcon, GithubIcon, ActivityIcon } from '../ui/Icons'

export interface MonitoringView {
  label: string
  modifier: string
  glyph: string
}

export function monitoringView(input: {
  sseState: string
  analyzing: boolean
  failed: boolean
  stopped: boolean
}): MonitoringView {
  if (input.failed) return { label: 'MONITORING ERROR', modifier: 'error', glyph: '⚠' }
  if (
    input.stopped ||
    input.sseState === 'DISCONNECTED' ||
    input.sseState === 'RECONNECTING' ||
    input.sseState === 'STOPPED'
  ) {
    return { label: 'MONITORING PAUSED', modifier: 'paused', glyph: '○' }
  }
  if (input.analyzing || input.sseState === 'CONNECTING') {
    return { label: 'ANALYZING CHANGES…', modifier: 'busy', glyph: '◐' }
  }
  return { label: 'LIVE MONITORING', modifier: 'live', glyph: '●' }
}

export interface ProjectHeaderProps {
  projectName: string
  source: 'local' | 'github'
  branch: string | null
  commitSha: string | null
  monitoring: MonitoringView
  lastChecked: string | null
  lastChange: string | null
  monitoringPaused: boolean
  stopping: boolean
  onStop: () => void
}

export function ProjectHeader({
  projectName,
  source,
  branch,
  commitSha,
  monitoring,
  lastChecked,
  lastChange,
  monitoringPaused,
  stopping,
  onStop,
}: ProjectHeaderProps) {
  const isLive = monitoring.modifier === 'live'
  const isBusy = monitoring.modifier === 'busy'
  const isError = monitoring.modifier === 'error'

  return (
    <header className="pr-header card">
      <div className="pr-header-main">
        <div className="pr-header-badge-row">
          <span className="eyebrow">Apex-APR</span>
          <span className="platform-tag">ENGINEERING OBSERVABILITY</span>
        </div>

        <div className="pr-header-title-row">
          <h1>{projectName}</h1>
        </div>

        <p className="pr-header-meta">
          Source: {source === 'github' ? 'GitHub' : 'Local folder'}
          <span aria-hidden="true" className="meta-sep"> · </span>Branch: <code>{branch || 'not available'}</code>
          <span aria-hidden="true" className="meta-sep"> · </span>Last commit: <code>{commitSha ? commitSha.slice(0, 7) : 'not available'}</code>
        </p>
      </div>

      <div className="pr-header-side">
        <div className="pr-monitor-badge-wrap">
          <p className={`pr-monitor pr-monitor-${monitoring.modifier}`}>
            <span className={`pr-monitor-glyph ${isLive ? 'pulse' : ''}`} aria-hidden="true">
              {monitoring.glyph}
            </span>
            <span>Monitoring: {monitoring.label}</span>
          </p>
        </div>

        <dl className="pr-monitor-detail">
          <div>
            <dt>Last checked</dt>
            <dd>{lastChecked || 'Not yet'}</dd>
          </div>
          <div>
            <dt>Last change</dt>
            <dd><code>{lastChange || 'None reported'}</code></dd>
          </div>
        </dl>

        <div className="pr-header-actions">
          <button
            type="button"
            className="button button-secondary pr-stop"
            onClick={onStop}
            disabled={monitoringPaused || stopping}
          >
            {stopping ? 'Stopping…' : monitoringPaused ? 'Monitoring stopped' : 'Stop Monitoring'}
          </button>
        </div>
      </div>
    </header>
  )
}