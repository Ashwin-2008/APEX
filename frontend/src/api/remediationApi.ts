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
