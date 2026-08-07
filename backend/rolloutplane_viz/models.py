from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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
