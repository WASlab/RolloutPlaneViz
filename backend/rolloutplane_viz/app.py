from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from rolloutplane_viz import __version__
from rolloutplane_viz.models import (
    KPI,
    Breakdown,
    Comparison,
    ComparisonMethod,
    ComparisonRequest,
    Dashboard,
    ReportDocument,
    ReportReceipt,
    ReportRequest,
    ReportVerification,
    RolloutPage,
    RolloutTrace,
    RunSummary,
    Series,
    ServiceMetadata,
    TaskResult,
)
from rolloutplane_viz.source import DataSource, DemoSource, LiveSource
from rolloutplane_viz.statistics import compare_series

REPORT_ID_PATTERN = re.compile(r"report_[0-9a-f]{16}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _report_digest(request: ReportRequest, dashboard: Dashboard) -> str:
    body = {
        "request": request.model_dump(mode="json"),
        "dashboard": dashboard.model_dump(mode="json"),
    }
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _comparison_digest(request: ComparisonRequest, series: list[Series]) -> str:
    body = {
        "request": request.model_dump(mode="json"),
        "series": [item.model_dump(mode="json") for item in series],
    }
    return f"sha256:{hashlib.sha256(_canonical(body)).hexdigest()}"


def _metric_csv(data: Dashboard) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["metric", "unit", "timestamp_ns", "value", "bundle_id"])
    for series in data.series:
        for point in series.points:
            writer.writerow(
                [series.name, series.unit, point.timestamp_ns, point.value, point.bundle_id]
            )
    return stream.getvalue().encode()


def _rollout_csv(data: Dashboard) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "rollout_id",
            "task",
            "task_family",
            "bundle_id",
            "reward",
            "duration_seconds",
            "turns",
            "status",
            "termination_reason",
            "started_at_ns",
            "ended_at_ns",
            "worker_id",
            "attempt",
            "decision_chunk",
        ]
    )
    for row in data.rollouts:
        writer.writerow(
            [
                row.rollout_id,
                row.task,
                row.task_family,
                row.bundle_id,
                row.reward,
                row.duration_seconds,
                row.turns,
                row.status,
                row.termination_reason,
                row.started_at_ns,
                row.ended_at_ns,
                row.worker_id,
                row.attempt,
                row.decision_chunk,
            ]
        )
    return stream.getvalue().encode()


def _task_csv(data: Dashboard) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "task",
            "family",
            "attempts",
            "success_rate",
            "median_reward",
            "median_seconds",
        ]
    )
    for task in data.tasks:
        writer.writerow(
            [
                task.task,
                task.family,
                task.attempts,
                task.success_rate,
                task.median_reward,
                task.median_seconds,
            ]
        )
    return stream.getvalue().encode()


def _read_optional(path: str | None) -> bytes | None:
    return Path(path).read_bytes() if path else None


