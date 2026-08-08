from __future__ import annotations

from typing import Self

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


class Point(Model):
    timestamp_ns: int
    value: float
    bundle_id: str


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
    bundle_id: str
    reward: float
    duration_seconds: float
    turns: int
    status: str
    termination_reason: str


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


class Comparison(Model):
    run_id: str
    baseline_bundle: str
    candidate_bundle: str
    estimates: list[Estimate]
    series: list[Series]


class ReportRequest(Model):
    run_id: str
    baseline_bundle: str | None = None
    candidate_bundle: str | None = None
    range_start_percent: float = Field(default=0, ge=0, le=100)
    range_end_percent: float = Field(default=100, ge=0, le=100)
    sections: list[str] = Field(
        default_factory=lambda: ["overview", "learning", "inference", "tasks", "rollouts"]
    )

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.range_start_percent >= self.range_end_percent:
            raise ValueError("report range must have positive width")
        return self


class ReportReceipt(Model):
    report_id: str
    created_at_ns: int
    source_generated_at_ns: int
    data_digest: str
    request: ReportRequest
    metric_count: int
    rollout_count: int
