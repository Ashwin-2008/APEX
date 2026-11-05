import { request } from './client'

export interface CodePatch {
  patch_id: string
  finding_id: string
  rule_id: string
  file: string
  original_snippet: string
  patched_snippet: string
  unified_diff: string
  strategy: string
  summary: string
  explanation: string
  tests_to_add: string[]
  validation_steps: string[]
  known_limitations?: string[]
  risk_classification?: string
  affected_symbols?: string[]
}

export interface PatchVerificationResult {
  status: string
  valid: boolean
  syntax_ok: boolean
  flaw_eliminated: boolean
  details: string
  diff?: string
}

export interface SemanticVerificationResult {
  valid: boolean
  risk_level: string
  summary: string
  details: string[]
  contract_changes: string[]
  control_flow_changes: string[]
  undefined_names: string[]
}

export interface BehavioralVerificationResult {
  status: string
  valid: boolean
  summary: string
  affected_symbol?: string | null
  test_files_run: string[]
  baseline_run?: any
  patched_run?: any
  newly_failing_tests: string[]
  details: string[]
}

export interface PostApplyVerificationResult {
  outcome: string
  flaw_eliminated: boolean
  summary: string
  original_flaw_detected: boolean
  new_findings_introduced: any[]
  behavioral_passed: boolean
  details: string[]
}

export interface AuditEvent {
  timestamp: string
  action: string
  from_state: string
  to_state: string
  actor: string
  details: string
}

export interface PatchProvenance {
  patch_id: string
  finding_id: string
  source_file: string
  original_source_sha256: string
  patched_source_sha256: string
  patch_content_sha256: string
  project_id?: number
  repo_revision?: string
  generator_version: string
  analyzer_version: string
  created_at: string
}

export interface ConfidenceDimension {
  name: string
  status: string
  score: number
  verified: boolean
  explanation: string
}

export interface PatchConfidenceReport {
  patch_id: string
  overall_status: string
  dimensions: ConfidenceDimension[]
  human_explanation: string
  can_apply: boolean
  requires_human_approval: boolean
}

export interface PatchRecord {
  patch: CodePatch
  state: string
  provenance?: PatchProvenance
  verification?: PatchVerificationResult
  semantic_verification?: SemanticVerificationResult
  behavioral_verification?: BehavioralVerificationResult
  post_apply_verification?: PostApplyVerificationResult
  backup_file_path?: string
  backup_sha256?: string
  applied_sha256?: string
  created_at: string
  applied_at?: string
  rolled_back_at?: string
  audit_trail: AuditEvent[]
}

export interface GenerateFixResponse {
  patch: CodePatch
  verification: PatchVerificationResult
  provenance?: PatchProvenance
  semantic_verification?: SemanticVerificationResult
  record: PatchRecord
}

export interface PatchActionResponse {
  success: boolean
  message: string
  patch_record?: PatchRecord
}

// ==========================================
// Phase 2D.2: Transaction & Recovery Types
// ==========================================

export interface PlannedFile {
  rel_path: string
  target_abs_path: string
  pre_hash: string
  post_hash: string
  staged_path: string
  backup_path: string
  status: string
  finding_id?: string
}

export interface RemediationTransaction {
  transaction_id: string
  project_id: number
  user_id?: number
  state: string
  created_at: string
  updated_at: string
  files_count: number
  files: PlannedFile[]
  finding_ids: string[]
  error_message?: string | null
  post_verification?: {
    status: string
    verified: boolean
    regressions: string[]
    files_checked: string[]
    verified_at: string
  } | null
}

export interface JournalEntry {
  timestamp: string
  event: string
  data: any
}

export interface LockStatus {
  is_locked: boolean
  project_id: number
  transaction_id?: string | null
  holder?: string | null
  expires_at?: string | null
  is_stale: boolean
  pid?: number | null
}

export interface RecoverySummary {
  project_id: number
  stale_lock_cleared: boolean
  recovered_transactions_count: number
  recovered_transactions: any[]
  manual_reconciliation_needed: any[]
}

export async function generateFix(
  projectId: number | string,
  findingId: string,
  customFinding?: any
): Promise<GenerateFixResponse> {
  return request<GenerateFixResponse>(`/project-reviews/${projectId}/findings/${encodeURIComponent(findingId)}/generate-fix`, {
    method: 'POST',
    body: JSON.stringify({ custom_finding: customFinding }),
  })
}

