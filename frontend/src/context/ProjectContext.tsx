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
  // Start with null: BEFORE A PROJECT IS CONNECTED, no default project is shown
  const [project, setProject] = useState<ConnectedProject | null>(null)

  const connect = (data: ConnectedProject) => {
    setProject(data)
  }

  const disconnect = () => {
    setProject(null)
    clearStoredProjectContext()
  }

  const updateProject = (patch: Partial<ConnectedProject>) => {
    setProject(prev => (prev ? { ...prev, ...patch } : null))
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
