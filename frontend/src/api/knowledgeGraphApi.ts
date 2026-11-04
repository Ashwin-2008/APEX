import { request } from './client'

export interface GraphNode {
  canonical_id: string
  project_id: number
  entity_type: string
  name: string
  qualified_name: string
  file_path: string
  start_line: number
  end_line: number
  metadata: Record<string, any>
}

export interface GraphEdge {
  source_canonical_id: string
  target_canonical_id: string
  rel_type: string
  project_id: number
  confidence: number
  evidence_location?: string | null
  analyzer_source: string
  provenance: Record<string, any>
}

export interface GraphOverview {
  project_id: number
  version_number: number
  commit_sha?: string | null
  node_count: number
  edge_count: number
  entity_type_counts: Record<string, number>
  relationship_type_counts: Record<string, number>
  consistency: {
    is_consistent: boolean
    node_count: number
    edge_count: number
    duplicate_edges: number
    dangling_sources_count: number
    dangling_targets_count: number
    unresolved_edges_count: number
  }
  created_at?: string | null
}

export interface ImpactedComponent {
  canonical_id: string
  name: string
  entity_type: string
  file_path: string
  impact_level: 'DIRECTLY_AFFECTED' | 'TRANSITIVELY_AFFECTED' | 'POTENTIALLY_AFFECTED' | 'UNKNOWN_IMPACT'
  depth: number
  confidence: number
  evidence_path: string[]
  relationship_to_source: string
  details: string
}

export interface ChangeImpactReport {
  target_canonical_ids: string[]
  total_impacted_count: number
  directly_affected_count: number
  transitively_affected_count: number
  potentially_affected_count: number
  impacted_components: ImpactedComponent[]
  affected_apis: any[]
  affected_tables: any[]
  affected_tests: any[]
  affected_findings: any[]
  potential_breaking_changes: string[]
}

export interface BlastRadiusReport {
  targets: string[]
  blast_radius_score: number
  risk_level: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  direct_symbols_count: number
  transitive_symbols_count: number
  affected_modules: string[]
  affected_apis_count: number
  affected_tables_count: number
  affected_tests_count: number
  boundaries_crossed: string[]
  risk_factors: string[]
  impact_report: ChangeImpactReport
  measured_properties?: {
    directly_affected_symbols_count: number
    transitively_affected_symbols_count: number
    affected_modules: string[]
    affected_apis_count: number
    affected_tables_count: number
    affected_tests_count: number
    max_dependency_depth: number
    total_fan_in: number
    total_fan_out: number
    boundaries_crossed: string[]
  }
  heuristic_factors?: {
    authentication_sensitivity: boolean
    public_api_exposure: boolean
    database_schema_impact: boolean
    core_infrastructure_involvement: boolean
    critical_component_involvement: boolean
    unresolved_dependency_uncertainty: boolean
  }
  score_breakdown?: {
    measured_structural_score: number
    heuristic_risk_score: number
    combined_score: number
  }
  score_explanation?: string
}

export interface RecommendedTest {
  test_id: string
  test_name: string
  file_path: string
  tier: 'DIRECT_TEST' | 'TRANSITIVE_TEST' | 'INTEGRATION_TEST'
  confidence: number
  reason: string
  target_symbol: string
  classification?: string
  evidence_path?: string[]
  execution_status?: string
}

export interface ArchitectureMetricsReport {
  total_modules: number
  circular_dependencies: string[][]
  high_fan_in_modules: Array<{ module: string; fan_in: number }>
  high_fan_out_modules: Array<{ module: string; fan_out: number }>
  orphaned_modules: string[]
  unresolved_imports: Array<{ source: string; target: string; location?: string }>
  layer_violations: Array<{ source: string; target: string; rule: string; severity: string; evidence?: string }>
}

