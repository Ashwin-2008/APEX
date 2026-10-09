import { createContext, useContext, useState, type ReactNode } from 'react'
import type { ProjectReview } from '../types/projectReview'
import { clearProjectContext as clearStoredProjectContext } from '../utils/projectNotifications'

export interface ConnectedProject {
  projectId: number
  name: string
  source: 'local' | 'github'
  path: string
  repositoryUrl?: string | null
  branch?: string | null
  commitSha?: string | null
  monitoringStatus?: string
  review?: ProjectReview
}

interface ProjectContextValue {
  project: ConnectedProject | null
  isConnected: boolean
  connect: (data: ConnectedProject) => void
  disconnect: () => void
  updateProject: (patch: Partial<ConnectedProject>) => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: { children: ReactNode }) {
  // Start with stored project if available; otherwise null
  const [project, setProject] = useState<ConnectedProject | null>(() => {
    try {
      const raw = localStorage.getItem('mistiq.project.context')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed && parsed.projectId) {
          const name = parsed.path ? parsed.path.split(/[\\/]/).filter(Boolean).pop() : 'Connected project'
          return {
            projectId: parsed.projectId,
            name: name || 'Connected project',
            source: parsed.source || 'local',
            path: parsed.path || '',
            repositoryUrl: parsed.repositoryUrl,
            branch: parsed.branch,
            commitSha: parsed.commitSha,
            monitoringStatus: parsed.monitoringStatus || 'active',
          }
        }
      }
    } catch {
      // ignore
    }
    return null
  })

  const connect = (data: ConnectedProject) => {
    setProject(data)
  }

  const disconnect = () => {
    setProject(null)
    clearStoredProjectContext()
  }

  const updateProject = (patch: Partial<ConnectedProject>) => {
    setProject(prev => {
      if (!prev) return null
      const updated = { ...prev, ...patch }
      try {
        const raw = localStorage.getItem('mistiq.project.context')
        if (raw) {
          const parsed = JSON.parse(raw)
          localStorage.setItem('mistiq.project.context', JSON.stringify({ ...parsed, ...patch }))
        }
      } catch {
        // ignore
      }
      return updated
    })
  }


  return (
    <ProjectContext.Provider
      value={{
        project,
        isConnected: Boolean(project && project.projectId),
        connect,
        disconnect,
        updateProject,
      }}
    >
      {children}
    </ProjectContext.Provider>
  )
}

export function useProject() {
  const context = useContext(ProjectContext)
  if (!context) {
    // Provide a safe fallback for standalone component tests
    return {
      project: null,
      isConnected: false,
      connect: () => {},
      disconnect: () => {},
      updateProject: () => {},
    }
  }
  return context
}
