import type { ActivityEntry } from '../../utils/labels'
import { GitCommitIcon, ActivityIcon, CheckCircleIcon, AlertTriangleIcon, ZapIcon } from '../ui/Icons'

function getEventIcon(message: string) {
  const m = message.toLowerCase()
  if (m.includes('resolved')) return CheckCircleIcon
  if (m.includes('critical') || m.includes('high') || m.includes('new')) return AlertTriangleIcon
  if (m.includes('commit') || m.includes('files changed') || m.includes('project changed')) return GitCommitIcon
  if (m.includes('prediction') || m.includes('profile')) return ZapIcon
  return ActivityIcon
}

function getEventBadge(message: string) {
  const m = message.toLowerCase()
  if (m.includes('resolved')) return { label: 'RESOLVED', cls: 'badge-resolved' }
  if (m.includes('critical')) return { label: 'CRITICAL', cls: 'badge-critical' }
  if (m.includes('high')) return { label: 'HIGH', cls: 'badge-high' }
  if (m.includes('medium')) return { label: 'MEDIUM', cls: 'badge-medium' }
  if (m.includes('analyzing') || m.includes('started')) return { label: 'ANALYZING', cls: 'badge-busy' }
  if (m.includes('completed') || m.includes('finished')) return { label: 'COMPLETED', cls: 'badge-success' }
  if (m.includes('prediction')) return { label: 'PREDICTION', cls: 'badge-info' }
  return { label: 'EVENT', cls: 'badge-neutral' }
}

export function ActivityFeed({ entries }: { entries: ActivityEntry[] }) {
  return (
    <section className="card pr-activity" aria-label="What changed">
      <div className="pr-section-header-row">
        <div>
          <h2>WHAT CHANGED?</h2>
          <p className="pr-section-note">A clear history of meaningful development events</p>
        </div>
        <div className="activity-live-indicator">
          <span className="live-dot-pulse" aria-hidden="true" />
          <span>Real-time event feed</span>
        </div>
      </div>

      {entries.length ? (
        <ol className="pr-activity-list" aria-label="What changed">
          {entries.map(entry => {
            const Icon = getEventIcon(entry.message)
            const badge = getEventBadge(entry.message)
            return (
              <li key={entry.key} className="pr-activity-item">
                <div className="activity-item-left">
                  <div className="activity-timeline-line" aria-hidden="true" />
                  <div className={`activity-icon-bubble ${badge.cls}`} aria-hidden="true">
                    <Icon size={13} />
                  </div>
                </div>

                <div className="activity-item-content">
                  <div className="activity-meta-row">
                    <span className={`activity-tag ${badge.cls}`}>{badge.label}</span>
                    <time dateTime={entry.time.toISOString()} title={entry.time.toLocaleString()}>
                      {entry.time.toLocaleTimeString()}
                    </time>
                  </div>

                  <span className="pr-activity-message">{entry.message}</span>

                  {entry.file && (
                    <div className="activity-file-row">
                      <code className="pr-activity-file">{entry.file}</code>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="pr-empty">
          No project activity has been observed yet. Save a file to see the first event.
        </p>
      )}
    </section>
  )
}