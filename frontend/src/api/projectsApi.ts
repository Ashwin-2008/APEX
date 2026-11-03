import { request } from './client'
import type {
  ActivityEventItem,
  AnalysisCoverageReport,
  ProjectFindingItem,
  ProjectItem,
  ProjectReview,
} from '../types/projectReview'

export async function fetchUserProjects(): Promise<ProjectItem[]> {
  return request<ProjectItem[]>('/projects')
}

export async function fetchProjectDetails(projectId: number): Promise<ProjectItem> {
  return request<ProjectItem>(`/projects/${projectId}`)
}

export async function connectNewProject(payload: {
  name?: string
  source_type: 'local' | 'github'
  path?: string
  repository_url?: string
  branch?: string
  enable_monitoring?: boolean
  enabled_analyzers?: string[]
}): Promise<{
  project: ProjectItem
  review_id: number
  review_number: number
  analysis: ProjectReview
  coverage: AnalysisCoverageReport
  persisted_review: Record<string, unknown>
}> {
  return request('/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateProjectSettings(
  projectId: number,
  patch: { name?: string; description?: string; settings?: Record<string, unknown> }
): Promise<{ id: number; name: string; settings?: Record<string, unknown> }> {
  return request(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export async function deleteProject(projectId: number): Promise<{ status: string; message: string }> {
  return request(`/projects/${projectId}`, {
    method: 'DELETE',
  })
}

export async function triggerManualAnalysis(projectId: number): Promise<{
  project_id: number
  review_id: number
  review_number: number
  coverage: AnalysisCoverageReport
  findings_count: number
}> {
  return request(`/projects/${projectId}/analyze`, {
    method: 'POST',
  })
}

export async function startMonitoring(projectId: number): Promise<{ project_id: number; monitoring_status: string }> {
  return request(`/projects/${projectId}/monitoring/start`, {
    method: 'POST',
  })
}

export async function stopMonitoring(projectId: number): Promise<{ project_id: number; monitoring_status: string }> {
  return request(`/projects/${projectId}/monitoring/stop`, {
    method: 'POST',
  })
}

export async function fetchProjectCoverage(projectId: number): Promise<AnalysisCoverageReport> {
  return request<AnalysisCoverageReport>(`/projects/${projectId}/coverage`)
}

export async function fetchProjectFindings(
  projectId: number,
  filters?: { status?: string; severity?: string; category?: string; suppressed?: boolean }
): Promise<ProjectFindingItem[]> {
  const query = new URLSearchParams()
  if (filters?.status) query.set('status_filter', filters.status)
  if (filters?.severity) query.set('severity', filters.severity)
  if (filters?.category) query.set('category', filters.category)
  if (filters?.suppressed !== undefined) query.set('suppressed', String(filters.suppressed))

  const qs = query.toString() ? `?${query.toString()}` : ''
  return request<ProjectFindingItem[]>(`/projects/${projectId}/findings${qs}`)
}

export async function suppressFinding(
  projectId: number,
  findingId: number,
  reason: string,
  suppressionType: 'false_positive' | 'wont_fix' | 'accepted_risk' = 'false_positive'
): Promise<ProjectFindingItem> {
  return request<ProjectFindingItem>(`/projects/${projectId}/findings/${findingId}/suppress`, {
    method: 'POST',
    body: JSON.stringify({ reason, suppression_type: suppressionType }),
  })
}

export async function reopenFinding(projectId: number, findingId: number): Promise<ProjectFindingItem> {
  return request<ProjectFindingItem>(`/projects/${projectId}/findings/${findingId}/reopen`, {
    method: 'POST',
  })
}

export async function fetchProjectActivity(projectId: number): Promise<ActivityEventItem[]> {
  return request<ActivityEventItem[]>(`/projects/${projectId}/activity`)
}