export async function applyPatch(
  projectId: number | string,
  patchId: string
): Promise<PatchActionResponse> {
  return request<PatchActionResponse>(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/apply`, {
    method: 'POST',
  })
}

export async function rollbackPatch(
  projectId: number | string,
  patchId: string
): Promise<PatchActionResponse> {
  return request<PatchActionResponse>(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/rollback`, {
    method: 'POST',
  })
}

export async function getPatchProvenance(
  projectId: number | string,
  patchId: string
): Promise<{ patch_id: string; provenance: PatchProvenance; state: string }> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/provenance`)
}

export async function getPatchVerification(
  projectId: number | string,
  patchId: string
): Promise<PatchConfidenceReport> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/verification`)
}

export async function getPatchHistory(
  projectId: number | string,
  patchId: string
): Promise<{ patch_id: string; state: string; audit_trail: AuditEvent[] }> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/history`)
}

export async function verifySemantic(
  projectId: number | string,
  patchId: string
): Promise<SemanticVerificationResult> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/verify-semantic`, {
    method: 'POST',
  })
}

export async function verifyBehavioral(
  projectId: number | string,
  patchId: string
): Promise<BehavioralVerificationResult> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/verify-behavioral`, {
    method: 'POST',
  })
}

export async function postApplyVerify(
  projectId: number | string,
  patchId: string
): Promise<PostApplyVerificationResult> {
  return request(`/project-reviews/${projectId}/patches/${encodeURIComponent(patchId)}/post-apply-verify`, {
    method: 'POST',
  })
}

// Phase 2D.2 APIs

export async function createTransaction(
  projectId: number | string,
  patches: Array<{ rel_path: string; patched_content: string; finding_id?: string }>,
  autoApply: boolean = false
): Promise<RemediationTransaction> {
  return request<RemediationTransaction>(`/project-reviews/${projectId}/remediation/transactions`, {
    method: 'POST',
    body: JSON.stringify({ patches, auto_apply: autoApply }),
  })
}

export async function listTransactions(
  projectId: number | string
): Promise<{ project_id: number; transactions: any[] }> {
  return request(`/project-reviews/${projectId}/remediation/transactions`)
}

export async function getTransaction(
  projectId: number | string,
  transactionId: string
): Promise<{ transaction_id: string; manifest: RemediationTransaction; journal: JournalEntry[] }> {
  return request(`/project-reviews/${projectId}/remediation/transactions/${encodeURIComponent(transactionId)}`)
}

export async function applyTransaction(
  projectId: number | string,
  transactionId: string
): Promise<RemediationTransaction> {
  return request<RemediationTransaction>(`/project-reviews/${projectId}/remediation/transactions/${encodeURIComponent(transactionId)}/apply`, {
    method: 'POST',
  })
}

export async function rollbackTransaction(
  projectId: number | string,
  transactionId: string,
  force: boolean = false
): Promise<RemediationTransaction> {
  return request<RemediationTransaction>(`/project-reviews/${projectId}/remediation/transactions/${encodeURIComponent(transactionId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  })
}

export async function recoverTransaction(
  projectId: number | string,
  transactionId: string
): Promise<any> {
  return request(`/project-reviews/${projectId}/remediation/transactions/${encodeURIComponent(transactionId)}/recover`, {
    method: 'POST',
  })
}

export async function inspectLock(
  projectId: number | string
): Promise<LockStatus> {
  return request<LockStatus>(`/project-reviews/${projectId}/remediation/locks`)
}

export async function breakStaleLock(
  projectId: number | string,
  force: boolean = false
): Promise<{ project_id: number; broken: boolean; message: string }> {
  return request(`/project-reviews/${projectId}/remediation/locks/break-stale`, {
    method: 'POST',
    body: JSON.stringify({ force }),
  })
}

export async function scanRecovery(
  projectId: number | string
): Promise<RecoverySummary> {
  return request<RecoverySummary>(`/project-reviews/${projectId}/remediation/scan-recovery`, {
    method: 'POST',
  })
}

// =====================================================================
// Phase 5.1: Durable Remediation Orchestrator Workflow APIs
// =====================================================================

export interface RemediationWorkflowSummary {
  workflow_id: string
  project_id: number
  tenant_id: string
  state: string
  risk_level: string
  approval_policy: string
  idempotency_key: string
  title: string
  description?: string | null
  version_id: number
  retry_count: number
  created_at: string
  updated_at: string
}

export interface RemediationWorkflowDetail extends RemediationWorkflowSummary {
  finding_ids: number[]
  active_plan_id?: string | null
  active_candidate_id?: string | null
  active_transaction_id?: string | null
  error_message?: string | null
  lease_holder?: string | null
  fencing_token: number
}

