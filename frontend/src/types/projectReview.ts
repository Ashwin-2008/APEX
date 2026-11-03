export type Severity = 'critical' | 'high' | 'medium' | 'low' | string

export interface DataFlowStep {
  step: number
  file?: string
  line?: number
  symbol?: string
  expression?: string
  role?: string
  module?: string
}

export interface FailureEvent {
  category: string
  severity: Severity
  confidence: number
  timestamp: string
  evidence: string
  analyzer_source: string
  status: string
  remediation: string
  component?: string
  file?: string
  line?: number
  end_line?: number
  rule_id?: string
  title?: string
  data_flow?: DataFlowStep[]
  metadata?: Record<string, any>
}
export interface FailureHistoryItem { timestamp: string; category: string; evidence: string }
export interface Transition { from: string; to: string; count: number; probability: number }
export interface FailureLoop { pattern: string; occurrence_count: number; risk: Severity; affected_component?: string; recommendation?: string }
export interface Prediction { category: string; probability: number; confidence: number; historical_support: number; affected_component?: string; evidence?: string; recommended_action?: string }
export interface ReviewHistoryItem { id: number; review_number: number; timestamp: string; metrics: Record<string, number>; finding_count: number; top_prediction: string | null }
export interface FailureHistoryRow { fingerprint: string; category: string; severity: Severity; confidence: number; component: string | null; file: string | null; line: number | null; evidence: string; analyzer_source: string; remediation: string; status: string; occurrences: number; review_numbers: number[]; first_seen: string; last_seen: string; resolved_at: string | null; resolution_evidence: string | null; related_commit: string | null }
export interface ReviewSummaryRow { review_number: number; review_id: number; timestamp: string; finding_count: number; critical_count: number; high_count: number; medium_count: number; low_count: number; newly_introduced: number; resolved_count: number; persistent_count: number; reopened_count: number }
export interface ComparisonFinding { id: number; category: string; severity: Severity; confidence: number; component?: string | null; file?: string | null; line?: number | null; evidence: string; analyzer_source: string; remediation: string; fingerprint: string; status: string }
export interface CategoryChange { previous: number; current: number; delta: number }
export interface SeverityChange { previous: number; current: number; delta: number }
export interface ReviewComparisonItem { from_review: number; to_review: number; from_timestamp: string; to_timestamp: string; newly_introduced: ComparisonFinding[]; resolved: ComparisonFinding[]; persistent: ComparisonFinding[]; reopened: ComparisonFinding[]; category_changes: Record<string, CategoryChange>; severity_changes: Record<string, SeverityChange>; summary: string }
export interface LifecycleCounts { unique_findings: number; total_occurrences: number; active_count: number; resolved_count: number; reopened_count: number; persistent_count: number }
export interface RiskDomain { category: string; total_detected: number; current_active: number; resolved_count: number; trend: 'Improving' | 'Worsening' | 'Stable'; reviews_present: number[] }
export interface ResolutionAnalysis { resolved_count: number; persistent_count: number; resolution_ratio: number; avg_occurrences_before_resolution: number; coverage_note: string }
export interface CategoryDistributionItem { category: string; distinct_count: number; total_occurrences: number; active_count: number; resolved_count: number; critical_high_count: number }
export interface FailureHistorySummary { review_count: number; distinct_failure_count: number; open_failure_count: number; resolved_failure_count: number; categories: string[]; first_review_at: string | null; last_review_at: string | null; reopened_failure_count?: number; total_occurrences?: number; recurring_failure_count?: number; recurring_categories?: string[]; category_distribution?: CategoryDistributionItem[] }
export interface FailureHistoryResponse { project: { id: number; name: string; repository_path: string }; summary: FailureHistorySummary; findings: FailureHistoryRow[]; recurring_findings?: FailureHistoryRow[]; message: string | null }
export interface TrajectoryReview { review_number: number; timestamp: string; categories: string[]; finding_count: number }
export interface TrajectoryEdge { from: string; to: string; count: number }
export interface TrajectoryLoop { pattern: string; occurrence_count: number }
export interface TrajectoryResponse { reviews: TrajectoryReview[]; transitions: TrajectoryEdge[]; loops: TrajectoryLoop[]; message: string | null }
export interface ReviewComparison { previous: { review_number: number; timestamp: string; metrics: Record<string, number> } | null; current: { review_number: number; timestamp: string; metrics: Record<string, number> } | null; resolved_findings: FailureEvent[]; persistent_findings: FailureEvent[]; newly_introduced_findings: FailureEvent[]; changed_components: string[]; metric_changes: Record<string, { previous: number; current: number; delta: number }>; summary: string }
export interface ProjectReview { project: { path: string; file_count: number; language_mix: Record<string, number>; commit_count: number; bugfix_commit_count: number; recent_churn: string }; persistence?: { project_id: number; review_id: number; review_number: number }; events: FailureEvent[]; history: FailureHistoryItem[]; transition_graph: Transition[]; failure_loops: FailureLoop[]; failure_dna: Record<string, number>; next_failure_predictions: Prediction[]; summary: { event_count: number; open_high_or_critical: number; generated_at: string; methodology: string } }
export interface EvolutionReport { improvements: Array<{ category: string; type: string; evidence?: string }>; regressions: Array<{ category: string; type: string; evidence?: string }>; persistent_risks: Array<{ category: string; type: string }>; stability: { review_count: number; persistent_category_count: number }; dna_evolution: Array<{ dimension: string; trend: string; values: Array<{ review_number: number; value: number }> }>; prediction_evolution: Array<{ review_number: number; predictions: Array<{ category: string; probability: number; confidence: number }> }>; reviews_summary?: ReviewSummaryRow[]; review_comparisons?: ReviewComparisonItem[]; lifecycle_counts?: LifecycleCounts; risk_domains?: RiskDomain[]; resolution_analysis?: ResolutionAnalysis; insufficient_history?: boolean; insufficient_history_message?: string | null; message: string }

