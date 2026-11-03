import type { CodeIntelligencePreview, EvolutionReport, FailureHistoryResponse, ProjectReview, RegistrySummary, RemediationResponse, RequirementReport, ResearchDatasetResponse, ResearchEvaluationResponse, ResearchPrediction, ResearchStatus, ReviewComparison, ReviewHistoryItem, TrajectoryResponse } from '../types/projectReview'
const baseUrl = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
export async function analyzeProject(projectPath: string): Promise<ProjectReview> {
  const response = await fetch(`${baseUrl}/project-reviews/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_path: projectPath }) })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : `Review failed (${response.status})`; throw new Error(detail) }
  if (!payload || typeof payload !== 'object' || !('events' in payload) || !('summary' in payload)) throw new Error('The reviewer returned an incomplete response.')
  return payload as ProjectReview
}
export async function connectProject(sourceType: 'local' | 'github', value: string): Promise<{ analysis: ProjectReview; project_id: number; monitoring_status: string; path: string; branch: string | null; current_commit_sha: string | null }> { const response = await fetch(`${baseUrl}/project-reviews/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sourceType === 'local' ? { source_type: sourceType, path: value } : { source_type: sourceType, repository_url: value }) }); const payload: unknown = await response.json().catch(() => null); if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : 'Unable to connect project.'; throw new Error(detail) } return payload as { analysis: ProjectReview; project_id: number; monitoring_status: string; path: string; branch: string | null; current_commit_sha: string | null } }
export async function getReviewHistory(projectId: number): Promise<{ project: { id: number; name: string; repository_path: string }; reviews: ReviewHistoryItem[] }> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/history`); if (!response.ok) throw new Error('Unable to load review history.'); return response.json() }
export async function compareReviews(projectId: number): Promise<ReviewComparison> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/compare`); if (!response.ok) throw new Error('Unable to compare reviews.'); return response.json() }
export async function getEvolution(projectId: number): Promise<EvolutionReport> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/evolution`); if (!response.ok) throw new Error('Unable to load evolution.'); return response.json() }
export async function getRequirements(projectId: number): Promise<RequirementReport> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/requirements/coverage`); if (!response.ok) throw new Error('Unable to load requirements.'); return response.json() }
export async function stopMonitoring(projectId: number): Promise<{ project_id: number; monitoring_status: string }> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/monitoring/stop`, { method: 'POST' }); const payload: unknown = await response.json().catch(() => null); if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : 'Unable to stop monitoring.'; throw new Error(detail) } return payload as { project_id: number; monitoring_status: string } }
async function getResearch<T>(endpoint: string, fallback: string): Promise<T> { const response = await fetch(`${baseUrl}/project-reviews/${endpoint}`); const payload: unknown = await response.json().catch(() => null); if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : fallback; throw new Error(detail) } return payload as T }
export async function getResearchStatus(): Promise<ResearchStatus> { return getResearch<ResearchStatus>('research/status', 'Unable to load research status.') }
export async function getResearchDataset(): Promise<ResearchDatasetResponse> { return getResearch<ResearchDatasetResponse>('research/dataset', 'Unable to load the research dataset.') }
export async function getResearchEvaluation(): Promise<ResearchEvaluationResponse> { return getResearch<ResearchEvaluationResponse>('research/evaluation', 'Unable to run the research evaluation.') }
export async function getResearchPrediction(projectId: number): Promise<ResearchPrediction> { return getResearch<ResearchPrediction>(`${projectId}/research-prediction`, 'Unable to load the research prediction.') }
export async function getFailureHistory(projectId: number): Promise<FailureHistoryResponse> { return getResearch<FailureHistoryResponse>(`${projectId}/failure-history`, 'Unable to load the failure history.') }
export async function getTrajectory(projectId: number): Promise<TrajectoryResponse> { return getResearch<TrajectoryResponse>(`${projectId}/trajectory`, 'Unable to load observed failure transitions.') }
export async function getProjects(): Promise<Array<{ id: number; name: string; repository_path: string; source_type: string; repository_url: string | null; branch: string | null; current_commit_sha: string | null; monitoring_status: string; updated_at: string | null }>> { const response = await fetch(`${baseUrl}/project-reviews/projects`); if (!response.ok) throw new Error('Unable to load projects list.'); return response.json() }
export async function getLatestReview(projectId: number): Promise<ProjectReview> { const response = await fetch(`${baseUrl}/project-reviews/${projectId}/latest`); if (!response.ok) throw new Error('Unable to load latest review.'); return response.json() }
export async function getCodeIntelligence(projectId: number): Promise<CodeIntelligencePreview & { risk_regions?: CodeIntelligencePreview['top_risk_regions'] }> { return getResearch(`${projectId}/code-intelligence`, 'Unable to load line-level code intelligence.') }
export async function requestRemediation(projectId: number, item: { file?: string | null; start_line?: number | null; end_line?: number | null; category: string; title: string; explanation?: string; state?: string }): Promise<RemediationResponse> {
  const response = await fetch(`${baseUrl}/project-reviews/${projectId}/remediation`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item) })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : 'Unable to generate remediation suggestion.'; throw new Error(detail) }
  return payload as RemediationResponse
}
export async function getModelRegistry(): Promise<RegistrySummary> { return getResearch<RegistrySummary>('research/registry', 'Unable to load model registry.') }
export async function promoteCandidateModel(candidateId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${baseUrl}/project-reviews/research/candidates/${encodeURIComponent(candidateId)}/promote`, { method: 'POST' })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : 'Unable to promote candidate model.'; throw new Error(detail) }
  return payload as Record<string, unknown>
}
export async function rollbackProductionModel(targetCandidateId?: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${baseUrl}/project-reviews/research/production/rollback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_candidate_id: targetCandidateId ?? null }) })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) { const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : 'Unable to roll back production model.'; throw new Error(detail) }
  return payload as Record<string, unknown>
}
