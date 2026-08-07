from __future__ import annotations

import asyncio
import math
import random
import time
from abc import ABC, abstractmethod
from collections import Counter, defaultdict

from rolloutplane.client import RemoteRolloutPlane
from rolloutplane.models import EventType, RolloutEvent

from rolloutplane_viz.models import (
    KPI,
    Breakdown,
    Dashboard,
    Point,
    RolloutRow,
    RolloutTrace,
    RunSummary,
    Series,
    TaskResult,
    TraceEvent,
)


class DataSource(ABC):
    @abstractmethod
    async def runs(self) -> list[RunSummary]: ...

    @abstractmethod
    async def dashboard(self, run_id: str) -> Dashboard: ...

    @abstractmethod
    async def trace(self, rollout_id: str) -> RolloutTrace | None: ...


class DemoSource(DataSource):
    """Seeded, realistic data for development and visual regression tests."""

    def __init__(self) -> None:
        self._random = random.Random(74019)
        self._start = 1_786_080_000_000_000_000
        self._run = RunSummary(
            run_id="repair-grpo-4b-v1",
            name="Repair GRPO · 4B · v1",
            status="running",
            model="Qwen3-4B + DSpark",
            environment="Factorio repair curriculum",
            started_at_ns=self._start,
            current_bundle="theta-184 / phi-12",
        )
        self._dashboard = self._build_dashboard()
        self._traces = {row.rollout_id: self._build_trace(row) for row in self._dashboard.rollouts}

    async def runs(self) -> list[RunSummary]:
        return [self._run]

    async def dashboard(self, run_id: str) -> Dashboard:
        if run_id != self._run.run_id:
            raise KeyError(run_id)
        return self._dashboard.model_copy(update={"generated_at_ns": time.time_ns()})

    async def trace(self, rollout_id: str) -> RolloutTrace | None:
        return self._traces.get(rollout_id)

    def _build_dashboard(self) -> Dashboard:
        bundles = ["theta-042 / phi-04", "theta-108 / phi-07", "theta-184 / phi-12"]
        names = [
            ("reward.mean", "reward"),
            ("success.rate", "ratio"),
            ("throughput.target_tokens", "token/s"),
            ("speculation.acceptance", "ratio"),
        ]
        series: list[Series] = []
        for metric, unit in names:
            points: list[Point] = []
            for step in range(72):
                phase = min(step // 24, 2)
                progress = step / 71
                noise = self._random.uniform(-0.025, 0.025)
                if metric == "reward.mean":
                    value = 0.18 + 0.62 * progress + noise
                elif metric == "success.rate":
                    value = 0.11 + 0.71 * progress + noise
                elif metric == "throughput.target_tokens":
                    value = 88 + 51 * progress + 7 * math.sin(step / 6) + noise * 40
                else:
                    value = 0.79 - 0.16 * (step % 24) / 23 + phase * 0.045 + noise
                points.append(
                    Point(
                        timestamp_ns=self._start + step * 600_000_000_000,
                        value=round(value, 4),
                        bundle_id=bundles[phase],
                    )
                )
            series.append(Series(name=metric, unit=unit, points=points))
        tasks = [
            TaskResult(
                task="Reversed inserter",
                family="repair",
                attempts=96,
                success_rate=0.91,
                median_reward=0.94,
                median_seconds=18.2,
            ),
            TaskResult(
                task="Missing power pole",
                family="repair",
                attempts=88,
                success_rate=0.86,
                median_reward=0.89,
                median_seconds=22.8,
            ),
            TaskResult(
                task="Wrong assembler recipe",
                family="repair",
                attempts=82,
                success_rate=0.79,
                median_reward=0.82,
                median_seconds=31.4,
            ),
            TaskResult(
                task="Starved furnace line",
                family="diagnosis",
                attempts=75,
                success_rate=0.68,
                median_reward=0.71,
                median_seconds=48.6,
            ),
            TaskResult(
                task="Belt throughput +25%",
                family="expansion",
                attempts=64,
                success_rate=0.56,
                median_reward=0.63,
                median_seconds=76.1,
            ),
            TaskResult(
                task="Recover depleted patch",
                family="recovery",
                attempts=41,
                success_rate=0.34,
                median_reward=0.45,
                median_seconds=119.7,
            ),
        ]
        reasons = [
            "success",
            "turn limit",
            "invalid program",
            "no progress",
            "agent death",
            "environment fault",
        ]
        task_names = [task.task for task in tasks]
        rollouts: list[RolloutRow] = []
        for index in range(18):
            reason = reasons[0] if index < 11 else reasons[1 + (index % 5)]
            rollouts.append(
                RolloutRow(
                    rollout_id=f"fo-{18420 + index}",
                    task=task_names[index % len(task_names)],
                    bundle_id=bundles[2 if index < 12 else 1],
                    reward=round(
                        self._random.uniform(0.35, 0.98)
                        if reason == "success"
                        else self._random.uniform(-0.08, 0.48),
                        3,
                    ),
                    duration_seconds=round(self._random.uniform(17, 128), 1),
                    turns=self._random.randint(2, 9),
                    status="completed" if reason == "success" else "truncated",
                    termination_reason=reason,
                )
            )
        return Dashboard(
            generated_at_ns=time.time_ns(),
            run=self._run,
            kpis=[
                KPI(
                    label="Validation success",
                    value=0.816,
                    unit="ratio",
                    delta=0.124,
                    direction="up",
                ),
                KPI(label="Mean reward", value=0.784, unit="reward", delta=0.091, direction="up"),
                KPI(
                    label="Target throughput",
                    value=137.4,
                    unit="token/s",
                    delta=0.218,
                    direction="up",
                ),
                KPI(label="Rollout p95", value=94.2, unit="s", delta=-0.083, direction="down"),
                KPI(
                    label="Invalid programs",
                    value=0.037,
                    unit="ratio",
                    delta=-0.041,
                    direction="down",
                ),
            ],
            series=series,
            wallclock=[
                Breakdown(label="target decode", value=41),
                Breakdown(label="draft", value=16),
                Breakdown(label="verification", value=13),
                Breakdown(label="environment", value=21),
                Breakdown(label="control + storage", value=2),
                Breakdown(label="idle", value=7),
            ],
            terminations=[
                Breakdown(label="success", value=61),
                Breakdown(label="turn limit", value=13),
                Breakdown(label="no progress", value=10),
                Breakdown(label="invalid program", value=8),
                Breakdown(label="agent death", value=5),
                Breakdown(label="environment fault", value=3),
            ],
            tasks=tasks,
            rollouts=rollouts,
            bundles=bundles,
        )

    def _build_trace(self, row: RolloutRow) -> RolloutTrace:
        labels = [
            ("rollout.started", "Loaded checkpoint and verified task constraints"),
            ("rollout.inference.completed", "Generated diagnostic inspection program"),
            ("rollout.environment.completed", "Observed entity status and production flow"),
            ("rollout.turn.completed", "Applied localized repair intervention"),
            ("rollout.reward.recorded", "Holdout verifier measured sustained output"),
            ("rollout.termination.recorded", f"Stopped: {row.termination_reason}"),
        ]
        return RolloutTrace(
            rollout=row,
            events=[
                TraceEvent(
                    sequence=index,
                    elapsed_seconds=round(index * row.duration_seconds / (len(labels) - 1), 2),
                    event_type=event_type,
                    summary=summary,
                    reward=row.reward if "reward" in event_type else None,
                )
                for index, (event_type, summary) in enumerate(labels)
            ],
        )


class LiveSource(DataSource):
    """Read-only projection over RolloutPlane's gRPC query API."""

    def __init__(self, target: str) -> None:
        self.client = RemoteRolloutPlane(target)
        self._cache_lock = asyncio.Lock()
        self._cached_dashboard: Dashboard | None = None
        self._cache_expires_at = 0.0
        self._run = RunSummary(
            run_id="live",
            name="Live RolloutPlane",
            status="running",
            model="versioned policy bundles",
            environment="agentic RL",
            started_at_ns=time.time_ns(),
            current_bundle="resolving",
        )

    async def close(self) -> None:
        await self.client.close()

    async def runs(self) -> list[RunSummary]:
        events = await self.client.list_events(limit=1000)
        bundles = [event.bundle_id for event in events if event.bundle_id]
        started = [event.occurred_at_ns for event in events]
        run = self._run.model_copy(
            update={
                "started_at_ns": min(started) if started else self._run.started_at_ns,
                "current_bundle": bundles[-1] if bundles else "no bundle observed",
            }
        )
        return [run]

    async def dashboard(self, run_id: str) -> Dashboard:
        if run_id != "live":
            raise KeyError(run_id)
        if self._cached_dashboard and time.monotonic() < self._cache_expires_at:
            return self._cached_dashboard
        async with self._cache_lock:
            if self._cached_dashboard and time.monotonic() < self._cache_expires_at:
                return self._cached_dashboard
            dashboard = await self._build_dashboard()
            self._cached_dashboard = dashboard
            self._cache_expires_at = time.monotonic() + 10.0
            return dashboard

    async def _build_dashboard(self) -> Dashboard:
        metrics, events = await asyncio.gather(
            self.client.query_metrics(limit=100_000),
            self.client.list_events(limit=100_000),
        )
        runs = await self.runs()
        run = runs[0]
        grouped: dict[tuple[str, str], list[Point]] = defaultdict(list)
        units: dict[str, str] = {}
        for record in metrics:
            bundle_id = record.bundle_id or "unversioned"
            grouped[(record.metric.name, record.metric.unit)].append(
                Point(
                    timestamp_ns=record.occurred_at_ns,
                    value=record.metric.value,
                    bundle_id=bundle_id,
                )
            )
            units[record.metric.name] = record.metric.unit
        series = [
            Series(
                name=name, unit=unit, points=sorted(points, key=lambda point: point.timestamp_ns)
            )
            for (name, unit), points in sorted(grouped.items())
        ]
        latest = {item.name: item.points[-1].value for item in series if item.points}
        kpis = [
            self._kpi(
                "Validation success", latest, ("validation.success_rate", "success.rate"), "ratio"
            ),
            self._kpi("Mean reward", latest, ("reward.mean", "reward.total"), "reward"),
            self._kpi(
                "Target throughput",
                latest,
                ("throughput.target_tokens", "inference.target_tokens_per_second"),
                "token/s",
            ),
            self._kpi(
                "Rollout p95", latest, ("rollout.p95_seconds", "rollout.duration_seconds"), "s"
            ),
            self._kpi("Invalid programs", latest, ("environment.invalid_program_rate",), "ratio"),
        ]
        termination_counts = Counter(
            str(event.payload.get("reason", "unknown"))
            for event in events
            if event.event_type == EventType.TERMINATION_RECORDED
        )
        total_terminations = sum(termination_counts.values()) or 1
        terminations = [
            Breakdown(label=reason, value=round(count * 100 / total_terminations, 2))
            for reason, count in termination_counts.most_common()
        ] or [Breakdown(label="no terminations", value=0)]
        wallclock_names = {
            "inference.target_seconds": "target decode",
            "inference.draft_seconds": "draft",
            "inference.verification_seconds": "verification",
            "environment.seconds": "environment",
            "control.seconds": "control + storage",
        }
        wallclock_values = {label: latest.get(name, 0) for name, label in wallclock_names.items()}
        wallclock_total = sum(wallclock_values.values()) or 1
        wallclock = [
            Breakdown(label=label, value=round(value * 100 / wallclock_total, 2))
            for label, value in wallclock_values.items()
        ]
        rollouts = self._rollout_rows(events)
        tasks = self._task_rows(rollouts)
        bundles = list(dict.fromkeys(point.bundle_id for item in series for point in item.points))
        return Dashboard(
            generated_at_ns=time.time_ns(),
            run=run,
            kpis=kpis,
            series=series,
            wallclock=wallclock,
            terminations=terminations,
            tasks=tasks,
            rollouts=rollouts[-100:][::-1],
            bundles=bundles or [run.current_bundle],
        )

    async def trace(self, rollout_id: str) -> RolloutTrace | None:
        events = await self.client.list_events(rollout_id=rollout_id, limit=10_000)
        if not events:
            return None
        row = self._rollout_rows(events)[0]
        start = min(event.occurred_at_ns for event in events)
        return RolloutTrace(
            rollout=row,
            events=[
                TraceEvent(
                    sequence=event.sequence if event.sequence is not None else index,
                    elapsed_seconds=(event.occurred_at_ns - start) / 1_000_000_000,
                    event_type=event.event_type,
                    summary=self._summary(event),
                    reward=self._event_reward(event),
                )
                for index, event in enumerate(events)
            ],
        )

    @staticmethod
    def _kpi(label: str, latest: dict[str, float], names: tuple[str, ...], unit: str) -> KPI:
        value = next((latest[name] for name in names if name in latest), 0.0)
        return KPI(label=label, value=value, unit=unit)

    @staticmethod
    def _event_reward(event: RolloutEvent) -> float | None:
        for metric in event.metrics:
            if metric.name in {"reward.total", "reward.mean"}:
                return metric.value
        value = event.payload.get("reward")
        return float(value) if isinstance(value, (int, float)) else None

    @classmethod
    def _rollout_rows(cls, events: list[RolloutEvent]) -> list[RolloutRow]:
        grouped: dict[str, list[RolloutEvent]] = defaultdict(list)
        for event in events:
            if event.rollout_id:
                grouped[event.rollout_id].append(event)
        rows: list[RolloutRow] = []
        for rollout_id, rollout_events in grouped.items():
            ordered = sorted(rollout_events, key=lambda item: item.occurred_at_ns)
            payload = next((event.payload for event in ordered if event.payload.get("task")), {})
            termination = next(
                (
                    event
                    for event in reversed(ordered)
                    if event.event_type == EventType.TERMINATION_RECORDED
                ),
                None,
            )
            reward = next(
                (
                    value
                    for event in reversed(ordered)
                    if (value := cls._event_reward(event)) is not None
                ),
                0.0,
            )
            reason = str(termination.payload.get("reason", "active")) if termination else "active"
            rows.append(
                RolloutRow(
                    rollout_id=rollout_id,
                    task=str(payload.get("task", payload.get("task_id", "unlabeled task"))),
                    bundle_id=next(
                        (event.bundle_id for event in ordered if event.bundle_id), "unversioned"
                    ),
                    reward=reward,
                    duration_seconds=(ordered[-1].occurred_at_ns - ordered[0].occurred_at_ns)
                    / 1_000_000_000,
                    turns=max((event.sequence or 0 for event in ordered), default=0) + 1,
                    status="completed"
                    if reason == "success"
                    else "active"
                    if reason == "active"
                    else "truncated",
                    termination_reason=reason,
                )
            )
        return rows

    @staticmethod
    def _task_rows(rows: list[RolloutRow]) -> list[TaskResult]:
        grouped: dict[str, list[RolloutRow]] = defaultdict(list)
        for row in rows:
            grouped[row.task].append(row)
        results = []
        for task, task_rows in grouped.items():
            rewards = sorted(row.reward for row in task_rows)
            durations = sorted(row.duration_seconds for row in task_rows)
            middle = len(task_rows) // 2
            results.append(
                TaskResult(
                    task=task,
                    family="live",
                    attempts=len(task_rows),
                    success_rate=sum(row.termination_reason == "success" for row in task_rows)
                    / len(task_rows),
                    median_reward=rewards[middle],
                    median_seconds=durations[middle],
                )
            )
        return sorted(results, key=lambda result: (-result.attempts, result.task))

    @staticmethod
    def _summary(event: RolloutEvent) -> str:
        for key in ("summary", "reason", "message", "task"):
            if key in event.payload:
                return str(event.payload[key])
        return event.event_type.replace(".", " ")
