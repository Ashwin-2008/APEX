import { useEffect, useState } from 'react'
import { NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useStudent } from '../context/StudentContext'
import { useTheme } from '../context/ThemeContext'
import { useProject } from '../context/ProjectContext'
import { LoadingState } from '../components'
import { NotificationCenter } from '../components/NotificationCenter'
import { getProjectNotifications } from '../utils/projectNotifications'
import {
  DashboardIcon,
  ProjectReviewIcon,
  EvolutionIcon,
  FailuresIcon,
  ResearchIcon,
  SunIcon,
  MoonIcon,
  LaptopIcon,
  SparklesIcon,
  UserIcon,
  GitBranchIcon,
  GitCommitIcon,
  FolderIcon,
  GithubIcon,
  BellIcon,
  ZapIcon,
} from '../components/ui/Icons'

export function AppLayout() {
  const { student, ready, leave } = useStudent()
  const { preference, setPreference } = useTheme()
  const { project, isConnected } = useProject()
  const location = useLocation()

  const [headerThemeDropdown, setHeaderThemeDropdown] = useState(false)
  const [sidebarThemeDropdown, setSidebarThemeDropdown] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [notifCount, setNotifCount] = useState<number>(() => {
    return getProjectNotifications().filter(item => !item.seen).length
  })

  useEffect(() => {
    const handleStorage = () => {
      setNotifCount(getProjectNotifications().filter(item => !item.seen).length)
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  if (!ready) return <LoadingState label="Restoring engineering workspace…" />
  if (!student) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  const hasConnectedProject = Boolean(isConnected && project && project.name)
  const projectName = project?.name || ''
  const source = project?.source === 'github' ? 'GitHub' : 'Local'
  const branch = project?.branch || 'main'
  const commit = project?.commitSha ? project.commitSha.slice(0, 7) : null
  const isMonitoring = project?.monitoringStatus !== 'paused' && project?.monitoringStatus !== 'stopped'

  const workspaceLinks = [
    { to: '/dashboard', label: 'Dashboard', icon: DashboardIcon },
    { to: '/project-review', label: 'Project Review', icon: ProjectReviewIcon },
    { to: '/progress', label: 'Project Evolution', icon: EvolutionIcon },
    { to: '/mistakes', label: 'Engineering Failures', icon: FailuresIcon },
  ]

  return (
    <div className="app-shell">
      {/* GLOBAL FULL-WIDTH TOP HEADER */}
      <header className="global-header" aria-label="Platform header">
        <div className="global-header-left">
          <NavLink className="header-brand" to="/dashboard">
            <span className="brand-logo-gem">M</span>
            <span className="brand-title">MISTIQ</span>
            <span className="brand-badge">2.0</span>
          </NavLink>
          <div className="header-sub-tag">ENGINEERING INTELLIGENCE</div>
        </div>

        {/* CENTER: PROJECT TELEMETRY (ONLY AFTER SUCCESSFUL CONNECTION) */}
        <div className="global-header-center">
          {hasConnectedProject ? (
            <div className="header-project-info" title={`Repository: ${projectName}`}>
              <span className="header-project-name">{projectName}</span>
              <div className="header-meta-chips">
                <span className="meta-chip">
                  {source === 'GitHub' ? (
                    <GithubIcon size={11} className="mr-1 inline" />
                  ) : (
                    <FolderIcon size={11} className="mr-1 inline" />
                  )}
                  {source}
                </span>
                <span className="meta-chip meta-chip-branch" title={`Branch: ${branch}`}>
                  <GitBranchIcon size={11} className="mr-1 inline text-primary" />
                  <code>{branch}</code>
                </span>
                {commit && (
                  <span className="meta-chip meta-chip-commit" title={`Commit: ${commit}`}>
                    <GitCommitIcon size={11} className="mr-1 inline text-muted" />
                    <code>{commit}</code>
                  </span>
                )}
              </div>
              <div className={`live-monitoring-pill ${isMonitoring ? 'live-active' : 'live-paused'}`}>
                <span className="pulse-indicator" aria-hidden="true" />
                <span>{isMonitoring ? 'LIVE MONITORING' : 'MONITORING PAUSED'}</span>
              </div>
            </div>
          ) : (
            <div className="header-no-project">
              <NavLink to="/project-review" className="header-connect-prompt">
                <ZapIcon size={12} className="inline mr-1 text-primary" />
                <span>Connect repository to begin engineering analysis</span>
              </NavLink>
            </div>
          )}
        </div>

        {/* RIGHT: NOTIFICATIONS, THEME, USER PROFILE */}
        <div className="global-header-right">
          <NotificationCenter
            isOpen={notifOpen}
            onToggle={() => setNotifOpen(v => !v)}
            onClose={() => setNotifOpen(false)}
          />

          <div className="relative theme-picker-wrap">
            <button
              type="button"
              className="header-icon-button theme-toggle"
              aria-label={`Theme: ${preference}`}
              onClick={() => setHeaderThemeDropdown(v => !v)}
              title={`Theme: ${preference} mode`}
            >
              {preference === 'purple' ? (
                <SparklesIcon size={15} />
              ) : preference === 'dark' ? (
                <MoonIcon size={15} />
              ) : preference === 'light' ? (
                <SunIcon size={15} />
              ) : (
                <LaptopIcon size={15} />
              )}
            </button>

            {headerThemeDropdown && (
              <div className="theme-dropdown-menu">
                {(['purple', 'dark', 'light', 'system'] as const).map(t => (
                  <button
                    key={t}
                    type="button"
                    className={`theme-dropdown-item ${preference === t ? 'active' : ''}`}
                    onClick={() => {
                      setPreference(t)
                      setHeaderThemeDropdown(false)
                    }}
                  >
                    {t === 'purple' && <SparklesIcon size={13} className="inline mr-2" />}
                    {t === 'light' && <SunIcon size={13} className="inline mr-2" />}
                    {t === 'dark' && <MoonIcon size={13} className="inline mr-2" />}
                    {t === 'system' && <LaptopIcon size={13} className="inline mr-2" />}
                    <span className="capitalize">{t === 'purple' ? 'Purple Glass' : `${t} Mode`}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <NavLink
            className="profile-link"
            to="/profile"
            aria-label="Developer Profile"
            title="View Developer Profile"
          >
            <span className="header-avatar">{student.name.slice(0, 1).toUpperCase()}</span>
            <span className="header-username">{student.name}</span>
          </NavLink>
        </div>
      </header>

      {/* APPLICATION BODY (SIDEBAR + MAIN CONTENT) */}
      <div className="app-body">
        {/* DEVELOPER SIDEBAR */}
        <aside className="sidebar" aria-label="Sidebar navigation">
          <div className="sidebar-nav-section">
            <span className="sidebar-label">WORKSPACE</span>
            <nav aria-label="Main navigation" className="sidebar-nav">
              {workspaceLinks.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
                >
                  <span className="nav-icon" aria-hidden="true">
                    <Icon size={16} />
                  </span>
                  <span className="nav-label">{label}</span>
                </NavLink>
              ))}
            </nav>
          </div>

          <div className="sidebar-nav-section research-nav">
            <span className="sidebar-label">EXPLORE</span>
            <nav aria-label="Explore navigation" className="sidebar-nav">
              <NavLink
                to="/project-review/research-lab"
                className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
              >
                <span className="nav-icon" aria-hidden="true">
                  <ResearchIcon size={16} />
                </span>
                <span className="nav-label">Research Lab</span>
              </NavLink>
            </nav>
          </div>

          <div className="sidebar-footer">
            {/* DEDICATED NOTIFICATIONS BUTTON IN SIDEBAR */}
            <button
              type="button"
              className={`sidebar-nav-item sidebar-notif-btn ${notifOpen ? 'active' : ''}`}
              onClick={() => setNotifOpen(v => !v)}
              aria-label="Open notifications"
            >
              <span className="nav-icon">
                <BellIcon size={16} />
              </span>
              <span className="nav-label">Notifications</span>
              {notifCount > 0 && <span className="sidebar-badge">{notifCount}</span>}
            </button>

            {/* DEDICATED THEME APPEARANCE PICKER IN SIDEBAR */}
            <div className="sidebar-theme-item">
              <button
                type="button"
                className="sidebar-nav-item sidebar-theme-toggle"
                onClick={() => setSidebarThemeDropdown(v => !v)}
                aria-label={`Switch theme appearance (currently ${preference})`}
              >
                <span className="nav-icon">
                  {preference === 'purple' ? (
                    <SparklesIcon size={16} />
                  ) : preference === 'dark' ? (
                    <MoonIcon size={16} />
                  ) : preference === 'light' ? (
                    <SunIcon size={16} />
                  ) : (
                    <LaptopIcon size={16} />
                  )}
                </span>
                <span className="nav-label">Appearance</span>
                <span className="sidebar-theme-current capitalize">{preference === 'purple' ? 'Purple' : preference}</span>
              </button>

              {sidebarThemeDropdown && (
                <div className="sidebar-theme-menu">
                  {(['purple', 'dark', 'light', 'system'] as const).map(t => (
                    <button
                      key={t}
                      type="button"
                      className={`theme-menu-btn ${preference === t ? 'active' : ''}`}
                      onClick={() => {
                        setPreference(t)
                        setSidebarThemeDropdown(false)
                      }}
                    >
                      {t === 'purple' ? (
                        <SparklesIcon size={13} className="mr-1 inline" />
                      ) : t === 'light' ? (
                        <SunIcon size={13} className="mr-1 inline" />
                      ) : t === 'dark' ? (
                        <MoonIcon size={13} className="mr-1 inline" />
                      ) : (
                        <LaptopIcon size={13} className="mr-1 inline" />
                      )}
                      <span className="capitalize">{t === 'purple' ? 'Purple' : t}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* DEVELOPER PROFILE LINK */}
            <div className="sidebar-user-card">
              <NavLink
                className="sidebar-person-link"
                to="/profile"
                aria-label="Developer Profile"
                title="Open Developer Profile"
              >
                <span className="avatar">{student.name.slice(0, 1).toUpperCase()}</span>
                <div className="sidebar-person">
                  <strong>{student.name}</strong>
                  <span>Lead Engineer</span>
                </div>
              </NavLink>
              <button
                type="button"
                className="sidebar-signout-btn"
                onClick={leave}
                title="Sign out of developer profile"
                aria-label="Sign out"
              >
                <UserIcon size={13} />
              </button>
            </div>
          </div>
        </aside>

        {/* MAIN WORKSPACE CONTENT */}
        <main className="main-content">
          {student?.id === 1 && (
            <div className="showcase-ribbon">
              Showcase Mode <span>· Synthetic Data</span>
            </div>
          )}
          <Outlet />
        </main>
      </div>

      {/* MOBILE BOTTOM NAVIGATION */}
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {workspaceLinks.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => (isActive ? 'mobile-link active' : 'mobile-link')}
          >
            <span aria-hidden="true" className="mobile-icon">
              <Icon size={18} />
            </span>
            <span className="mobile-text">{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
