import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { deleteProject as apiDeleteProject, fetchProjectDetails, fetchUserProjects } from '../api/projectsApi'
import type { ProjectItem, ProjectReview } from '../types/projectReview'
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
  projects: ProjectItem[]
  isConnected: boolean
  loading: boolean
  connect: (data: ConnectedProject) => void
  disconnect: () => void
  selectProject: (projectId: number) => Promise<void>
  refreshProjects: () => Promise<void>
  removeProject: (projectId: number) => Promise<void>
  updateProject: (patch: Partial<ConnectedProject>) => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<ProjectItem[]>([])
  const [loading, setLoading] = useState(false)
  const [project, setProject] = useState<ConnectedProject | null>(() => {
    try {
      const raw = localStorage.getItem('mistiq.project.context')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed && parsed.projectId) {
          const name = parsed.name || (parsed.path ? parsed.path.split(/[\\/]/).filter(Boolean).pop() : 'Connected project')
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

  const refreshProjects = async () => {
    try {
      setLoading(true)
      const list = await fetchUserProjects()
      setProjects(list)
    } catch {
      // User may not be logged in yet
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshProjects()
  }, [])

  const selectProject = async (projectId: number) => {
    try {
      const details = await fetchProjectDetails(projectId)
      const connected: ConnectedProject = {
        projectId: details.id,
        name: details.name,
        source: details.source_type,
        path: details.repository_path,
        repositoryUrl: details.repository_url,
        branch: details.branch,
        commitSha: details.current_commit_sha,
        monitoringStatus: details.monitoring_status,
      }
      setProject(connected)
      localStorage.setItem('mistiq.project.context', JSON.stringify(connected))
      localStorage.setItem('apex.selected.projectId', String(projectId))
      // Trigger a storage event so notifications/subscribers adapt
      window.dispatchEvent(new Event('storage'))
    } catch (err) {
      console.error('Failed to switch project:', err)
    }
  }

  const connect = (data: ConnectedProject) => {
    setProject(data)
    localStorage.setItem('mistiq.project.context', JSON.stringify(data))
    localStorage.setItem('apex.selected.projectId', String(data.projectId))
    refreshProjects()
  }

  const disconnect = () => {
    setProject(null)
    clearStoredProjectContext()
    localStorage.removeItem('apex.selected.projectId')
  }

  const removeProject = async (projectId: number) => {
    await apiDeleteProject(projectId)
    if (project?.projectId === projectId) {
      disconnect()
    }
    await refreshProjects()
  }

  const updateProject = (patch: Partial<ConnectedProject>) => {
    setProject(prev => {
      if (!prev) return null
      const updated = { ...prev, ...patch }
      try {
        localStorage.setItem('mistiq.project.context', JSON.stringify(updated))
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
        projects,
        isConnected: Boolean(project && project.projectId),
        loading,
        connect,
        disconnect,
        selectProject,
        refreshProjects,
        removeProject,
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
      projects: [],
      isConnected: false,
      loading: false,
      connect: () => {},
      disconnect: () => {},
      selectProject: async () => {},
      refreshProjects: async () => {},
      removeProject: async () => {},
      updateProject: () => {},
    }
  }
  return context
}