export interface RequirementReport { requirements: Array<{ requirement_key: string; title: string; source: string; coverage: { status: string; confidence: number; evidence: string; implementation: { files?: string[] }; tests: { files?: string[] } } }>; message: string | null }
export interface LeakageCheck { name: string; status: string; detail: string }
export interface LeakageReport { passed: boolean; checks: LeakageCheck[]; errors: string[]; warnings: string[] }

export interface DatasetQualityAudit {
  total_projects: number
  unique_repository_groups: number
  unique_real_repository_groups: number
  real_projects: number
  synthetic_temp_projects: number
  total_reviews: number
  real_reviews: number
  synthetic_reviews: number
  total_transitions: number
  real_transitions: number
  synthetic_transitions: number
  raw_observations: number
  curated_real_observations: number
  curated_primary_observations: number
  unique_feature_vectors: number
  unique_feature_target_pairs: number
  duplicate_observations: number
  duplicate_observation_percentage: number
  missing_label_percentage: number
  data_origin: string
}

export interface RegistryCandidateSummary {
  candidate_id: string
  version?: string
  algorithm: string
  stage: string
  trained_at?: string
  training_observations?: number
  dataset_version?: string
  dataset_hash?: string
  model_sha256?: string
  primary_metrics?: ResearchMetrics | null
  unseen_repository_metrics?: ResearchMetrics | null
}

export interface RegistrySummary {
  production: {
    active_version: string
    active_candidate_id: string
    active_model_relpath: string
    active_model_sha256: string | null
    updated_at?: string
  }
  candidates: RegistryCandidateSummary[]
  archived: RegistryCandidateSummary[]
  promotion_history?: Array<Record<string, unknown>>
}

export interface IngestionSummary {
  dataset_version: string
  status?: string
  discovered_git_repositories?: number
  eligible_git_repositories?: number
  distinct_repository_groups_in_dataset?: number
  curated_observations_count?: number
  distinct_failure_categories?: number
  secret_redactions_applied?: number
  exclusions_count?: number
  dataset_sha256?: string
  supported_collection_targets?: number[]
}