export interface WorkflowAuditEvent {
  event_id: string
  workflow_id: string
  from_state?: string | null
  to_state: string
  action: string
  actor: string
  event_payload: Record<string, any>
  created_at: string
}

export interface CandidatePatch {
  candidate_id: string
  workflow_id: string
  plan_id: string
  strategy: string
  diff_unified: string
  diff_hash: string
  files_manifest: Record<string, any>
  lifecycle_state: string
  created_at: string
}

export interface WorkflowApproval {
  approval_id: string
  workflow_id: string
  candidate_id: string
  patch_content_hash: string
  approving_actor: string
  decision: string
  risk_classification: string
  approval_policy: string
  decision_rationale: string
  is_valid: boolean
  created_at: string
}

export async function createRemediationWorkflow(
  projectId: number | string,
  data: {
    finding_ids: number[]
    title: string
    description?: string
    risk_level?: string
    approval_policy?: string
    idempotency_key?: string
  }
): Promise<RemediationWorkflowDetail> {
  return request<RemediationWorkflowDetail>(`/projects/${projectId}/remediation/workflows`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function listRemediationWorkflows(
  projectId: number | string,
  options: { skip?: number; limit?: number; state?: string } = {}
): Promise<RemediationWorkflowSummary[]> {
  const params = new URLSearchParams()
  if (options.skip !== undefined) params.set('skip', String(options.skip))
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  if (options.state) params.set('state', options.state)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return request<RemediationWorkflowSummary[]>(`/projects/${projectId}/remediation/workflows${qs}`)
}

export async function getRemediationWorkflow(
  projectId: number | string,
  workflowId: string
): Promise<RemediationWorkflowDetail> {
  return request<RemediationWorkflowDetail>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}`
  )
}

export async function cancelRemediationWorkflow(
  projectId: number | string,
  workflowId: string,
  reason: string = 'User requested cancellation'
): Promise<RemediationWorkflowSummary> {
  return request<RemediationWorkflowSummary>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/cancel`,
    {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }
  )
}

export async function getRemediationWorkflowHistory(
  projectId: number | string,
  workflowId: string,
  options: { skip?: number; limit?: number } = {}
): Promise<WorkflowAuditEvent[]> {
  const params = new URLSearchParams()
  if (options.skip !== undefined) params.set('skip', String(options.skip))
  if (options.limit !== undefined) params.set('limit', String(options.limit))
  const qs = params.toString() ? `?${params.toString()}` : ''
  return request<WorkflowAuditEvent[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/history${qs}`
  )
}

export async function listRemediationWorkflowCandidates(
  projectId: number | string,
  workflowId: string
): Promise<CandidatePatch[]> {
  return request<CandidatePatch[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/candidates`
  )
}

export async function listRemediationWorkflowApprovals(
  projectId: number | string,
  workflowId: string
): Promise<WorkflowApproval[]> {
  return request<WorkflowApproval[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/approvals`
  )
}

export async function recordWorkflowApproval(
  projectId: number | string,
  workflowId: string,
  data: {
    candidate_id: string
    patch_content_hash: string
    decision: 'APPROVED' | 'REJECTED'
    rationale: string
    candidate_version?: number
    base_commit_sha?: string
  }
): Promise<WorkflowApproval> {
  return request<WorkflowApproval>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/approve`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    }
  )
}

export async function revokeWorkflowApproval(
  projectId: number | string,
  workflowId: string,
  approvalId: string,
  reason: string
): Promise<WorkflowApproval> {
  return request<WorkflowApproval>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/approvals/${encodeURIComponent(approvalId)}/revoke`,
    {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }
  )
}

export interface AuditChainVerifyResult {
  workflow_id: string
  is_valid: boolean
  errors: string[]
}

export async function verifyWorkflowAuditChain(
  projectId: number | string,
  workflowId: string
): Promise<AuditChainVerifyResult> {
  return request<AuditChainVerifyResult>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/audit-events/verify`
  )
}

// =====================================================================
// Phase 5.2: Root Cause Investigation & Remediation Planning API
// =====================================================================

export interface RemediationHypothesis {
  hypothesis_id: string
  workflow_id: string
  title: string
  category: string
  explanation: string
  confidence_score: number
  status: 'CONFIRMED' | 'STRONGLY_SUPPORTED' | 'INFERRED' | 'INSUFFICIENT_EVIDENCE' | 'REJECTED'
  supporting_evidence: Array<{
    source_type: string
    summary: string
    confidence: number
    finding_id?: number
    metadata?: Record<string, any>
  }>
  contradicting_evidence: Array<{
    source_type: string
    summary: string
    confidence: number
  }>
  affected_symbols: string[]
  affected_files: string[]
  evidence_completeness_score: number
  provenance: Record<string, any> | string
  created_at: string
}

