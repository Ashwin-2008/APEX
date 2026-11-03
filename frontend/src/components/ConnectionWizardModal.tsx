import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { connectNewProject } from '../api/projectsApi'
import { useProject } from '../context/ProjectContext'
import { FolderIcon, GithubIcon, SparklesIcon, ZapIcon } from './ui/Icons'

interface ConnectionWizardModalProps {
  isOpen: boolean
  onClose: () => void
}

export function ConnectionWizardModal({ isOpen, onClose }: ConnectionWizardModalProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [sourceType, setSourceType] = useState<'local' | 'github'>('local')
  const [path, setPath] = useState('')
  const [githubUrl, setGithubUrl] = useState('')
  const [branch, setBranch] = useState('')
  const [projectName, setProjectName] = useState('')
  const [enableMonitoring, setEnableMonitoring] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const { connect } = useProject()
  const navigate = useNavigate()

  if (!isOpen) return null

  const handleConnect = async () => {
    setErrorMessage(null)
    setConnecting(true)
    try {
      const resp = await connectNewProject({
        name: projectName.trim() || undefined,
        source_type: sourceType,
        path: sourceType === 'local' ? path.trim() : undefined,
        repository_url: sourceType === 'github' ? githubUrl.trim() : undefined,
        branch: branch.trim() || undefined,
        enable_monitoring: enableMonitoring,
      })

      connect({
        projectId: resp.project.id,
        name: resp.project.name,
        source: resp.project.source_type,
        path: resp.project.repository_path,
        repositoryUrl: resp.project.repository_url,
        branch: resp.project.branch,
        commitSha: resp.project.current_commit_sha,
        monitoringStatus: resp.project.monitoring_status,
      })

      onClose()
      navigate('/project-review')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Repository connection failed.'
      setErrorMessage(msg)
    } finally {
      setConnecting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-xl rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl p-6 text-slate-100">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div className="flex items-center gap-2">
            <span className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400">
              <ZapIcon size={18} />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">Connect Repository to APEX</h2>
              <p className="text-xs text-slate-400">Set up continuous engineering intelligence and failure prediction</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-md text-sm"
          >
            ✕
          </button>
        </div>

        {errorMessage && (
          <div className="mb-4 p-3 rounded-lg bg-red-950/60 border border-red-800 text-xs text-red-200">
            <strong>Connection Failed:</strong> {errorMessage}
          </div>
        )}

        {step === 1 && (
          <div>
            <div className="text-xs font-semibold uppercase text-slate-400 mb-2">Step 1 — Choose Source</div>
            <div className="grid grid-cols-2 gap-4 mb-6">
              <button
                type="button"
                onClick={() => setSourceType('local')}
                className={`p-4 rounded-xl border text-left transition-all ${
                  sourceType === 'local'
                    ? 'border-indigo-500 bg-indigo-950/40 text-white ring-1 ring-indigo-500'
                    : 'border-slate-800 bg-slate-950 hover:bg-slate-800/50 text-slate-300'
                }`}
              >
                <FolderIcon size={24} className="text-indigo-400 mb-2" />
                <div className="font-semibold text-sm">Local Repository</div>
                <div className="text-xs text-slate-400 mt-1">Directory on machine or mounted drive with live file watching.</div>
              </button>

              <button
                type="button"
                onClick={() => setSourceType('github')}
                className={`p-4 rounded-xl border text-left transition-all ${
                  sourceType === 'github'
                    ? 'border-indigo-500 bg-indigo-950/40 text-white ring-1 ring-indigo-500'
                    : 'border-slate-800 bg-slate-950 hover:bg-slate-800/50 text-slate-300'
                }`}
              >
                <GithubIcon size={24} className="text-indigo-400 mb-2" />
                <div className="font-semibold text-sm">GitHub Repository</div>
                <div className="text-xs text-slate-400 mt-1">Public or authorized GitHub repository clone and telemetry tracking.</div>
              </button>
            </div>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setStep(2)}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow"
              >
                Next: Configure Path →
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <div className="text-xs font-semibold uppercase text-slate-400 mb-2">Step 2 — Repository Configuration</div>

            {sourceType === 'local' ? (
              <div className="space-y-3 mb-6">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Local Repository Path</label>
                  <input
                    type="text"
                    placeholder="e.g. C:\Users\Username\Projects\my-app"
                    value={path}
                    onChange={e => setPath(e.target.value)}
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Absolute filesystem path visible to the APEX engine.</p>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Display Name (Optional)</label>
                  <input
                    type="text"
                    placeholder="Defaults to directory name"
                    value={projectName}
                    onChange={e => setProjectName(e.target.value)}
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-3 mb-6">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">GitHub HTTPS URL</label>
                  <input
                    type="text"
                    placeholder="https://github.com/owner/repository"
                    value={githubUrl}
                    onChange={e => setGithubUrl(e.target.value)}
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Branch (Optional)</label>
                    <input
                      type="text"
                      placeholder="e.g. main"
                      value={branch}
                      onChange={e => setBranch(e.target.value)}
                      className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">Display Name (Optional)</label>
                    <input
                      type="text"
                      placeholder="Defaults to repo name"
                      value={projectName}
                      onChange={e => setProjectName(e.target.value)}
                      className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>
              </div>
            )}

            <div className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between mb-6">
              <div>
                <div className="text-xs font-semibold text-slate-200">Continuous Live Monitoring</div>
                <div className="text-[11px] text-slate-400">Watch files for changes and execute incremental scans in real-time.</div>
              </div>
              <input
                type="checkbox"
                checked={enableMonitoring}
                onChange={e => setEnableMonitoring(e.target.checked)}
                className="w-4 h-4 rounded text-indigo-600 focus:ring-indigo-500 border-slate-700 bg-slate-900"
              />
            </div>

            <div className="flex justify-between">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
              >
                ← Back
              </button>
              <button
                type="button"
                disabled={connecting || (sourceType === 'local' ? !path.trim() : !githubUrl.trim())}
                onClick={handleConnect}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-lg shadow flex items-center gap-2"
              >
                {connecting ? (
                  <>
                    <span className="w-3 h-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
                    Analyzing Repository…
                  </>
                ) : (
                  'Start Analysis & Connect →'
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

