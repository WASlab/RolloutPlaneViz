from __future__ import annotations

import asyncio
import math
import random
import statistics
import time
from abc import ABC, abstractmethod
from collections import Counter, defaultdict

from rolloutplane.client import RemoteRolloutPlane
from rolloutplane.models import (
    Checkpoint,
    EventType,
    InferenceBundle,
    MetricRecord,
    RolloutEvent,
    RolloutLease,
    TrainingRun,
)

from rolloutplane_viz.models import (
    KPI,
    Breakdown,
    BundleSummary,
    Dashboard,
    Point,
    RolloutPage,
    RolloutRow,
    RolloutTrace,
    RunSummary,
    Series,
    TaskResult,
    TraceEvent,
)


class DataSource(ABC):
    source_kind = "unknown"
    refresh_seconds = 10.0
    max_series_points = 2_000

    @abstractmethod
    async def runs(self) -> list[RunSummary]: ...

    @abstractmethod
    async def dashboard(self, run_id: str) -> Dashboard: ...

    async def evidence(self, run_id: str) -> Dashboard:
        """Return the complete bounded source projection used for analysis.

        Sources that downsample their interactive dashboard override this method so
        statistical comparisons and reports never inherit presentation sampling.
        """
        return await self.dashboard(run_id)

    @abstractmethod
    async def trace(self, rollout_id: str) -> RolloutTrace | None: ...

    @abstractmethod
    async def rollouts(
        self,
        run_id: str,
        *,
        offset: int,
        limit: int,
        query: str | None = None,
        status: str | None = None,
        bundle_id: str | None = None,
    ) -> RolloutPage: ...


