export interface RunSummary {
  run_id: string
  name: string
  status: string
  model: string
  environment: string
  started_at_ns: number
  current_bundle: string
}

export interface Point {
  timestamp_ns: number
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
  bundle_id: string
  reward: number
  duration_seconds: number
  turns: number
  status: string
  termination_reason: string
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
}

export interface Comparison {
  run_id: string
  baseline_bundle: string
  candidate_bundle: string
  estimates: Estimate[]
  series: Series[]
}

export interface ReportRequest {
  run_id: string
  baseline_bundle: string | null
  candidate_bundle: string | null
  range_start_percent: number
  range_end_percent: number
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
}
