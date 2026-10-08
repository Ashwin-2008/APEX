export interface MonitoringView {
  label: string
  modifier: string
  glyph: string
}

export function monitoringView(input: { sseState: string; analyzing: boolean; failed: boolean; stopped: boolean }): MonitoringView {
  if (input.failed) return { label: 'MONITORING ERROR', modifier: 'error', glyph: '⚠' }
  if (input.stopped || input.sseState === 'DISCONNECTED' || input.sseState === 'RECONNECTING' || input.sseState === 'STOPPED') {
    return { label: 'MONITORING PAUSED', modifier: 'paused', glyph: '○' }
  }
  if (input.analyzing || input.sseState === 'CONNECTING') return { label: 'ANALYZING CHANGES…', modifier: 'busy', glyph: '◌' }
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

export function ProjectHeader({ projectName, source, branch, commitSha, monitoring, lastChecked, lastChange, monitoringPaused, stopping, onStop }: ProjectHeaderProps) {
  return (
    <header className="pr-header">
      <div className="pr-header-main">
        <span className="eyebrow">MISTIQ-APR</span>
        <h1>{projectName}</h1>
        <p className="pr-header-meta">
          Source: {source === 'github' ? 'GitHub' : 'Local folder'}
          <span aria-hidden="true"> · </span>Branch: <code>{branch || 'not available'}</code>
          <span aria-hidden="true"> · </span>Last commit: <code>{commitSha ? commitSha.slice(0, 7) : 'not available'}</code>
        </p>
      </div>
      <div className="pr-header-side">
        <p className={`pr-monitor pr-monitor-${monitoring.modifier}`}>
          <span className="pr-monitor-glyph" aria-hidden="true">{monitoring.glyph}</span>
          <span>Monitoring: {monitoring.label}</span>
        </p>
        <dl className="pr-monitor-detail">
          <dt>Last checked</dt>
          <dd>{lastChecked || 'Not yet'}</dd>
          <dt>Last change</dt>
          <dd><code>{lastChange || 'None reported'}</code></dd>
        </dl>
        <button type="button" className="button pr-stop" onClick={onStop} disabled={monitoringPaused || stopping}>
          {stopping ? 'Stopping…' : monitoringPaused ? 'Monitoring stopped' : 'Stop Monitoring'}
        </button>
      </div>
    </header>
  )
}