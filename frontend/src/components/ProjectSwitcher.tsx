import { useState, useRef, useEffect } from 'react'
import { useProject } from '../context/ProjectContext'
import { FolderIcon, GithubIcon, GitBranchIcon, ZapIcon } from './ui/Icons'

interface ProjectSwitcherProps {
  onOpenConnectWizard?: () => void
}

export function ProjectSwitcher({ onOpenConnectWizard }: ProjectSwitcherProps) {
  const { project, projects, selectProject } = useProject()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  const filtered = projects.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.repository_path.toLowerCase().includes(search.toLowerCase())
  )

  const activeProject = project ? projects.find(p => p.id === project.projectId) || project : null

  return (
    <div className="relative inline-block text-left" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700/80 transition-colors text-sm text-slate-100 font-medium shadow-sm"
        title="Switch active project workspace"
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="max-w-[160px] truncate">
          {activeProject?.name || 'Select Project'}
        </span>
        <svg className="w-4 h-4 text-slate-400 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 mt-2 w-80 rounded-xl shadow-2xl bg-slate-900 border border-slate-700 py-2 z-50 animate-in fade-in slide-in-from-top-2">
          <div className="px-3 pb-2 border-b border-slate-800">
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">
              Active Workspace
            </div>
            <input
              type="text"
              placeholder="Filter projects…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full px-2.5 py-1 text-xs bg-slate-950 border border-slate-700 rounded-md text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="max-h-60 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-4 py-3 text-xs text-slate-400 text-center">
                {projects.length === 0 ? 'No projects connected yet' : 'No matching projects found'}
              </div>
            ) : (
              filtered.map(p => {
                const isSelected = project?.projectId === p.id
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      selectProject(p.id)
                      setOpen(false)
                    }}
                    className={`w-full text-left px-3 py-2 flex items-center justify-between text-xs hover:bg-slate-800 transition-colors ${
                      isSelected ? 'bg-indigo-950/40 text-indigo-300 font-medium border-l-2 border-indigo-500' : 'text-slate-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      {p.source_type === 'github' ? (
                        <GithubIcon size={12} className="text-slate-400 flex-shrink-0" />
                      ) : (
                        <FolderIcon size={12} className="text-slate-400 flex-shrink-0" />
                      )}
                      <span className="truncate">{p.name}</span>
                    </div>
                    {isSelected && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono">
                        Active
                      </span>
                    )}
                  </button>
                )
              })
            )}
          </div>

          <div className="pt-2 px-2 border-t border-slate-800">
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                if (onOpenConnectWizard) onOpenConnectWizard()
              }}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 px-3 text-xs font-medium text-indigo-400 bg-indigo-950/50 hover:bg-indigo-900/60 rounded-lg border border-indigo-800/50 transition-colors"
            >
              <span>+</span>
              <span>Connect New Project</span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