def downsample(points: list[Point], limit: int = 2_000) -> list[Point]:
    """Min/max bucket downsampling that preserves spikes and endpoints."""
    if limit < 4:
        raise ValueError("limit must be at least 4")
    if len(points) <= limit:
        return points
    interior = points[1:-1]
    bucket_count = max(1, (limit - 2) // 2)
    bucket_size = max(1, math.ceil(len(interior) / bucket_count))
    selected = [points[0]]
    for start in range(0, len(interior), bucket_size):
        bucket = interior[start : start + bucket_size]
        minimum = min(bucket, key=lambda point: point.value)
        maximum = max(bucket, key=lambda point: point.value)
        extrema = [minimum] if minimum == maximum else [minimum, maximum]
        selected.extend(sorted(extrema, key=lambda point: point.timestamp_ns))
    selected.append(points[-1])
    return selected[: limit - 1] + [points[-1]] if len(selected) > limit else selected


def _filter_rollouts(
    rows: list[RolloutRow],
    *,
    query: str | None,
    status: str | None,
    bundle_id: str | None,
) -> list[RolloutRow]:
    needle = query.casefold().strip() if query else ""
    filtered = [
        row
        for row in rows
        if (status is None or row.status == status)
        and (bundle_id is None or row.bundle_id == bundle_id)
        and (
            not needle
            or needle
            in " ".join(
                value
                for value in (
                    row.rollout_id,
                    row.task,
                    row.task_family,
                    row.termination_reason,
                    row.worker_id,
                )
                if value
            ).casefold()
        )
    ]
    return sorted(filtered, key=lambda row: (row.started_at_ns, row.rollout_id), reverse=True)


def _event_reward(event: RolloutEvent) -> float | None:
    preferred = {
        "reward.total",
        "reward.mean",
        "reward.task_success",
        "task.reward",
    }
    for metric in reversed(event.metrics):
        if metric.name in preferred:
            return metric.value
    value = event.payload.get("reward")
    if isinstance(value, (int, float)):
        return float(value)
    vector = event.payload.get("reward_vector")
    if isinstance(vector, dict):
        for name in ("total", "task_success", "success"):
            candidate = vector.get(name)
            if isinstance(candidate, (int, float)):
                return float(candidate)
    return None


def _rollout_rows(events: list[RolloutEvent], leases: list[RolloutLease]) -> list[RolloutRow]:
    grouped: dict[str, list[RolloutEvent]] = defaultdict(list)
    for event in events:
        if event.rollout_id:
            grouped[event.rollout_id].append(event)
    lease_by_rollout = {
        lease.rollout_id: lease for lease in sorted(leases, key=lambda item: item.acquired_at_ns)
    }
    rows: list[RolloutRow] = []
    for rollout_id, rollout_events in grouped.items():
        ordered = sorted(
            rollout_events,
            key=lambda item: (
                item.sequence if item.sequence is not None else 2**63,
                item.occurred_at_ns,
                item.event_id,
            ),
        )
        lease = lease_by_rollout.get(rollout_id)
        payload = next(
            (
                event.payload
                for event in ordered
                if event.payload.get("task") or event.payload.get("task_id")
            ),
            {},
        )
        termination = next(
            (
                event
                for event in reversed(ordered)
                if event.event_type == EventType.TERMINATION_RECORDED
            ),
            None,
        )
        terminal = next(
            (
                event
                for event in reversed(ordered)
                if event.event_type in {EventType.ROLLOUT_COMPLETED, EventType.ROLLOUT_FAILED}
            ),
            None,
        )
        reward = next(
            (value for event in reversed(ordered) if (value := _event_reward(event)) is not None),
            0.0,
        )
        reason = str(termination.payload.get("reason", "active")) if termination else "active"
        truncated = bool(termination and termination.payload.get("truncated", False))
        if terminal and terminal.event_type == EventType.ROLLOUT_FAILED:
            status = "failed"
        elif terminal:
            status = "truncated" if truncated else "completed"
        else:
            status = "active"
        started_at_ns = ordered[0].occurred_at_ns
        ended_at_ns = ordered[-1].occurred_at_ns
        rows.append(
            RolloutRow(
                rollout_id=rollout_id,
                task=(
                    lease.task_id
                    if lease and lease.task_id
                    else str(payload.get("task", payload.get("task_id", "unlabeled task")))
                ),
                task_family=(
                    lease.labels.get("task_family", "unlabeled") if lease else "unlabeled"
                ),
                bundle_id=(
                    lease.bundle_id
                    if lease
                    else next(
                        (event.bundle_id for event in ordered if event.bundle_id),
                        "unversioned",
                    )
                ),
                reward=reward,
                duration_seconds=(ended_at_ns - started_at_ns) / 1_000_000_000,
                turns=sum(event.event_type == EventType.TURN_COMPLETED for event in ordered),
                status=status,
                termination_reason=reason,
                started_at_ns=started_at_ns,
                ended_at_ns=ended_at_ns,
                worker_id=lease.worker_id if lease else ordered[0].worker_id,
                attempt=lease.attempt if lease else 0,
                decision_chunk=lease.decision_chunk if lease else 0,
            )
        )
    return sorted(rows, key=lambda row: (row.started_at_ns, row.rollout_id))


def _task_rows(rows: list[RolloutRow]) -> list[TaskResult]:
    grouped: dict[tuple[str, str], list[RolloutRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.task, row.task_family)].append(row)
    results = [
        TaskResult(
            task=task,
            family=family,
            attempts=len(task_rows),
            success_rate=(
                sum(row.termination_reason == "success" for row in task_rows) / len(task_rows)
            ),
            median_reward=statistics.median(row.reward for row in task_rows),
            median_seconds=statistics.median(row.duration_seconds for row in task_rows),
        )
        for (task, family), task_rows in grouped.items()
    ]
    return sorted(results, key=lambda result: (-result.attempts, result.task))


def _bundle_summary(bundle: InferenceBundle) -> BundleSummary:
    speculator = bundle.speculator
    return BundleSummary(
        bundle_id=bundle.bundle_id or "unaddressed",
        target=f"{bundle.target.name}@{bundle.target.version}",
        tokenizer=f"{bundle.tokenizer.name}@{bundle.tokenizer.version}",
        engine=f"{bundle.engine.name}@{bundle.engine.version}",
        speculator=(f"{speculator.name}@{speculator.version}" if speculator else None),
        policy_step=bundle.policy_step,
        target_digest=bundle.target.digest,
        tokenizer_digest=bundle.tokenizer.digest,
        engine_digest=bundle.engine.digest,
        speculator_digest=speculator.digest if speculator else None,
        sampling=bundle.sampling,
        environment_contract=bundle.environment_contract,
        reward_contract=bundle.reward_contract,
        created_at_ns=bundle.created_at_ns,
        labels=bundle.labels,
    )


class DemoSource(DataSource):
    """Seeded data for development and visual regression tests."""

    source_kind = "demo"
    refresh_seconds = 0.0

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
            algorithm="grpo",
            current_checkpoint="step-184",
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

    async def rollouts(
        self,
        run_id: str,
        *,
        offset: int,
        limit: int,
        query: str | None = None,
        status: str | None = None,
        bundle_id: str | None = None,
    ) -> RolloutPage:
        if run_id != self._run.run_id:
            raise KeyError(run_id)
        rows = _filter_rollouts(
            self._dashboard.rollouts,
            query=query,
            status=status,
            bundle_id=bundle_id,
        )
        return RolloutPage(
            items=rows[offset : offset + limit],
            total=len(rows),
            offset=offset,
            limit=limit,
        )

    def _build_dashboard(self) -> Dashboard:
        bundles = ["theta-042 / phi-04", "theta-108 / phi-07", "theta-184 / phi-12"]
        definitions = [
            ("reward.mean", "reward"),
            ("success.rate", "ratio"),
            ("throughput.target_tokens", "token/s"),
            ("speculation.acceptance", "ratio"),
        ]
        series: list[Series] = []
        for metric, unit in definitions:
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
            ("Reversed inserter", "repair", 0.91, 0.94, 18.2),
            ("Missing power pole", "repair", 0.86, 0.89, 22.8),
            ("Wrong assembler recipe", "repair", 0.79, 0.82, 31.4),
            ("Starved furnace line", "diagnosis", 0.68, 0.71, 48.6),
            ("Belt throughput +25%", "expansion", 0.56, 0.63, 76.1),
            ("Recover depleted patch", "recovery", 0.34, 0.45, 119.7),
        ]
        task_results = [
            TaskResult(
                task=task,
                family=family,
                attempts=96 - index * 9,
                success_rate=success,
                median_reward=reward,
                median_seconds=seconds,
            )
            for index, (task, family, success, reward, seconds) in enumerate(tasks)
        ]
        reasons = [
            "success",
            "turn limit",
            "invalid program",
            "no progress",
            "agent death",
            "environment fault",
        ]
        rollouts: list[RolloutRow] = []
        for index in range(36):
            reason = reasons[0] if index < 23 else reasons[1 + (index % 5)]
            duration = round(self._random.uniform(17, 128), 1)
            started = self._start + (42 * 600 + index * 90) * 1_000_000_000
            task = task_results[index % len(task_results)]
            rollouts.append(
                RolloutRow(
                    rollout_id=f"fo-{18420 + index}",
                    task=task.task,
                    task_family=task.family,
                    bundle_id=bundles[2 if index < 24 else 1],
                    reward=round(
                        self._random.uniform(0.35, 0.98)
                        if reason == "success"
                        else self._random.uniform(-0.08, 0.48),
                        3,
                    ),
                    duration_seconds=duration,
                    turns=self._random.randint(2, 9),
                    status="completed" if reason == "success" else "truncated",
                    termination_reason=reason,
                    started_at_ns=started,
                    ended_at_ns=started + round(duration * 1_000_000_000),
                    worker_id=f"demo-worker-{index % 4}",
                )
            )
        details = [
            BundleSummary(
                bundle_id=bundle,
                target=f"qwen3-4b@theta-{step:03d}",
                tokenizer="qwen3-tokenizer@1",
                engine="vllm@0.24",
                speculator=f"dspark@phi-{4 + index * 3:02d}",
                policy_step=step,
                target_digest=f"sha256:demo-target-{step}",
                tokenizer_digest="sha256:demo-tokenizer",
                engine_digest="sha256:demo-vllm",
                speculator_digest=f"sha256:demo-dspark-{step}",
                sampling={
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "logprobs": True,
                    "max_completion_tokens": 1_024,
                },
                environment_contract="factorio/microtasks-v1",
                reward_contract="factorio/reward-vector/v1",
                created_at_ns=self._start + index * 24 * 600_000_000_000,
                labels={"source": "deterministic-demo"},
            )
            for index, (bundle, step) in enumerate(zip(bundles, (42, 108, 184), strict=True))
        ]
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
            tasks=task_results,
            rollouts=list(reversed(rollouts)),
            bundles=bundles,
            bundle_details=details,
        )

    def _build_trace(self, row: RolloutRow) -> RolloutTrace:
        labels = [
            ("rollout.started", "Loaded checkpoint and verified task constraints"),
            ("rollout.inference.completed", "Generated diagnostic inspection program"),
            ("rollout.environment.completed", "Observed entity status and production flow"),
            ("rollout.turn.completed", "Applied localized repair intervention"),
            ("rollout.reward.recorded", "Holdout verifier measured sustained output"),
            ("rollout.termination.recorded", f"Stopped: {row.termination_reason}"),
            ("rollout.completed", "Closed the evidence sequence"),
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
    """Read-only, paginated projection over RolloutPlane 0.2's gRPC API."""

    source_kind = "rolloutplane-grpc"

    def __init__(
        self,
        target: str,
        *,
        refresh_seconds: float = 10.0,
        max_series_points: int = 2_000,
        max_source_records: int = 1_000_000,
        root_certificates: bytes | None = None,
        client_private_key: bytes | None = None,
        client_certificate_chain: bytes | None = None,
        secure: bool | None = None,
        server_name_override: str | None = None,
    ) -> None:
        if refresh_seconds <= 0 or max_series_points < 4 or max_source_records <= 0:
            raise ValueError("live source limits must be positive")
        self.refresh_seconds = refresh_seconds
        self.max_series_points = max_series_points
        self.max_source_records = max_source_records
        self.client = RemoteRolloutPlane(
            target,
            root_certificates=root_certificates,
            client_private_key=client_private_key,
            client_certificate_chain=client_certificate_chain,
            secure=secure,
            server_name_override=server_name_override,
        )
        self._cache_lock = asyncio.Lock()
        self._cached_dashboards: dict[str, tuple[float, Dashboard]] = {}
        self._cached_evidence: dict[str, Dashboard] = {}
        self._rollout_cache: dict[str, list[RolloutRow]] = {}

    async def close(self) -> None:
        await self.client.close()

    async def _all_runs(self) -> list[TrainingRun]:
        items: list[TrainingRun] = []
        cursor: str | None = None
        while True:
            page = await self.client.list_runs(limit=100, cursor=cursor)
            items.extend(page.items)
            if len(items) > self.max_source_records:
                raise RuntimeError("run query exceeded the configured source-record limit")
            cursor = page.next_cursor
            if cursor is None:
                return items

    async def _all_checkpoints(self, run_id: str) -> list[Checkpoint]:
        items: list[Checkpoint] = []
        cursor: str | None = None
        while True:
            page = await self.client.list_checkpoints(run_id, limit=100, cursor=cursor)
            items.extend(page.items)
            if len(items) > self.max_source_records:
                raise RuntimeError("checkpoint query exceeded the source-record limit")
            cursor = page.next_cursor
            if cursor is None:
                return items

    async def _all_leases(
        self, *, run_id: str | None = None, rollout_id: str | None = None
    ) -> list[RolloutLease]:
        items: list[RolloutLease] = []
        cursor: str | None = None
        while True:
            page = await self.client.list_leases(
                run_id=run_id,
                rollout_id=rollout_id,
                limit=1_000,
                cursor=cursor,
            )
            items.extend(page.items)
            if len(items) > self.max_source_records:
                raise RuntimeError("lease query exceeded the source-record limit")
            cursor = page.next_cursor
            if cursor is None:
                return items

    async def _all_events(
        self,
        *,
        run_id: str | None = None,
        rollout_id: str | None = None,
        to_ns: int | None = None,
    ) -> list[RolloutEvent]:
        items: list[RolloutEvent] = []
        cursor: str | None = None
        while True:
            page = await self.client.list_events_page(
                run_id=run_id,
                rollout_id=rollout_id,
                to_ns=to_ns,
                limit=10_000,
                cursor=cursor,
            )
            items.extend(page.items)
            if len(items) > self.max_source_records:
                raise RuntimeError("event query exceeded the source-record limit")
            cursor = page.next_cursor
            if cursor is None:
                return items

    async def _all_metrics(self, run_id: str, *, to_ns: int) -> list[MetricRecord]:
        items: list[MetricRecord] = []
        cursor: str | None = None
        while True:
            page = await self.client.query_metrics_page(
                run_id=run_id,
                to_ns=to_ns,
                limit=10_000,
                cursor=cursor,
            )
            items.extend(page.items)
            if len(items) > self.max_source_records:
                raise RuntimeError("metric query exceeded the source-record limit")
            cursor = page.next_cursor
            if cursor is None:
                return items

    @staticmethod
    def _summary(
        run: TrainingRun,
        checkpoints: list[Checkpoint],
        leases: list[RolloutLease],
    ) -> RunSummary:
        checkpoint = max(checkpoints, key=lambda item: item.step, default=None)
        lease = max(leases, key=lambda item: item.acquired_at_ns, default=None)
        current_bundle = (
            checkpoint.bundle_id
            if checkpoint and checkpoint.bundle_id
            else lease.bundle_id
            if lease
            else "no bundle observed"
        )
        return RunSummary(
            run_id=run.run_id,
            name=run.name,
            status=run.status,
            model=run.model,
            environment=run.environment,
            started_at_ns=run.started_at_ns or run.created_at_ns,
            finished_at_ns=run.ended_at_ns,
            current_bundle=current_bundle,
            algorithm=run.algorithm,
            current_checkpoint=checkpoint.checkpoint_id if checkpoint else None,
        )

    async def runs(self) -> list[RunSummary]:
        runs = await self._all_runs()

        async def summarize(run: TrainingRun) -> RunSummary:
            checkpoints, leases = await asyncio.gather(
                self._all_checkpoints(run.run_id),
                self._all_leases(run_id=run.run_id),
            )
            return self._summary(run, checkpoints, leases)

        summaries = await asyncio.gather(*(summarize(run) for run in runs))
        return sorted(
            summaries,
            key=lambda run: (run.started_at_ns, run.run_id),
            reverse=True,
        )

    async def dashboard(self, run_id: str) -> Dashboard:
        cached = self._cached_dashboards.get(run_id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        async with self._cache_lock:
            cached = self._cached_dashboards.get(run_id)
            if cached and time.monotonic() < cached[0]:
                return cached[1]
            dashboard = await self._build_dashboard(run_id)
            self._cached_dashboards[run_id] = (
                time.monotonic() + self.refresh_seconds,
                dashboard,
            )
            return dashboard

    async def evidence(self, run_id: str) -> Dashboard:
        await self.dashboard(run_id)
        return self._cached_evidence[run_id]

    async def _build_dashboard(self, run_id: str) -> Dashboard:
        cutoff_ns = time.time_ns()
        run, checkpoints, leases, metrics, events = await asyncio.gather(
            self.client.get_run(run_id),
            self._all_checkpoints(run_id),
            self._all_leases(run_id=run_id),
            self._all_metrics(run_id, to_ns=cutoff_ns),
            self._all_events(run_id=run_id, to_ns=cutoff_ns),
        )
        summary = self._summary(run, checkpoints, leases)
        grouped: dict[tuple[str, str], list[Point]] = defaultdict(list)
        for record in metrics:
            grouped[(record.metric.name, record.metric.unit)].append(
                Point(
                    timestamp_ns=record.occurred_at_ns,
                    value=record.metric.value,
                    bundle_id=record.bundle_id or "unversioned",
                )
            )
        raw_series = [
            Series(
                name=name,
                unit=unit,
                points=sorted(points, key=lambda point: point.timestamp_ns),
            )
            for (name, unit), points in sorted(grouped.items())
        ]
        series = [
            metric_series.model_copy(
                update={"points": downsample(metric_series.points, self.max_series_points)}
            )
            for metric_series in raw_series
        ]
        bundle_ids = list(
            dict.fromkeys(
                [checkpoint.bundle_id for checkpoint in checkpoints if checkpoint.bundle_id]
                + [lease.bundle_id for lease in leases]
                + [
                    point.bundle_id
                    for metric_series in raw_series
                    for point in metric_series.points
                    if point.bundle_id != "unversioned"
                ]
            )
        )
        semaphore = asyncio.Semaphore(16)

        async def load_bundle(bundle_id: str) -> BundleSummary:
            async with semaphore:
                return _bundle_summary(await self.client.get_bundle(bundle_id))

        details = await asyncio.gather(*(load_bundle(bundle_id) for bundle_id in bundle_ids))
        details = sorted(details, key=lambda bundle: (bundle.created_at_ns or 0, bundle.bundle_id))
        bundles = [bundle.bundle_id for bundle in details]
        if not bundles and summary.current_bundle != "no bundle observed":
            bundles = [summary.current_bundle]
        rows = _rollout_rows(events, leases)
        self._rollout_cache[run_id] = rows
        latest = {item.name: item.points[-1].value for item in raw_series if item.points}
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
        termination_total = sum(termination_counts.values())
        terminations = (
            [
                Breakdown(label=reason, value=round(count * 100 / termination_total, 2))
                for reason, count in termination_counts.most_common()
            ]
            if termination_total
            else [Breakdown(label="no terminations", value=0)]
        )
        wallclock_names = {
            "inference.target_seconds": "target decode",
            "inference.draft_seconds": "draft",
            "inference.verification_seconds": "verification",
            "environment.seconds": "environment",
            "control.seconds": "control + storage",
        }
        wallclock_values = {label: latest.get(name, 0.0) for name, label in wallclock_names.items()}
        wallclock_total = sum(wallclock_values.values())
        wallclock = (
            [
                Breakdown(label=label, value=round(value * 100 / wallclock_total, 2))
                for label, value in wallclock_values.items()
            ]
            if wallclock_total
            else [Breakdown(label="no timing evidence", value=0)]
        )
        evidence = Dashboard(
            generated_at_ns=cutoff_ns,
            run=summary,
            kpis=kpis,
            series=raw_series,
            wallclock=wallclock,
            terminations=terminations,
            tasks=_task_rows(rows),
            rollouts=list(reversed(rows)),
            bundles=bundles,
            bundle_details=details,
        )
        self._cached_evidence[run_id] = evidence
        return evidence.model_copy(
            update={
                "series": series,
                "rollouts": list(reversed(rows[-200:])),
            }
        )

    async def rollouts(
        self,
        run_id: str,
        *,
        offset: int,
        limit: int,
        query: str | None = None,
        status: str | None = None,
        bundle_id: str | None = None,
    ) -> RolloutPage:
        await self.dashboard(run_id)
        rows = _filter_rollouts(
            self._rollout_cache.get(run_id, []),
            query=query,
            status=status,
            bundle_id=bundle_id,
        )
        return RolloutPage(
            items=rows[offset : offset + limit],
            total=len(rows),
            offset=offset,
            limit=limit,
        )

    async def trace(self, rollout_id: str) -> RolloutTrace | None:
        events, leases = await asyncio.gather(
            self._all_events(rollout_id=rollout_id),
            self._all_leases(rollout_id=rollout_id),
        )
        if not events:
            return None
        rows = _rollout_rows(events, leases)
        if not rows:
            return None
        start = min(event.occurred_at_ns for event in events)
        ordered = sorted(
            events,
            key=lambda event: (
                event.sequence if event.sequence is not None else 2**63,
                event.occurred_at_ns,
            ),
        )
        return RolloutTrace(
            rollout=rows[0],
            events=[
                TraceEvent(
                    sequence=event.sequence if event.sequence is not None else index,
                    elapsed_seconds=(event.occurred_at_ns - start) / 1_000_000_000,
                    event_type=event.event_type,
                    summary=self._event_summary(event),
                    reward=_event_reward(event),
                )
                for index, event in enumerate(ordered)
            ],
        )

    @staticmethod
    def _kpi(
        label: str,
        latest: dict[str, float],
        names: tuple[str, ...],
        unit: str,
    ) -> KPI:
        value = next((latest[name] for name in names if name in latest), 0.0)
        return KPI(label=label, value=value, unit=unit)

    @staticmethod
    def _event_summary(event: RolloutEvent) -> str:
        for key in ("summary", "reason", "message", "task", "task_id"):
            if key in event.payload:
                return str(event.payload[key])
        return event.event_type.replace(".", " ")