export interface ResearchStatus {
  dataset_version: string
  projects: number
  reviews: number
  transitions: number
  training_observations: number
  distinct_timepoints?: number
  failure_categories: number
  failure_category_list?: string[]
  date_range: { first: string; last: string } | null
  status: string
  message: string
  leakage: LeakageReport
  model_status: string
  model_available: boolean
  model_detail: string | null
  artifact: Record<string, unknown> | null
  evaluation_requirements?: { min_observations: number; min_distinct_categories: number; min_distinct_timepoints: number; min_walk_forward_train_observations: number }
  quality_audit?: DatasetQualityAudit
  registry?: RegistrySummary
  ingestion?: IngestionSummary
}

export interface ResearchMetrics { sample_count?: number; accuracy?: number; macro_f1?: number; weighted_f1?: number; macro_precision?: number; macro_recall?: number; top_2_accuracy?: number; top_3_accuracy?: number; log_loss?: number | null }
export interface ResearchModelResult { model: string; status: string; metrics: ResearchMetrics | null; n_cutoffs?: number; classes?: string[] }
export interface ResearchCutoff { cutoff: number; train_size: number; test_size: number; train_time_range: { start: string; end: string }; test_time_range: { start: string; end: string }; predictions?: string[]; actual?: string[]; metrics?: ResearchMetrics | null; models?: Record<string, unknown> }
export interface WalkForwardReport { status: string; message: string; n_cutoffs: number; cutoffs: ResearchCutoff[]; total_test_predictions?: number; global_classes?: string[] }
export interface AblationRow { variant: string; removed: string | null; feature_count?: number; status: string; metrics: ResearchMetrics; delta_macro_f1: number | null }
export interface AblationReport { status: string; results: AblationRow[]; n_cutoffs: number; message?: string; report_path?: string }
export interface CalibrationBin { lower: number; upper: number; count: number; mean_predicted_confidence: number | null; empirical_accuracy: number | null }
export interface CalibrationReport { available: boolean; reason?: string; sample_count?: number; brier_score?: number; expected_calibration_error?: number; reliability_bins?: CalibrationBin[]; methodology?: string }
export interface TrainingReport { trained: boolean; reason: string | null; path: string | null; metadata: Record<string, unknown> | null }
export interface ResearchEvaluation { status: string; refused?: boolean; methodology: string; results: ResearchModelResult[]; walk_forward_splits: number; leakage: LeakageReport; walk_forward: WalkForwardReport; ablation: AblationReport; calibration: CalibrationReport; training: TrainingReport; train_observations?: number }
export interface ResearchEvaluationResponse { dataset: ResearchStatus; evaluation: ResearchEvaluation; report_path: string; registry?: RegistrySummary; ingestion?: IngestionSummary }
export interface ResearchDatasetResponse { status: ResearchStatus; project_list: Array<{ id: number; name: string; repository_path: string }>; observations: Array<{ project_id: number; review_id: number; review_number: number; timestamp: string; target: string; features: Record<string, number> }> }
export interface ResearchPredictionFeature { feature: string; feature_group?: string; description?: string; value: number; standardized_value?: number; coefficient?: number; contribution: number; direction: string }

export interface CodeIntelligenceRiskRegion {
  file: string
  start_line: number
  end_line: number
  symbol?: string | null
  category: string
  category_label?: string
  severity: Severity
  state: 'verified_finding' | 'potential_risk' | 'model_ranked_candidate' | 'unknown_insufficient_evidence' | string
  priority_score: number
  title: string
  explanation: string
  code_excerpt?: string
  signals?: string[]
}

export interface CodeIntelligencePreview {
  available: boolean
  summary?: {
    indexed_files: number
    code_files: number
    test_files: number
    total_lines: number
    total_symbols: number
    module_test_reference_ratio: number
    verified_line_findings_count: number
    localized_risk_regions_count: number
    state_counts?: Record<string, number>
  }
  top_risk_regions?: CodeIntelligenceRiskRegion[]
}

