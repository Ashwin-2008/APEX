import type { ReactNode } from 'react'
import { FolderIcon, GithubIcon, ShieldIcon, ActivityIcon, CheckCircleIcon, ZapIcon } from '../ui/Icons'

export interface ConnectScreenProps {
  source: 'local' | 'github'
  value: string
  connecting: boolean
  error: string
  onSourceChange: (source: 'local' | 'github') => void
  onValueChange: (value: string) => void
  onConnect: () => void
}

export function ConnectScreen({
  source,
  value,
  connecting,
  error,
  onSourceChange,
  onValueChange,
  onConnect,
}: ConnectScreenProps) {
  const options: Array<{
    key: 'local' | 'github'
    title: string
    blurb: ReactNode
    icon: typeof FolderIcon
  }> = [
    {
      key: 'local',
      title: 'Local Project',
      blurb: 'Connect a folder from this computer.',
      icon: FolderIcon,
    },
    {
      key: 'github',
      title: 'GitHub',
      blurb: 'Connect a repository.',
      icon: GithubIcon,
    },
  ]

  const pipelineSteps = [
    { num: '①', label: 'Connected', desc: 'Repository or directory mounted', done: connecting },
    { num: '②', label: 'Analyzing', desc: 'Deterministic scanners executing', done: connecting },
    { num: '③', label: 'Building profile', desc: 'Failure DNA & history indexing', done: false },
    { num: '④', label: 'Monitoring enabled', desc: 'Live SSE event stream active', done: false },
  ]

  return (
    <div className="pr-connect-wrapper">
      <div className="pr-connect-hero">
        <div className="pr-connect-badge">
          <ZapIcon size={12} className="inline mr-1 text-primary" />
          <span>MISTIQ-APR 2.0</span>
        </div>
        <h1>CONNECT YOUR PROJECT</h1>
        <p className="pr-connect-tagline">
          Continuous engineering intelligence for local repositories and GitHub projects. Connect once to observe code evolution, detect active findings, and predict failure patterns in real-time.
        </p>
      </div>

      <div className="pr-connect-container">
        {/* Source Chooser & Input Form */}
        <div className="pr-connect-main-card card">
          <div className="pr-connect-section-header">
            <span className="eyebrow">CHOOSE SOURCE</span>
            <h2>How do you want to connect?</h2>
          </div>

          <div className="pr-connect-choices" role="radiogroup" aria-label="Connection source">
            {options.map(option => {
              const Icon = option.icon
              const isSelected = source === option.key
              return (
                <button
                  key={option.key}
                  type="button"
                  className={`pr-choice-card ${isSelected ? 'active' : ''}`}
                  aria-pressed={isSelected}
                  onClick={() => {
                    onSourceChange(option.key)
                    onValueChange('')
                  }}
                >
                  <div className="choice-icon-wrap">
                    <Icon size={20} />
                  </div>
                  <div className="choice-text">
                    <strong>{option.title}</strong>
                    <span>{option.blurb}</span>
                  </div>
                  {isSelected && <span className="choice-check-badge">✓</span>}
                </button>
              )
            })}
          </div>

          <div
            className="pr-connect-input-box"
            aria-label={source === 'local' ? 'Local project connection' : 'GitHub repository connection'}
          >
            <div className="input-group">
              <label htmlFor="connect-value">
                {source === 'local' ? 'Project path' : 'Repository URL'}
              </label>
              <div className="input-with-icon">
                <span className="input-affix-icon" aria-hidden="true">
                  {source === 'local' ? <FolderIcon size={16} /> : <GithubIcon size={16} />}
                </span>
                <input
                  id="connect-value"
                  value={value}
                  onChange={event => onValueChange(event.target.value)}
                  placeholder={
                    source === 'local'
                      ? 'C:\\projects\\my-app or /home/dev/repo'
                      : 'https://github.com/org/repository'
                  }
                  onKeyDown={event =>
                    event.key === 'Enter' && !connecting && value.trim() && onConnect()
                  }
                  disabled={connecting}
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
            </div>

            {error && (
              <div className="pr-error" role="alert">
                {error}
              </div>
            )}

            <div className="pr-connect-actions">
              <button
                type="button"
                className="button connect-submit-btn"
                disabled={!value.trim() || connecting}
                onClick={onConnect}
              >
                {connecting ? (
                  <>
                    <span className="loading-spinner-sm" aria-hidden="true" />
                    Connecting…
                  </>
                ) : source === 'local' ? (
                  'Connect Project'
                ) : (
                  'Connect Repository'
                )}
              </button>
            </div>

            {connecting && (
              <ol className="pr-connect-progress" aria-live="polite">
                <li>Connecting…</li>
                <li>Analyzing project…</li>
                <li>Monitoring active.</li>
              </ol>
            )}

            <p className="live-note">
              <ShieldIcon size={13} className="inline mr-1 text-primary" />
              MISTIQ analyzes deterministic evidence first. Monitoring starts automatically after the initial analysis completes.
            </p>
          </div>
        </div>

        {/* ANALYSIS PIPELINE SIDEBAR */}
        <div className="pr-connect-side-card card">
          <div className="pr-pipeline-header">
            <span className="eyebrow">OBSERVABILITY WORKFLOW</span>
            <h3>ANALYSIS PIPELINE</h3>
            <p className="text-muted text-xs">Deterministic multi-pass inspection</p>
          </div>

          <div className="pipeline-steps-timeline">
            {pipelineSteps.map((step, idx) => (
              <div
                key={step.num}
                className={`pipeline-step-item ${connecting && idx < 2 ? 'step-active' : ''}`}
              >
                <div className="step-badge">{step.num}</div>
                <div className="step-content">
                  <strong>{step.label}</strong>
                  <p>{step.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="pipeline-specs-box">
            <h4>Analyzers Running</h4>
            <div className="specs-tag-list">
              <span className="spec-tag">Secret Detector</span>
              <span className="spec-tag">Test Inventory</span>
              <span className="spec-tag">Dependencies</span>
              <span className="spec-tag">Git Churn</span>
              <span className="spec-tag">Requirements</span>
              <span className="spec-tag">Failure DNA</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}