export interface SubgraphResponse {
  center_id: string
  radius: number
  total_nodes: number
  total_edges: number
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface TechnologyCoverageSummary {
  technology: string
  files_discovered: number
  files_parsed: number
  symbols_extracted: number
  dimension_status: Record<string, string>
  coverage_score: number
  notes: string[]
  file_discovery_coverage?: number
  symbol_extraction_coverage?: number
  relationship_extraction_coverage?: number
  framework_specific_coverage?: number
  cross_language_resolution_coverage?: number
  status?: string
}

export interface GraphCoverageReport {
  project_id: number
  total_files: number
  total_nodes: number
  total_edges: number
  unresolved_relationships_count: number
  technologies: Record<string, TechnologyCoverageSummary>
  overall_coverage_percentage: number
  unresolved_reasons: Array<{ source: string; target: string; expression: string; reason: string }>
  dimensional_breakdown?: {
    file_discovery: Record<string, any>
    symbol_extraction: Record<string, any>
    relationship_extraction: Record<string, any>
    framework_specific: Record<string, any>
    cross_language_resolution: Record<string, any>
  }
}

export interface IdentityTransitionRecord {
  id: number
  from_version_id: number | null
  to_version_id: number
  old_canonical_id: string
  new_canonical_id: string
  transition_type: string
  confidence: number
  evidence: Record<string, any>
  created_at: string | null
}

export interface GraphVersionSummary {
  id: number
  version_number: number
  status: string
  is_current: boolean
  commit_sha: string | null
  node_count: number
  edge_count: number
  metadata: Record<string, any>
  created_at: string | null
}

export interface VersionDiffReport {
  project_id: number
  version_a_number: number
  version_b_number: number
  added_nodes_count: number
  removed_nodes_count: number
  modified_nodes_count: number
  renamed_entities_count: number
  added_edges_count: number
  removed_edges_count: number
  changed_relationships_count: number
  added_nodes: Array<{ canonical_id: string; name: string; entity_type: string; file_path: string; start_line: number }>
  removed_nodes: Array<{ canonical_id: string; name: string; entity_type: string; file_path: string; start_line: number }>
  modified_nodes: Array<{ canonical_id: string; name: string; entity_type: string; file_path: string; old_lines: [number, number]; new_lines: [number, number] }>
  renamed_entities: Array<{ old_canonical_id: string; new_canonical_id: string; transition_type: string; confidence: number; evidence: Record<string, any> }>
  added_edges: Array<{ source: string; target: string; rel_type: string; confidence: number }>
  removed_edges: Array<{ source: string; target: string; rel_type: string; confidence: number }>
  changed_relationships: Array<{ source: string; target: string; rel_type: string; old_confidence: number; new_confidence: number; old_resolution?: string; new_resolution?: string }>
  split_entities?: Array<{ old_canonical_id: string; new_canonical_id: string; transition_type: string; confidence: number; evidence: Record<string, any> }>
  merged_entities?: Array<{ old_canonical_id: string; new_canonical_id: string; transition_type: string; confidence: number; evidence: Record<string, any> }>
}

export async function extractGraph(
  projectId: number | string,
  forceFullRebuild: boolean = false,
  changedFiles: string[] = [],
  deletedFiles: string[] = []
): Promise<{ project_id: number; version_number: number; node_count: number; edge_count: number }> {
  return request(`/project-reviews/${projectId}/graph/extract`, {
    method: 'POST',
    body: JSON.stringify({
      force_full_rebuild: forceFullRebuild,
      changed_files: changedFiles,
      deleted_files: deletedFiles,
    }),
  })
}

export async function getGraphOverview(projectId: number | string): Promise<GraphOverview> {
  return request(`/project-reviews/${projectId}/graph/overview`)
}

export async function queryGraphNodes(
  projectId: number | string,
  params: { entity_type?: string; search?: string; file_path?: string; skip?: number; limit?: number } = {}
): Promise<{ total: number; skip: number; limit: number; nodes: GraphNode[] }> {
  const q = new URLSearchParams()
  if (params.entity_type) q.set('entity_type', params.entity_type)
  if (params.search) q.set('search', params.search)
  if (params.file_path) q.set('file_path', params.file_path)
  if (params.skip !== undefined) q.set('skip', String(params.skip))
  if (params.limit !== undefined) q.set('limit', String(params.limit))
  return request(`/project-reviews/${projectId}/graph/nodes?${q.toString()}`)
}

export async function queryGraphEdges(
  projectId: number | string,
  params: { rel_type?: string; source_id?: string; target_id?: string; skip?: number; limit?: number } = {}
): Promise<{ total: number; skip: number; limit: number; edges: GraphEdge[] }> {
  const q = new URLSearchParams()
  if (params.rel_type) q.set('rel_type', params.rel_type)
  if (params.source_id) q.set('source_id', params.source_id)
  if (params.target_id) q.set('target_id', params.target_id)
  if (params.skip !== undefined) q.set('skip', String(params.skip))
  if (params.limit !== undefined) q.set('limit', String(params.limit))
  return request(`/project-reviews/${projectId}/graph/edges?${q.toString()}`)
}

export async function analyzeImpact(
  projectId: number | string,
  targets: string[],
  maxDepth: number = 5
): Promise<ChangeImpactReport> {
  return request(`/project-reviews/${projectId}/graph/impact`, {
    method: 'POST',
    body: JSON.stringify({ targets, max_depth: maxDepth }),
  })
}

export async function computeBlastRadius(
  projectId: number | string,
  targets: string[],
  maxDepth: number = 5
): Promise<BlastRadiusReport> {
  return request(`/project-reviews/${projectId}/graph/blast-radius`, {
    method: 'POST',
    body: JSON.stringify({ targets, max_depth: maxDepth }),
  })
}

export async function getRecommendedTests(
  projectId: number | string,
  targets: string[],
  maxDepth: number = 4
): Promise<{ project_id: number; targets: string[]; recommended_tests: RecommendedTest[] }> {
  return request(`/project-reviews/${projectId}/graph/recommended-tests`, {
    method: 'POST',
    body: JSON.stringify({ targets, max_depth: maxDepth }),
  })
}

export async function getArchitectureMetrics(
  projectId: number | string
): Promise<ArchitectureMetricsReport> {
  return request(`/project-reviews/${projectId}/graph/architecture`)
}

export async function getSubgraph(
  projectId: number | string,
  centerId: string,
  radius: number = 2,
  limit: number = 80
): Promise<SubgraphResponse> {
  const q = new URLSearchParams({ center_id: centerId, radius: String(radius), limit: String(limit) })
  return request(`/project-reviews/${projectId}/graph/subgraph?${q.toString()}`)
}

export async function getGraphCoverage(projectId: number | string): Promise<GraphCoverageReport> {
  return request(`/project-reviews/${projectId}/graph/coverage`)
}

export async function getIdentityTransitions(
  projectId: number | string,
  toVersionId?: number
): Promise<IdentityTransitionRecord[]> {
  const q = new URLSearchParams()
  if (toVersionId !== undefined) q.set('to_version_id', String(toVersionId))
  return request(`/project-reviews/${projectId}/graph/transitions?${q.toString()}`)
}

export async function listGraphVersions(projectId: number | string): Promise<GraphVersionSummary[]> {
  return request(`/project-reviews/${projectId}/graph/versions`)
}

export async function compareGraphVersions(
  projectId: number | string,
  v1: number,
  v2: number
): Promise<VersionDiffReport> {
  const q = new URLSearchParams({ v1: String(v1), v2: String(v2) })
  return request(`/project-reviews/${projectId}/graph/compare?${q.toString()}`)
}

export async function recoverGraphUpdates(
  projectId: number | string
): Promise<{ project_id: number; recovered_count: number; status: string }> {
  return request(`/project-reviews/${projectId}/graph/recover`, { method: 'POST' })
}
