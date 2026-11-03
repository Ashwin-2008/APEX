import { useEffect, useState } from 'react'
import { fetchProjectActivity } from '../api/projectsApi'
import { useProject } from '../context/ProjectContext'
import type { ActivityEventItem } from '../types/projectReview'

export function ActivityFeedPage() {
  const { project, isConnected } = useProject()
  const [activity, setActivity] = useState<ActivityEventItem[]>([])
  const [loading, setLoading] = useState(false)

  const loadActivity = async () => {
    if (!project?.projectId) return
    setLoading(true)
    try {
      const data = await fetchProjectActivity(project.projectId)
      setActivity(data)
    } catch (err) {
      console.error('Failed to load project activity:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadActivity()
  }, [project?.projectId])

  if (!isConnected || !project) {
    return (
      <div className="p-8 text-center text-xs text-slate-500">
        Please connect or select a project from the workspace to view its live activity timeline.
      </div>
    )
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-xl font-black text-white">Live Activity Timeline</h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time audit history of file changes, analyzer runs, and findings lifecycle for <strong className="text-slate-200">{project.name}</strong>
          </p>
        </div>
        <button
          type="button"
          onClick={loadActivity}
          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg"
        >
          ↻ Refresh
        </button>
      </div>

      {loading ? (
        <div className="py-12 text-center text-xs text-slate-500">Loading timeline events…</div>
      ) : activity.length === 0 ? (
        <div className="py-12 text-center text-xs text-slate-500">No activity events recorded yet for this project.</div>
      ) : (
        <div className="relative border-l border-slate-800 ml-4 space-y-6 py-2">
          {activity.map(evt => (
            <div key={evt.id} className="relative pl-6">
              <span className="absolute -left-1.5 top-1.5 w-3 h-3 rounded-full border-2 border-slate-900 bg-indigo-500" />
              <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 shadow-sm">
                <div className="flex items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-white">{evt.title}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                      {evt.event_type}
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-500 font-mono">
                    {evt.created_at ? new Date(evt.created_at).toLocaleString() : ''}
                  </span>
                </div>
                <p className="text-xs text-slate-300">{evt.description}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

