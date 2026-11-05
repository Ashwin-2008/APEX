import { request } from './client'
import type { Prediction, PredictionExplanation } from '../types/entities'

export interface PredictionRunPayload {
  task: 'FAILURE_FORECAST' | 'CHANGE_RISK' | 'REGRESSION_RISK' | 'REMEDIATION_OUTCOME'
  target_entity?: string
  horizon?: 'NEXT_CHANGE' | '7_DAYS' | '30_DAYS'
  changed_files?: string[]
  changed_symbols?: string[]
  graph_blast_radius_score?: number
  graph_dependent_tests?: string[]
  patch_size_lines?: number
}

export interface PredictionFeedbackPayload {
  prediction_id: string
  feedback_category: 'CORRECT' | 'INCORRECT' | 'PARTIALLY_CORRECT' | 'UNVERIFIABLE' | 'NOT_APPLICABLE'
  notes?: string
}

export interface PredictivePrediction {
  id?: number
  prediction_id: string
  project_id: number
  target_entity: string
  prediction_task: string
  prediction_horizon: string
  model_id: string
  model_version: string
  dataset_version: string
  feature_schema_version: string
  state: 'PREDICTION_AVAILABLE' | 'LOW_CONFIDENCE' | 'INSUFFICIENT_DATA' | 'OUT_OF_DISTRIBUTION' | 'CALIBRATION_UNCERTAIN' | 'MODEL_UNAVAILABLE' | 'NOT_SUPPORTED'
  predicted_outcome: string
  probability: number | null
  confidence: number
  supporting_evidence: Record<string, any>
  explanation: Record<string, any>
  limitations: string[]
  created_at?: string
  is_abstention?: boolean
  reason?: string
}

export interface PredictiveOverview {
  project_id: number
  tasks: Record<string, PredictivePrediction>
  generated_at: string
}

export interface PredictiveMetrics {
  project_id: number
  feedback_metrics: {
    total_feedback_events: number
    distribution: Record<string, number>
    user_confirmed_accuracy_rate: number
    eligible_for_retraining_review: boolean
  }
  models_registry: Record<string, any>
  baseline_evaluations: Record<string, any>
  total_project_observations: number
}

// Student AMPA endpoints (preserved for backwards compatibility)
export const getLatestPrediction = (id: number) => request<Prediction>(`/predictions/${id}/latest`)
export const getLatestExplanation = (id: number) => request<PredictionExplanation>(`/predictions/${id}/latest/explanation`)

// APEX Phase 4 Predictive Intelligence API
export const getProjectPredictions = (projectId: number) =>
  request<PredictiveOverview>(`/project-reviews/${projectId}/predictions`)

export const getPredictionDetail = (projectId: number, predictionId: string) =>
  request<PredictivePrediction>(`/project-reviews/${projectId}/predictions/${predictionId}`)

export const runProjectPrediction = (projectId: number, payload: PredictionRunPayload) =>
  request<PredictivePrediction>(`/project-reviews/${projectId}/predictions/run`, {
    method: 'POST',
    body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' },
  })

export const getProjectPredictionHistory = (projectId: number, limit = 50) =>
  request<PredictivePrediction[]>(`/project-reviews/${projectId}/prediction-history?limit=${limit}`)

export const getProjectPredictionMetrics = (projectId: number) =>
  request<PredictiveMetrics>(`/project-reviews/${projectId}/prediction-metrics`)

export const getProjectPredictionDatasets = (projectId: number) =>
  request<{ project_id: number; datasets: any[] }>(`/project-reviews/${projectId}/prediction-datasets`)

export const getProjectPredictionModels = (projectId: number) =>
  request<Record<string, any>>(`/project-reviews/${projectId}/prediction-models`)

export const getProjectPredictiveBenchmarks = (projectId: number) =>
  request<any>(`/project-reviews/${projectId}/predictive-benchmarks`)

export const recordPredictionFeedback = (projectId: number, payload: PredictionFeedbackPayload) =>
  request<{ status: string; feedback_id: number; prediction_id: string; category: string }>(
    `/project-reviews/${projectId}/prediction-feedback`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
    }
  )
