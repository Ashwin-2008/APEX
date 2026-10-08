import type { ActivityEntry } from '../../utils/labels'

export function ActivityFeed({ entries }: { entries: ActivityEntry[] }) {
  return (
    <section className="card pr-activity" aria-label="What changed">
      <h2>WHAT CHANGED?</h2>
      <p className="pr-section-note">A clear history of meaningful development events</p>
      {entries.length ? (
        <ol className="pr-activity-list" aria-label="What changed">
          {entries.map(entry => (
            <li key={entry.key}>
              <time dateTime={entry.time.toISOString()}>{entry.time.toLocaleTimeString()}</time>
              <span className="pr-activity-message">{entry.message}</span>
              {entry.file && <code className="pr-activity-file">{entry.file}</code>}
            </li>
          ))}
        </ol>
      ) : (
        <p className="pr-empty">No project activity has been observed yet. Save a file to see the first event.</p>
      )}
    </section>
  )
}