export interface FindingCluster {
  cluster_id: string
  workflow_id: string
  cluster_name: string
  primary_finding_id: number
  thematic_category: string
  correlation_rationale: string
  confidence_score: number
  is_manually_adjusted: boolean
  finding_ids: number[]
  created_at: string
}

export interface RemediationPlan {
  plan_id: string
  workflow_id: string
  strategy_name: string
  strategy_description?: string
  target_findings: number[]
  affected_files: string[]
  root_cause_reference: Record<string, any>
  proposed_changes_summary: string
  regression_risks: string[]
  required_tests: Array<{
    test_id: string
    test_name: string
    file_path: string
    tier: string
    confidence: number
    reason: string
    classification?: string
  }>
  rollback_strategy: string
  risk_assessment: {
    blast_radius_score?: number
    risk_level?: string
    affected_modules?: string[]
    predictive_risk_distribution?: Record<string, number>
    candidate_patch_preview?: string
    scoring_weights_used?: Record<string, number>
  }
  plan_score: number
  score_breakdown: Record<string, number>
  ranking_explanation?: string
  approval_tier_required: string
  estimated_complexity: string
  is_preferred: boolean
  abstain_reason?: string | null
  created_at: string
}

export interface PlanComparisonMatrix {
  workflow_id: string
  plans_count: number
  comparison_matrix: Array<{
    plan_id: string
    strategy_name: string
    score: number
    is_preferred: boolean
    complexity: string
    approval_tier: string
    blast_radius_score: number
    affected_modules_count: number
    required_tests_count: number
    abstained: boolean
    abstain_reason?: string | null
    score_breakdown: Record<string, number>
  }>
}

export async function triggerRootCauseInvestigation(
  projectId: number | string,
  workflowId: string
): Promise<{ status: string; hypotheses_count: number; clusters_count: number }> {
  return request<{ status: string; hypotheses_count: number; clusters_count: number }>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/investigate`,
    { method: 'POST' }
  )
}

export async function fetchInvestigationDetails(
  projectId: number | string,
  workflowId: string
): Promise<{
  workflow_id: string
  workflow_state: string
  hypotheses: RemediationHypothesis[]
  clusters: FindingCluster[]
}> {
  return request<{
    workflow_id: string
    workflow_state: string
    hypotheses: RemediationHypothesis[]
    clusters: FindingCluster[]
  }>(`/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/investigation`)
}

export async function fetchHypotheses(
  projectId: number | string,
  workflowId: string
): Promise<RemediationHypothesis[]> {
  return request<RemediationHypothesis[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/hypotheses`
  )
}

export async function fetchClusters(
  projectId: number | string,
  workflowId: string
): Promise<FindingCluster[]> {
  return request<FindingCluster[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/clusters`
  )
}

export async function separateFindingFromCluster(
  projectId: number | string,
  workflowId: string,
  clusterId: string,
  findingId: number,
  reason: string
): Promise<any> {
  return request(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/clusters/${encodeURIComponent(clusterId)}/separate-finding`,
    {
      method: 'POST',
      body: JSON.stringify({ finding_id: findingId, reason }),
    }
  )
}

export async function generateRemediationPlans(
  projectId: number | string,
  workflowId: string
): Promise<RemediationPlan[]> {
  return request<RemediationPlan[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/generate-plans`,
    { method: 'POST' }
  )
}

export async function fetchRemediationPlans(
  projectId: number | string,
  workflowId: string
): Promise<RemediationPlan[]> {
  return request<RemediationPlan[]>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/plans`
  )
}

export async function fetchRemediationPlan(
  projectId: number | string,
  workflowId: string,
  planId: string
): Promise<RemediationPlan> {
  return request<RemediationPlan>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/plans/${encodeURIComponent(planId)}`
  )
}

export async function selectPreferredPlan(
  projectId: number | string,
  workflowId: string,
  planId: string
): Promise<{ status: string; plan_id: string; strategy_name: string; workflow_state: string; active_candidate_id: string }> {
  return request(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/plans/${encodeURIComponent(planId)}/select`,
    { method: 'POST' }
  )
}

export async function compareRemediationPlans(
  projectId: number | string,
  workflowId: string
): Promise<PlanComparisonMatrix> {
  return request<PlanComparisonMatrix>(
    `/projects/${projectId}/remediation/workflows/${encodeURIComponent(workflowId)}/plans/compare`
  )
}
