export interface RunSummary {
  run_id: string
  name: string
  status: string
  model: string
  environment: string
  started_at_ns: number
  current_bundle: string
  algorithm: string | null
  finished_at_ns: number | null
  current_checkpoint: string | null
}

export interface BundleSummary {
  bundle_id: string
  target: string
  tokenizer: string
  engine: string
  speculator: string | null
  policy_step: number | null
  target_digest: string | null
  tokenizer_digest: string | null
  engine_digest: string | null
  speculator_digest: string | null
  sampling: Record<string, unknown>
  environment_contract: string | null
  reward_contract: string | null
  created_at_ns: number | null
  labels: Record<string, string>
}

export interface Point {
  timestamp_ns: number
  timestamp_ms: number
  value: number
  bundle_id: string
}

export interface Series {
  name: string
  unit: string
  points: Point[]
}

export interface KPI {
  label: string
  value: number
  unit: string
  delta: number | null
  direction: string
}

export interface Breakdown { label: string; value: number }

export interface TaskResult {
  task: string
  family: string
  attempts: number
  success_rate: number
  median_reward: number
  median_seconds: number
}

export interface RolloutRow {
  rollout_id: string
  task: string
  task_family: string
  bundle_id: string
  reward: number
  duration_seconds: number
  turns: number
  status: string
  termination_reason: string
  started_at_ns: number
  ended_at_ns: number
  worker_id: string | null
  attempt: number
  decision_chunk: number
}

export interface TraceEvent {
  sequence: number
  elapsed_seconds: number
  event_type: string
  summary: string
  reward: number | null
}

export interface RolloutTrace { rollout: RolloutRow; events: TraceEvent[] }

export interface Dashboard {
  generated_at_ns: number
  run: RunSummary
  kpis: KPI[]
  series: Series[]
  wallclock: Breakdown[]
  terminations: Breakdown[]
  tasks: TaskResult[]
  rollouts: RolloutRow[]
  bundles: string[]
  bundle_details: BundleSummary[]
}

export type ComparisonMethod = 'normal_independent' | 'moving_block_bootstrap'

export interface ComparisonRequest {
  run_id: string
  baseline_bundle: string
  candidate_bundle: string
  method: ComparisonMethod
  confidence_level: number
  resamples: number
  block_length: number | null
  metric_names: string[]
}

export interface Estimate {
  metric: string
  unit: string
  baseline_mean: number
  candidate_mean: number
  absolute_delta: number
  relative_delta: number | null
  confidence_low: number
  confidence_high: number
  sample_count_baseline: number
  sample_count_candidate: number
  standard_error: number | null
  standardized_effect: number | null
  probability_candidate_greater: number | null
  block_length: number | null
}

export interface Comparison {
  run_id: string
  baseline_bundle: string
  candidate_bundle: string
  method: ComparisonMethod
  confidence_level: number
  resamples: number | null
  generated_at_ns: number
  source_generated_at_ns: number
  data_digest: string
  request: ComparisonRequest
  estimates: Estimate[]
  series: Series[]
  bundle_details: BundleSummary[]
}

export interface ReportRequest {
  run_id: string
  baseline_bundle: string | null
  candidate_bundle: string | null
  range_start_percent: number
  range_end_percent: number
  range_start_ns?: number | null
  range_end_ns?: number | null
  sections: string[]
}

export interface ReportReceipt {
  report_id: string
  created_at_ns: number
  source_generated_at_ns: number
  data_digest: string
  request: ReportRequest
  metric_count: number
  rollout_count: number
  task_count: number
  range_start_ns: number
  range_end_ns: number
  source_kind: string
}

export interface ReportDocument { receipt: ReportReceipt; dashboard: Dashboard }

export interface ReportVerification {
  report_id: string
  verified: boolean
  expected_digest: string
  actual_digest: string
  verified_at_ns: number
}

export interface RolloutPage {
  items: RolloutRow[]
  total: number
  offset: number
  limit: number
}

export interface ServiceMetadata {
  application: string
  version: string
  api_version: string
  source_kind: string
  refresh_seconds: number
  max_series_points: number
  report_store: string
  features: string[]
}