export interface RemediationSuggestion {
  summary: string
  why_it_matters: string
  evidence_references: string[]
  suggested_fix: string
  patch: string
  tests_to_add: string[]
  validation_steps: string[]
  potential_side_effects: string[]
  confidence: number
  limitations: string[]
}

export interface RemediationResponse {
  available: boolean
  llm_used: boolean
  provider: string
  model: string
  message: string
  evidence_state: string
  secret_redactions_applied: number
  remediation: RemediationSuggestion
  grounding_validation: {
    passed: boolean
    referenced_files_exist: boolean
    referenced_lines_valid: boolean
    respects_prediction_vs_verified_distinction: boolean
  }
  patch_validation: {
    has_patch: boolean
    target_file_exists: boolean
    original_lines_fresh: boolean
    syntax_valid: boolean
    auto_applied: boolean
    review_only: boolean
    status: string
  }
}

export interface ResearchPrediction {
  available: boolean
  project_id: number
  project_name?: string
  reason?: string
  message?: string
  predicted_category?: string | null
  predicted_label?: string | null
  predictions?: Array<{
    rank?: number
    category: string
    label?: string
    probability: number
    model_score?: number
    calibrated_probability?: number | null
    historical_frequency?: number
    historical_occurrences?: number
    deterministic_risk_score?: number
  }>
  supporting_features?: ResearchPredictionFeature[]
  uncertainty?: {
    level: 'low' | 'moderate' | 'high' | string
    normalized_entropy: number
    top_1_margin: number
    project_review_count: number
    is_calibrated_probability: boolean
    calibration_note: string
  }
  score_semantics?: Record<string, string>
  code_intelligence?: CodeIntelligencePreview
  historical_evidence?: Record<string, unknown>
  model?: Record<string, unknown>
  training_metadata?: Record<string, unknown>
  disclaimer?: string
}

export interface UserProfile {
  id: number
  email: string
  username: string
  full_name?: string | null
  role?: string | null
  preferences?: Record<string, unknown>
  created_at?: string | null
}

export interface NotificationItem {
  id: number
  user_id: number
  project_id?: number | null
  type: string
  title: string
  message: string
  data?: Record<string, unknown>
  seen: boolean
  created_at?: string | null
}

export interface ActivityEventItem {
  id: number
  project_id: number
  event_type: string
  title: string
  description: string
  metadata?: Record<string, unknown>
  created_at?: string | null
}

export interface AnalysisCoverageReport {
  overall_status: 'COMPLETE' | 'PARTIAL' | 'FAILED' | 'UNSUPPORTED' | 'NOT_APPLICABLE' | string
  coverage_percentage: number
  total_files: number
  supported_files: number
  analyzed_files: number
  skipped_files: number
  excluded_files: number
  duration_ms: number
  generated_at?: string
  analyzers: Record<string, {
    status: string
    findings_count: number
    duration_ms: number
    error_message?: string | null
  }>
}

export interface ProjectItem {
  id: number
  name: string
  repository_path: string
  source_type: 'local' | 'github'
  repository_url?: string | null
  branch?: string | null
  current_commit_sha?: string | null
  monitoring_status: string
  last_analyzed_at?: string | null
  created_at?: string | null
  description?: string | null
  summary: {
    reviews_count: number
    active_findings_count: number
    critical_findings_count: number
    high_findings_count: number
    latest_coverage: number
  }
}

export interface ProjectFindingItem {
  id: number
  review_id: number
  title?: string | null
  category: string
  severity: string
  confidence: number
  component?: string | null
  file?: string | null
  line?: number | null
  evidence: string
  analyzer_source: string
  remediation: string
  status: string
  fingerprint: string
  detected_at?: string | null
  suppressed: boolean
  suppression_reason?: string | null
  suppression_type?: string | null
  suppressed_at?: string | null
}
