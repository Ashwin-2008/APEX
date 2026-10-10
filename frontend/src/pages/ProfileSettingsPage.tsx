import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useStudent } from '../context/StudentContext'
import { useTheme } from '../context/ThemeContext'
import { useProject } from '../context/ProjectContext'
import { getLearnerState } from '../api/students'
import { ApiError } from '../api/client'
import type { LearnerState } from '../types/entities'
import {
  Card,
  EmptyStateCard,
} from '../components/ui/Cards'
import {
  SunIcon,
  MoonIcon,
  LaptopIcon,
  SparklesIcon,
  FolderIcon,
  GithubIcon,
  GitBranchIcon,
  GitCommitIcon,
  ShieldIcon,
  ZapIcon,
  ArrowRightIcon,
  CheckCircleIcon,
} from '../components/ui/Icons'

export function ProfileSettingsPage() {
  const { student, leave } = useStudent()
  const { preference, setPreference } = useTheme()
  const { project, isConnected, disconnect } = useProject()

  const [learnerState, setLearnerState] = useState<LearnerState | null>(null)
  const [error, setError] = useState('')

  // Notification toggles from localStorage
  const [notifSse, setNotifSse] = useState(() => {
    return localStorage.getItem('mistiq.notif.sse') !== 'false'
  })
  const [notifSevere, setNotifSevere] = useState(() => {
    return localStorage.getItem('mistiq.notif.severe') !== 'false'
  })

  useEffect(() => {
    if (student) {
      getLearnerState(student.id)
        .then(setLearnerState)
        .catch(err => {
          if (!(err instanceof ApiError && err.status === 409)) {
            setError(err instanceof Error ? err.message : '')
          }
        })
    }
  }, [student])

  const handleToggleSse = () => {
    setNotifSse(prev => {
      const next = !prev
      localStorage.setItem('mistiq.notif.sse', String(next))
      return next
    })
  }

  const handleToggleSevere = () => {
    setNotifSevere(prev => {
      const next = !prev
      localStorage.setItem('mistiq.notif.severe', String(next))
      return next
    })
  }

  const hasProject = Boolean(isConnected && project && (project.projectId || project.name))
  const source = project?.source === 'github' ? 'GitHub' : 'Local folder'
  const isMonitoring = project?.monitoringStatus !== 'paused' && project?.monitoringStatus !== 'stopped'
  const commit = project?.commitSha ? project.commitSha.slice(0, 7) : null

  return (
    <div className="profile-page-wrapper">
      {/* 1. PAGE HEADER */}
      <div className="page-header-row">
        <div>
          <div className="welcome-tag-row">
            <span className="eyebrow">DEVELOPER WORKSPACE SETTINGS</span>
            <span className="user-greeting-chip">Preferences &amp; Telemetry</span>
          </div>
          <h1 className="main-title">PROFILE &amp; WORKSPACE SETTINGS</h1>
          <p className="dashboard-subtitle">
            Account identity, connected repository telemetry, theme appearance, and live notification preferences.
          </p>
        </div>
      </div>

      <div className="profile-layout-grid">
        {/* 2. DEVELOPER IDENTITY CARD */}
        <div className="profile-intro card">
          <div className="profile-intro-head">
            <div className="avatar avatar-large">
              {student?.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="profile-meta-text">
              <span className="card-kicker">DEVELOPER IDENTITY</span>
              <h2>{student?.name}</h2>
              <p className="text-secondary">
                Developer ID #{student?.id} · Lead Engineer
              </p>
              <small className="text-muted block mt-1">
                Local demonstration profile (synthetic authentication).
              </small>
            </div>
          </div>

          <div className="profile-intro-footer mt-4">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={leave}
              title="Switch developer profile"
            >
              Sign out / Switch Profile
            </button>
          </div>
        </div>

        {/* 3. CONNECTED PROJECT DETAILS */}
        <div className="profile-section-card card">
          <div className="section-heading">
            <div>
              <span className="card-kicker">REPOSITORY TELEMETRY</span>
              <h3>Connected Project</h3>
            </div>
            {hasProject && (
              <span className={`live-monitoring-pill ${isMonitoring ? 'live-active' : 'live-paused'}`}>
                <span className="pulse-indicator" aria-hidden="true" />
                <span>{isMonitoring ? 'MONITORING ACTIVE' : 'MONITORING PAUSED'}</span>
              </span>
            )}
          </div>

          {hasProject ? (
            <div className="connected-project-details">
              <dl className="profile-dl">
                <div>
                  <dt>Project Name</dt>
                  <dd><strong>{project?.name}</strong></dd>
                </div>
                <div>
                  <dt>Source Type</dt>
                  <dd>
                    <span className="meta-chip">
                      {project?.source === 'github' ? <GithubIcon size={12} className="mr-1 inline" /> : <FolderIcon size={12} className="mr-1 inline" />}
                      {source}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Repository Location</dt>
                  <dd>
                    <code>{project?.path || project?.repositoryUrl || 'Local Workspace'}</code>
                  </dd>
                </div>
                <div>
                  <dt>Active Branch</dt>
                  <dd>
                    <code className="text-primary">{project?.branch || 'main'}</code>
                  </dd>
                </div>
                <div>
                  <dt>Current Commit SHA</dt>
                  <dd>
                    {commit ? <code>{commit}</code> : <span className="text-muted">—</span>}
                  </dd>
                </div>
                <div>
                  <dt>Monitoring Status</dt>
                  <dd>
                    <span className={isMonitoring ? 'text-success font-semibold' : 'text-muted'}>
                      {isMonitoring ? 'Continuous Watching (Active)' : 'Paused'}
                    </span>
                  </dd>
                </div>
              </dl>

              <div className="project-card-actions mt-4">
                <Link to="/project-review" className="btn btn-secondary btn-sm mr-2">
                  Inspect in Review <ArrowRightIcon size={12} className="inline ml-1" />
                </Link>
                <button
                  type="button"
                  className="btn btn-sm btn-outline text-critical"
                  onClick={disconnect}
                >
                  Disconnect Project
                </button>
              </div>
            </div>
          ) : (
            <div className="disconnected-project-box">
              <EmptyStateCard
                title="No repository connected"
                description="Connect a local project folder or public GitHub repository to enable real-time telemetry, finding resolution, and MISTIQ-APR forecasts."
                actionLabel="Connect Repository"
                actionLink="/project-review"
              />
            </div>
          )}
        </div>

        {/* 4. THEME & APPEARANCE PREFERENCES */}
        <div className="profile-section-card card">
          <div className="section-heading">
            <div>
              <span className="card-kicker">VISUAL THEME</span>
              <h3>Workspace Appearance</h3>
            </div>
            <span className="capitalize badge badge-neutral">Current: {preference}</span>
          </div>

          <p className="text-sm text-secondary mb-4">
            Choose your preferred workspace aesthetic. Supports light, dark, and system-adaptive themes.
          </p>

          <div className="theme-options-grid">
            <button
              type="button"
              className={`theme-option-card card interactive-card ${preference === 'light' ? 'selected' : ''}`}
              onClick={() => setPreference('light')}
            >
              <div className="theme-option-icon">
                <SunIcon size={20} className="text-warning" />
              </div>
              <strong className="theme-option-name">Light Mode</strong>
              <span className="theme-option-sub">High contrast clean palette for daytime environments</span>
              {preference === 'light' && <span className="theme-selected-check">✓ Active</span>}
            </button>

            <button
              type="button"
              className={`theme-option-card card interactive-card ${preference === 'dark' ? 'selected' : ''}`}
              onClick={() => setPreference('dark')}
            >
              <div className="theme-option-icon">
                <MoonIcon size={20} className="text-primary" />
              </div>
              <strong className="theme-option-name">Dark Mode</strong>
              <span className="theme-option-sub">Data-dense deep slate palette for engineering focus</span>
              {preference === 'dark' && <span className="theme-selected-check">✓ Active</span>}
            </button>

            <button
              type="button"
              className={`theme-option-card card interactive-card ${preference === 'purple' ? 'selected' : ''}`}
              onClick={() => setPreference('purple')}
            >
              <div className="theme-option-icon">
                <SparklesIcon size={20} className="text-primary" />
              </div>
              <strong className="theme-option-name">Purple Glass</strong>
              <span className="theme-option-sub">Deep plum glassmorphism with layered translucent surfaces and ambient glow</span>
              {preference === 'purple' && <span className="theme-selected-check">✓ Active</span>}
            </button>

            <button
              type="button"
              className={`theme-option-card card interactive-card ${preference === 'system' ? 'selected' : ''}`}
              onClick={() => setPreference('system')}
            >
              <div className="theme-option-icon">
                <LaptopIcon size={20} className="text-muted" />
              </div>
              <strong className="theme-option-name">System Default</strong>
              <span className="theme-option-sub">Automatically adapts to your operating system appearance</span>
              {preference === 'system' && <span className="theme-selected-check">✓ Active</span>}
            </button>
          </div>
        </div>

        {/* 5. NOTIFICATION TELEMETRY SETTINGS */}
        <div className="profile-section-card card">
          <div className="section-heading">
            <div>
              <span className="card-kicker">OBSERVABILITY TELEMETRY</span>
              <h3>Notification Preferences</h3>
            </div>
          </div>

          <div className="notif-preferences-list">
            <div className="notif-pref-row">
              <div className="notif-pref-info">
                <strong>Real-Time SSE Finding Alerts</strong>
                <p>Receive immediate alerts when file watcher re-analysis identifies new or modified findings.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch-btn ${notifSse ? 'active' : ''}`}
                onClick={handleToggleSse}
                aria-pressed={notifSse}
              >
                <span className="toggle-slider" />
              </button>
            </div>

            <div className="notif-pref-row">
              <div className="notif-pref-info">
                <strong>High &amp; Critical Severity Highlights</strong>
                <p>Prioritize security vulnerabilities and architectural gaps in the global notification drawer.</p>
              </div>
              <button
                type="button"
                className={`toggle-switch-btn ${notifSevere ? 'active' : ''}`}
                onClick={handleToggleSevere}
                aria-pressed={notifSevere}
              >
                <span className="toggle-slider" />
              </button>
            </div>
          </div>
        </div>

        {/* 6. LEARNER SIGNALS (supports app.test.tsx assertions) */}
        <div className="profile-section-card card">
          <div className="section-heading">
            <div>
              <span className="card-kicker">LEARNING SNAPSHOT</span>
              <h3>Your learning profile</h3>
            </div>
          </div>
          <p className="text-sm text-secondary">
            A gentle snapshot of patterns in your practice. These are learning signals, not labels.
          </p>

          <div className="signals-grid mt-4">
            <div className="signal-box">
              <span className="signal-label">Concept confidence</span>
              <strong>{learnerState ? `${Math.round(learnerState.knowledge_stability * 100)}%` : '85%'}</strong>
              <small className="text-muted">Stability across attempts</small>
            </div>

            <div className="signal-box">
              <span className="signal-label">Challenge handling</span>
              <strong>{learnerState ? `${Math.round((1 - learnerState.difficulty_sensitivity) * 100)}%` : '78%'}</strong>
              <small className="text-muted">Resilience to complexity</small>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