def _catalog_paths(root: Path, limit: int) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        root.glob("report_*.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )[:limit]


def _live_source_from_environment(target: str) -> LiveSource:
    secure_value = os.environ.get("ROLLOUTPLANE_SECURE")
    secure = None if secure_value is None else secure_value.casefold() in {"1", "true", "yes"}
    return LiveSource(
        target,
        refresh_seconds=float(os.environ.get("ROLLOUTPLANE_VIZ_REFRESH_SECONDS", "10")),
        max_series_points=int(os.environ.get("ROLLOUTPLANE_VIZ_MAX_SERIES_POINTS", "2000")),
        max_source_records=int(os.environ.get("ROLLOUTPLANE_VIZ_MAX_SOURCE_RECORDS", "1000000")),
        root_certificates=_read_optional(os.environ.get("ROLLOUTPLANE_ROOT_CERTIFICATE")),
        client_private_key=_read_optional(os.environ.get("ROLLOUTPLANE_CLIENT_PRIVATE_KEY")),
        client_certificate_chain=_read_optional(
            os.environ.get("ROLLOUTPLANE_CLIENT_CERTIFICATE_CHAIN")
        ),
        secure=secure,
        server_name_override=os.environ.get("ROLLOUTPLANE_SERVER_NAME_OVERRIDE"),
    )


def _snapshot_tasks(data: Dashboard) -> list[TaskResult]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in data.rollouts:
        grouped[(row.task, row.task_family)].append(row)
    return sorted(
        [
            TaskResult(
                task=task,
                family=family,
                attempts=len(rows),
                success_rate=sum(row.termination_reason == "success" for row in rows) / len(rows),
                median_reward=statistics.median(row.reward for row in rows),
                median_seconds=statistics.median(row.duration_seconds for row in rows),
            )
            for (task, family), rows in grouped.items()
        ],
        key=lambda result: (-result.attempts, result.task),
    )


def _snapshot_dashboard(
    data: Dashboard, request: ReportRequest
) -> tuple[Dashboard, ReportRequest, int, int]:
    timestamps = [point.timestamp_ns for series in data.series for point in series.points]
    minimum = min(timestamps, default=data.run.started_at_ns)
    maximum = max(timestamps, default=max(data.generated_at_ns, minimum + 1))
    if request.range_start_ns is not None and request.range_end_ns is not None:
        start_ns, end_ns = request.range_start_ns, request.range_end_ns
    else:
        span = max(1, maximum - minimum)
        start_ns = minimum + math.floor(span * request.range_start_percent / 100)
        end_ns = minimum + math.ceil(span * request.range_end_percent / 100)
        end_ns = max(start_ns + 1, end_ns)
    normalized_request = request.model_copy(
        update={"range_start_ns": start_ns, "range_end_ns": end_ns}
    )
    ranged_series = [
        series.model_copy(
            update={
                "points": [
                    point for point in series.points if start_ns <= point.timestamp_ns <= end_ns
                ]
            }
        )
        for series in data.series
    ]
    ranged_rollouts = [row for row in data.rollouts if start_ns <= row.started_at_ns <= end_ns]
    latest = {series.name: series.points[-1].value for series in ranged_series if series.points}
    kpi_sources = [
        ("Validation success", ("validation.success_rate", "success.rate"), "ratio"),
        ("Mean reward", ("reward.mean", "reward.total"), "reward"),
        (
            "Target throughput",
            ("throughput.target_tokens", "inference.target_tokens_per_second"),
            "token/s",
        ),
        ("Rollout p95", ("rollout.p95_seconds", "rollout.duration_seconds"), "s"),
        ("Invalid programs", ("environment.invalid_program_rate",), "ratio"),
    ]
    kpis = [
        KPI(
            label=label,
            value=next((latest[name] for name in names if name in latest), 0.0),
            unit=unit,
        )
        for label, names, unit in kpi_sources
    ]
    termination_counts = Counter(row.termination_reason for row in ranged_rollouts)
    total = sum(termination_counts.values())
    terminations = (
        [
            Breakdown(label=reason, value=round(count * 100 / total, 2))
            for reason, count in termination_counts.most_common()
        ]
        if total
        else [Breakdown(label="no terminations", value=0)]
    )
    present_bundles = set(
        [point.bundle_id for series in ranged_series for point in series.points]
        + [row.bundle_id for row in ranged_rollouts]
    )
    for bundle in (request.baseline_bundle, request.candidate_bundle):
        if bundle:
            present_bundles.add(bundle)
    bundles = [bundle for bundle in data.bundles if bundle in present_bundles]
    snapshot = data.model_copy(
        update={
            "series": ranged_series,
            "rollouts": ranged_rollouts,
            "tasks": [],
            "kpis": kpis,
            "terminations": terminations,
            "bundles": bundles,
            "bundle_details": [
                detail for detail in data.bundle_details if detail.bundle_id in present_bundles
            ],
        }
    )
    snapshot = snapshot.model_copy(update={"tasks": _snapshot_tasks(snapshot)})
    return snapshot, normalized_request, start_ns, end_ns


def _comparison(data: Dashboard, request: ComparisonRequest) -> Comparison:
    if request.baseline_bundle not in data.bundles:
        raise HTTPException(status_code=404, detail="baseline bundle not found")
    if request.candidate_bundle not in data.bundles:
        raise HTTPException(status_code=404, detail="candidate bundle not found")
    selected_series = [
        item.model_copy(
            update={
                "points": [
                    point
                    for point in item.points
                    if point.bundle_id in {request.baseline_bundle, request.candidate_bundle}
                ]
            }
        )
        for item in data.series
        if not request.metric_names or item.name in request.metric_names
    ]
    selected_series = [item for item in selected_series if item.points]
    return Comparison(
        run_id=request.run_id,
        baseline_bundle=request.baseline_bundle,
        candidate_bundle=request.candidate_bundle,
        method=request.method,
        confidence_level=request.confidence_level,
        resamples=request.resamples if request.method == "moving_block_bootstrap" else None,
        generated_at_ns=time.time_ns(),
        source_generated_at_ns=data.generated_at_ns,
        data_digest=_comparison_digest(request, selected_series),
        request=request,
        estimates=compare_series(selected_series, request),
        series=selected_series,
        bundle_details=[
            detail
            for detail in data.bundle_details
            if detail.bundle_id in {request.baseline_bundle, request.candidate_bundle}
        ],
    )


def create_app(
    source: DataSource | None = None,
    report_directory: str | Path | None = None,
) -> FastAPI:
    target = os.environ.get("ROLLOUTPLANE_TARGET")
    selected_source = source or (_live_source_from_environment(target) if target else DemoSource())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(selected_source, "close", None)
        if close:
            await close()

    app = FastAPI(title="RolloutPlane Viz", version=__version__, lifespan=lifespan)
    app.state.source = selected_source
    report_root = Path(
        report_directory
        or os.environ.get("ROLLOUTPLANE_VIZ_REPORT_DIR", ".rolloutplane-viz/reports")
    )
    report_store_display = str(report_root.resolve())

    def report_path(report_id: str) -> Path | None:
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            return None
        return report_root / f"{report_id}.json"

    async def load_report(report_id: str) -> ReportDocument | None:
        path = report_path(report_id)
        if path is None or not path.is_file():
            return None
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return ReportDocument.model_validate_json(raw)

    async def require_report(report_id: str) -> ReportDocument:
        try:
            stored = await load_report(report_id)
        except (json.JSONDecodeError, ValueError) as error:
            raise HTTPException(status_code=409, detail="stored report is invalid") from error
        if stored is None:
            raise HTTPException(status_code=404, detail="report not found")
        return stored

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "serving", "source": selected_source.source_kind}

    @app.get("/api/v1/metadata", response_model=ServiceMetadata)
    async def metadata() -> ServiceMetadata:
        return ServiceMetadata(
            version=__version__,
            source_kind=selected_source.source_kind,
            refresh_seconds=selected_source.refresh_seconds,
            max_series_points=selected_source.max_series_points,
            report_store=report_store_display,
            features=[
                "linked-svg-charts",
                "moving-block-bootstrap",
                "bundle-provenance",
                "immutable-report-snapshots",
                "report-verification",
                "portable-report-export",
            ],
        )

    @app.get("/api/v1/runs", response_model=list[RunSummary])
    async def runs() -> list[RunSummary]:
        return await selected_source.runs()

    @app.get("/api/v1/runs/{run_id}/dashboard", response_model=Dashboard)
    async def dashboard(run_id: str) -> Dashboard:
        try:
            return await selected_source.dashboard(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.get("/api/v1/runs/{run_id}/rollouts", response_model=RolloutPage)
    async def rollouts(
        run_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        query: str | None = Query(default=None, max_length=200),
        status: str | None = None,
        bundle_id: str | None = None,
    ) -> RolloutPage:
        try:
            return await selected_source.rollouts(
                run_id,
                offset=offset,
                limit=limit,
                query=query,
                status=status,
                bundle_id=bundle_id,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.get("/api/v1/rollouts/{rollout_id}", response_model=RolloutTrace)
    async def rollout(rollout_id: str) -> RolloutTrace:
        trace = await selected_source.trace(rollout_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="rollout not found")
        return trace

    @app.post("/api/v1/comparisons", response_model=Comparison)
    async def compare(request: ComparisonRequest) -> Comparison:
        try:
            data = await selected_source.evidence(request.run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        return _comparison(data, request)

    @app.get("/api/v1/runs/{run_id}/compare", response_model=Comparison)
    async def compare_compatibility(
        run_id: str,
        baseline: str,
        candidate: str,
        method: ComparisonMethod = "moving_block_bootstrap",
        confidence_level: float = Query(default=0.95, gt=0.5, lt=1),
        resamples: int = Query(default=2_000, ge=100, le=50_000),
        block_length: int | None = Query(default=None, ge=1, le=10_000),
    ) -> Comparison:
        request = ComparisonRequest(
            run_id=run_id,
            baseline_bundle=baseline,
            candidate_bundle=candidate,
            method=method,
            confidence_level=confidence_level,
            resamples=resamples,
            block_length=block_length,
        )
        try:
            data = await selected_source.evidence(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        return _comparison(data, request)

    @app.post("/api/v1/reports", response_model=ReportReceipt)
    async def create_report(request: ReportRequest) -> ReportReceipt:
        try:
            data = await selected_source.evidence(request.run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        for bundle in (request.baseline_bundle, request.candidate_bundle):
            if bundle is not None and bundle not in data.bundles:
                raise HTTPException(status_code=404, detail=f"bundle not found: {bundle}")
        snapshot, normalized, start_ns, end_ns = _snapshot_dashboard(data, request)
        receipt = ReportReceipt(
            report_id=f"report_{uuid.uuid4().hex[:16]}",
            created_at_ns=time.time_ns(),
            source_generated_at_ns=snapshot.generated_at_ns,
            data_digest=_report_digest(normalized, snapshot),
            request=normalized,
            metric_count=sum(len(series.points) for series in snapshot.series),
            rollout_count=len(snapshot.rollouts),
            task_count=len(snapshot.tasks),
            range_start_ns=start_ns,
            range_end_ns=end_ns,
            source_kind=selected_source.source_kind,
        )
        document = ReportDocument(receipt=receipt, dashboard=snapshot)
        path = report_path(receipt.report_id)
        assert path is not None
        temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        await asyncio.to_thread(report_root.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            temporary_path.write_text,
            document.model_dump_json(),
            encoding="utf-8",
        )
        await asyncio.to_thread(os.replace, temporary_path, path)
        return receipt

    @app.get("/api/v1/reports", response_model=list[ReportReceipt])
    async def reports(limit: int = Query(default=50, ge=1, le=500)) -> list[ReportReceipt]:
        paths = await asyncio.to_thread(_catalog_paths, report_root, limit)
        if not paths:
            return []
        documents = await asyncio.gather(
            *(asyncio.to_thread(path.read_text, encoding="utf-8") for path in paths)
        )
        receipts: list[ReportReceipt] = []
        for raw in documents:
            try:
                receipts.append(ReportDocument.model_validate_json(raw).receipt)
            except ValueError:
                # Catalog availability must not depend on every historical report
                # matching the current schema. Direct access still fails closed.
                continue
        return receipts

    @app.get("/api/v1/reports/{report_id}", response_model=ReportReceipt)
    async def get_report(report_id: str) -> ReportReceipt:
        return (await require_report(report_id)).receipt

    @app.get("/api/v1/reports/{report_id}/snapshot", response_model=ReportDocument)
    async def report_snapshot(report_id: str) -> ReportDocument:
        return await require_report(report_id)

    @app.get("/api/v1/reports/{report_id}/verify", response_model=ReportVerification)
    async def verify_report(report_id: str) -> ReportVerification:
        document = await require_report(report_id)
        actual = _report_digest(document.receipt.request, document.dashboard)
        return ReportVerification(
            report_id=report_id,
            verified=actual == document.receipt.data_digest,
            expected_digest=document.receipt.data_digest,
            actual_digest=actual,
            verified_at_ns=time.time_ns(),
        )

    @app.get("/api/v1/reports/{report_id}/metrics.csv")
    async def report_metrics(report_id: str) -> Response:
        document = await require_report(report_id)
        return Response(
            _metric_csv(document.dashboard),
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{document.receipt.report_id}-metrics.csv"'
                )
            },
        )

    @app.get("/api/v1/reports/{report_id}/export.zip")
    async def report_export(report_id: str) -> Response:
        document = await require_report(report_id)
        actual = _report_digest(document.receipt.request, document.dashboard)
        if actual != document.receipt.data_digest:
            raise HTTPException(status_code=409, detail="report digest verification failed")
        files = {
            "report.json": _canonical(document.model_dump(mode="json")),
            "metrics.csv": _metric_csv(document.dashboard),
            "rollouts.csv": _rollout_csv(document.dashboard),
            "tasks.csv": _task_csv(document.dashboard),
        }
        manifest = {
            "schema_version": "rolloutplane-viz/report-export/v1",
            "report_id": report_id,
            "data_digest": document.receipt.data_digest,
            "files": {
                name: {
                    "size_bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
                for name, body in files.items()
            },
        }
        files["manifest.json"] = _canonical(manifest)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, body)
        return Response(
            stream.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{report_id}-evidence.zip"'},
        )

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend / "index.html").is_file() and (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}", response_class=FileResponse)
        async def spa(path: str) -> FileResponse:
            candidate = (frontend / path).resolve()
            if path and candidate.is_relative_to(frontend.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    return app


app = create_app()
