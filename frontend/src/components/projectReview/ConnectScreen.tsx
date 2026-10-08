import type { ReactNode } from 'react'

export interface ConnectScreenProps {
  source: 'local' | 'github'
  value: string
  connecting: boolean
  error: string
  onSourceChange: (source: 'local' | 'github') => void
  onValueChange: (value: string) => void
  onConnect: () => void
}

export function ConnectScreen({ source, value, connecting, error, onSourceChange, onValueChange, onConnect }: ConnectScreenProps) {
  const options: Array<{ key: 'local' | 'github'; title: string; blurb: ReactNode }> = [
    { key: 'local', title: 'Local Project', blurb: 'Connect a folder from this computer.' },
    { key: 'github', title: 'GitHub', blurb: 'Connect a repository.' },
  ]
  return (
    <div className="pr-connect">
      <div className="pr-connect-copy">
        <span className="eyebrow">MISTIQ-APR</span>
        <h1>CONNECT YOUR PROJECT</h1>
        <p>Connect once, then MISTIQ watches meaningful development changes, analyzes them, and shows what changed and what to fix.</p>
        <h2>How do you want to connect?</h2>
        <div className="pr-connect-choices">
          {options.map(option => (
            <button
              key={option.key}
              type="button"
              className={`pr-choice${source === option.key ? ' active' : ''}`}
              aria-pressed={source === option.key}
              onClick={() => { onSourceChange(option.key); onValueChange('') }}
            >
              <strong>{option.title}</strong>
              <span>{option.blurb}</span>
            </button>
          ))}
        </div>
      </div>
      <section className="card pr-connect-card" aria-label={source === 'local' ? 'Local project connection' : 'GitHub repository connection'}>
        <span className="card-kicker">{source === 'local' ? 'Local project' : 'GitHub'}</span>
        <h2>{source === 'local' ? 'Connect a folder from this computer' : 'Connect a GitHub repository'}</h2>
        <label htmlFor="connect-value">{source === 'local' ? 'Project path' : 'Repository URL'}</label>
        <input
          id="connect-value"
          value={value}
          onChange={event => onValueChange(event.target.value)}
          placeholder={source === 'local' ? 'C:\\projects\\my-app' : 'https://github.com/user/repository'}
          onKeyDown={event => event.key === 'Enter' && !connecting && value.trim() && onConnect()}
        />
        {error && <div className="pr-error" role="alert">{error}</div>}
        <button className="button" disabled={!value.trim() || connecting} onClick={onConnect}>
          {connecting ? 'Connecting…' : source === 'local' ? 'Connect Project' : 'Connect Repository'}
        </button>
        {connecting && (
          <ol className="pr-connect-progress" aria-live="polite">
            <li>Connecting…</li>
            <li>Analyzing project…</li>
            <li>Monitoring active.</li>
          </ol>
        )}
        <p className="live-note">MISTIQ analyzes deterministic evidence first. Monitoring starts after the initial analysis.</p>
      </section>
    </div>
  )
}