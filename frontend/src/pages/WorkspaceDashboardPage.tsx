import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchUserProjects,
  startMonitoring,
  stopMonitoring,
  triggerManualAnalysis,
} from '../api/projectsApi'
import { ConnectionWizardModal } from '../components/ConnectionWizardModal'
import { FolderIcon, GithubIcon, GitBranchIcon, SparklesIcon, ZapIcon } from '../components/ui/Icons'
import { useAuth } from '../context/AuthContext'
import { useProject } from '../context/ProjectContext'
import type { ProjectItem } from '../types/projectReview'

export function WorkspaceDashboardPage() {
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [wizardOpen, setWizardOpen] = useState(false)
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null)

  const { user } = useAuth()
  const { selectProject, removeProject } = useProject()
  const navigate = useNavigate()

  const loadProjects = async () => {
    try {
      setLoading(true)
      const list = await fetchUserProjects()
      setProjects(list)
    } catch (err) {
      console.error('Failed to load workspace projects:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProjects()
  }, [])

  const handleOpenProject = async (p: ProjectItem) => {
    await selectProject(p.id)
    navigate('/project-review')
  }

  const handleToggleMonitoring = async (p: ProjectItem) => {
    setActionLoadingId(p.id)
    try {
      if (p.monitoring_status === 'active') {
        await stopMonitoring(p.id)
      } else {
        await startMonitoring(p.id)
      }
      await loadProjects()
    } catch (err) {
      console.error('Failed to toggle monitoring:', err)
    } finally {
      setActionLoadingId(null)
    }
  }

  const handleManualScan = async (p: ProjectItem) => {
    setActionLoadingId(p.id)
    try {
      await triggerManualAnalysis(p.id)
      await loadProjects()
    } catch (err) {
      console.error('Failed to trigger manual scan:', err)
    } finally {
      setActionLoadingId(null)
    }
  }

  const handleDeleteProject = async (p: ProjectItem) => {
    if (!window.confirm(`Are you sure you want to disconnect and delete '${p.name}'?`)) return
    setActionLoadingId(p.id)
    try {
      await removeProject(p.id)
      await loadProjects()
    } catch (err) {
      console.error('Failed to remove project:', err)
    } finally {
      setActionLoadingId(null)
    }
  }

  const filteredProjects = projects.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.repository_path.toLowerCase().includes(search.toLowerCase())
  )

  const totalReviews = projects.reduce((acc, p) => acc + (p.summary?.reviews_count || 0), 0)
  const activeMonitored = projects.filter(p => p.monitoring_status === 'active').length
  const totalFindings = projects.reduce((acc, p) => acc + (p.summary?.active_findings_count || 0), 0)
  const criticalFindings = projects.reduce((acc, p) => acc + (p.summary?.critical_findings_count || 0), 0)

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* HEADER SECTION */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-black tracking-tight text-white">Engineering Workspace</h1>
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
              MULTI-TENANT 2.0
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Welcome back, <strong className="text-slate-200">{user?.full_name || user?.username || 'Engineer'}</strong>. Manage and monitor your software repositories independently.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setWizardOpen(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow flex items-center gap-2 transition-colors"
          >
            <span>+</span>
            <span>Connect Project</span>
          </button>
        </div>
      </div>

      {/* METRICS ROW */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Connected Projects</div>
          <div className="text-2xl font-black text-white mt-1 font-mono">{projects.length}</div>
          <div className="text-[10px] text-slate-500 mt-1">{totalReviews} historical reviews recorded</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Live Monitored</div>
          <div className="text-2xl font-black text-emerald-400 mt-1 font-mono">{activeMonitored}</div>
          <div className="text-[10px] text-slate-500 mt-1">Real-time file watching & Git polling</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Active Findings</div>
          <div className="text-2xl font-black text-amber-400 mt-1 font-mono">{totalFindings}</div>
          <div className="text-[10px] text-slate-500 mt-1">Across all workspace repositories</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Critical Risks</div>
          <div className={`text-2xl font-black mt-1 font-mono ${criticalFindings > 0 ? 'text-red-400' : 'text-slate-400'}`}>
            {criticalFindings}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">Urgent vulnerabilities requiring review</div>
        </div>
      </div>

      {/* SEARCH AND FILTER BAR */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <input
            type="text"
            placeholder="Search projects by name or directory…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full px-3 py-2 text-xs bg-slate-900 border border-slate-800 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div className="text-xs text-slate-400">
          Showing <span className="text-white font-medium">{filteredProjects.length}</span> of {projects.length} project(s)
        </div>
      </div>

      {/* PROJECTS GRID */}
      {loading ? (
        <div className="py-16 text-center text-xs text-slate-500">Loading workspace projects…</div>
      ) : filteredProjects.length === 0 ? (
        <div className="py-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/30 p-8">
          <div className="w-12 h-12 rounded-full bg-indigo-500/10 text-indigo-400 mx-auto flex items-center justify-center mb-3">
            <ZapIcon size={24} />
          </div>
          <h3 className="text-sm font-bold text-white">No Projects Connected</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
            Connect your first local repository or public/private GitHub repo to start tracking engineering quality and failure patterns.
          </p>
          <button
            type="button"
            onClick={() => setWizardOpen(true)}
            className="mt-4 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow"
          >
            + Connect Repository
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredProjects.map(p => {
            const isActing = actionLoadingId === p.id
            const isMonitoringActive = p.monitoring_status === 'active'

            return (
              <div
                key={p.id}
                className="rounded-xl border border-slate-800 bg-slate-900/70 hover:border-slate-700 transition-all shadow-sm flex flex-col justify-between p-5"
              >
                <div>
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 truncate">
                      {p.source_type === 'github' ? (
                        <GithubIcon size={16} className="text-indigo-400 flex-shrink-0" />
                      ) : (
                        <FolderIcon size={16} className="text-indigo-400 flex-shrink-0" />
                      )}
                      <h3 className="text-sm font-bold text-white truncate" title={p.name}>
                        {p.name}
                      </h3>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase flex-shrink-0 ${
                        isMonitoringActive
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {p.monitoring_status}
                    </span>
                  </div>

                  <p className="text-[11px] text-slate-400 truncate mb-3 font-mono" title={p.repository_path}>
                    {p.repository_path}
                  </p>

                  <div className="flex items-center gap-2 text-[11px] text-slate-400 mb-4">
                    {p.branch && (
                      <span className="flex items-center gap-1 bg-slate-950 px-2 py-0.5 rounded border border-slate-800">
                        <GitBranchIcon size={10} className="text-indigo-400" />
                        <code>{p.branch}</code>
                      </span>
                    )}
                    {p.current_commit_sha && (
                      <span className="bg-slate-950 px-2 py-0.5 rounded border border-slate-800 font-mono text-[10px]">
                        {p.current_commit_sha.slice(0, 7)}
                      </span>
                    )}
                  </div>

                  {/* Summary pills */}
                  <div className="grid grid-cols-3 gap-2 py-3 border-t border-slate-800/80 text-center text-xs">
                    <div>
                      <div className="font-bold text-slate-200 font-mono">
                        {p.summary?.active_findings_count || 0}
                      </div>
                      <div className="text-[10px] text-slate-500">Findings</div>
                    </div>
                    <div>
                      <div className={`font-bold font-mono ${p.summary?.critical_findings_count ? 'text-red-400' : 'text-slate-400'}`}>
                        {p.summary?.critical_findings_count || 0}
                      </div>
                      <div className="text-[10px] text-slate-500">Critical</div>
                    </div>
                    <div>
                      <div className="font-bold text-indigo-400 font-mono">
                        {p.summary?.latest_coverage || 85}%
                      </div>
                      <div className="text-[10px] text-slate-500">Coverage</div>
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-slate-800 flex items-center justify-between gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => handleOpenProject(p)}
                    className="flex-1 py-1.5 px-3 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg transition-colors text-center"
                  >
                    Open Dashboard →
                  </button>

                  <button
                    type="button"
                    disabled={isActing}
                    onClick={() => handleToggleMonitoring(p)}
                    className="p-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
                    title={isMonitoringActive ? 'Pause Monitoring' : 'Resume Monitoring'}
                  >
                    {isMonitoringActive ? '⏸' : '▶'}
                  </button>

                  <button
                    type="button"
                    disabled={isActing}
                    onClick={() => handleManualScan(p)}
                    className="p-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
                    title="Run Full Scan"
                  >
                    🔄
                  </button>

                  <button
                    type="button"
                    disabled={isActing}
                    onClick={() => handleDeleteProject(p)}
                    className="p-1.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-red-950/60 hover:text-red-400 text-slate-400 text-xs"
                    title="Disconnect Project"
                  >
                    🗑
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* CONNECTION WIZARD MODAL */}
      <ConnectionWizardModal isOpen={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  )
}

