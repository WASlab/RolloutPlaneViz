from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSummary(Model):
    run_id: str
    name: str
    status: str
    model: str
    environment: str
    started_at_ns: int
    current_bundle: str
    algorithm: str | None = None
    finished_at_ns: int | None = None
    current_checkpoint: str | None = None


class BundleSummary(Model):
    bundle_id: str
    target: str
    tokenizer: str
    engine: str
    speculator: str | None = None
    policy_step: int | None = None
    target_digest: str | None = None
    tokenizer_digest: str | None = None
    engine_digest: str | None = None
    speculator_digest: str | None = None
    sampling: dict[str, object] = Field(default_factory=dict)
    environment_contract: str | None = None
    reward_contract: str | None = None
    created_at_ns: int | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class Point(Model):
    timestamp_ns: int
    timestamp_ms: int | None = None
    value: float
    bundle_id: str

    @model_validator(mode="after")
    def browser_timestamp(self) -> Self:
        # JavaScript numbers cannot represent contemporary nanosecond epochs.
        # Preserve the exact integer for reports and send a safe millisecond
        # projection for charts.
        if self.timestamp_ms is None:
            self.timestamp_ms = self.timestamp_ns // 1_000_000
        return self


class Series(Model):
    name: str
    unit: str
    points: list[Point]


class KPI(Model):
    label: str
    value: float
    unit: str
    delta: float | None = None
    direction: str = "neutral"


class Breakdown(Model):
    label: str
    value: float


class TaskResult(Model):
    task: str
    family: str
    attempts: int
    success_rate: float
    median_reward: float
    median_seconds: float


class RolloutRow(Model):
    rollout_id: str
    task: str
    task_family: str = "unlabeled"
    bundle_id: str
    reward: float
    duration_seconds: float
    turns: int
    status: str
    termination_reason: str
    started_at_ns: int = Field(default=0, ge=0)
    ended_at_ns: int = Field(default=0, ge=0)
    worker_id: str | None = None
    attempt: int = Field(default=0, ge=0)
    decision_chunk: int = Field(default=0, ge=0)


class TraceEvent(Model):
    sequence: int
    elapsed_seconds: float
    event_type: str
    summary: str
    reward: float | None = None


class RolloutTrace(Model):
    rollout: RolloutRow
    events: list[TraceEvent]


class Dashboard(Model):
    generated_at_ns: int
    run: RunSummary
    kpis: list[KPI]
    series: list[Series]
    wallclock: list[Breakdown]
    terminations: list[Breakdown]
    tasks: list[TaskResult]
    rollouts: list[RolloutRow]
    bundles: list[str]
    bundle_details: list[BundleSummary] = Field(default_factory=list)


ComparisonMethod = Literal["normal_independent", "moving_block_bootstrap"]


class ComparisonRequest(Model):
    run_id: str
    baseline_bundle: str
    candidate_bundle: str
    method: ComparisonMethod = "moving_block_bootstrap"
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1)
    resamples: int = Field(default=2_000, ge=100, le=50_000)
    block_length: int | None = Field(default=None, ge=1, le=10_000)
    metric_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def distinct_bundles(self) -> Self:
        if self.baseline_bundle == self.candidate_bundle:
            raise ValueError("comparison bundles must differ")
        return self


class Estimate(Model):
    metric: str
    unit: str
    baseline_mean: float
    candidate_mean: float
    absolute_delta: float
    relative_delta: float | None
    confidence_low: float
    confidence_high: float
    sample_count_baseline: int
    sample_count_candidate: int
    standard_error: float | None = None
    standardized_effect: float | None = None
    probability_candidate_greater: float | None = None
    block_length: int | None = None


class Comparison(Model):
    run_id: str
    baseline_bundle: str
    candidate_bundle: str
    method: ComparisonMethod
    confidence_level: float
    resamples: int | None = None
    generated_at_ns: int
    source_generated_at_ns: int
    data_digest: str
    request: ComparisonRequest
    estimates: list[Estimate]
    series: list[Series]
    bundle_details: list[BundleSummary] = Field(default_factory=list)


ReportSection = Literal["overview", "learning", "inference", "tasks", "rollouts", "provenance"]


def default_report_sections() -> list[ReportSection]:
    return [
        "overview",
        "learning",
        "inference",
        "tasks",
        "rollouts",
        "provenance",
    ]


class ReportRequest(Model):
    run_id: str
    baseline_bundle: str | None = None
    candidate_bundle: str | None = None
    range_start_percent: float = Field(default=0, ge=0, le=100)
    range_end_percent: float = Field(default=100, ge=0, le=100)
    range_start_ns: int | None = Field(default=None, ge=0)
    range_end_ns: int | None = Field(default=None, ge=0)
    sections: list[ReportSection] = Field(default_factory=default_report_sections)

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.range_start_percent >= self.range_end_percent:
            raise ValueError("report range must have positive width")
        if (self.range_start_ns is None) != (self.range_end_ns is None):
            raise ValueError("both exact range boundaries must be supplied together")
        if (
            self.range_start_ns is not None
            and self.range_end_ns is not None
            and self.range_start_ns >= self.range_end_ns
        ):
            raise ValueError("exact report range must have positive width")
        if not self.sections:
            raise ValueError("at least one report section is required")
        self.sections = list(dict.fromkeys(self.sections))
        return self


class ReportReceipt(Model):
    report_id: str
    created_at_ns: int
    source_generated_at_ns: int
    data_digest: str
    request: ReportRequest
    metric_count: int
    rollout_count: int
    task_count: int
    range_start_ns: int
    range_end_ns: int
    source_kind: str


class ReportDocument(Model):
    receipt: ReportReceipt
    dashboard: Dashboard


class ReportVerification(Model):
    report_id: str
    verified: bool
    expected_digest: str
    actual_digest: str
    verified_at_ns: int


class RolloutPage(Model):
    items: list[RolloutRow]
    total: int
    offset: int
    limit: int


class ServiceMetadata(Model):
    application: str = "RolloutPlane Viz"
    version: str
    api_version: str = "v1"
    source_kind: str
    refresh_seconds: float
    max_series_points: int
    report_store: str
    features: list[str]
