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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from rolloutplane_viz.models import (
    Comparison,
    Dashboard,
    Estimate,
    ReportReceipt,
    ReportRequest,
    RolloutTrace,
    RunSummary,
    Series,
)
from rolloutplane_viz.source import DataSource, DemoSource, LiveSource

REPORT_ID_PATTERN = re.compile(r"report_[0-9a-f]{16}\Z")


def create_app(
    source: DataSource | None = None,
    report_directory: str | Path | None = None,
) -> FastAPI:
    target = os.environ.get("ROLLOUTPLANE_TARGET")
    selected_source = source or (LiveSource(target) if target else DemoSource())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(selected_source, "close", None)
        if close:
            await close()

    app = FastAPI(title="RolloutPlane Viz", version="0.2.0", lifespan=lifespan)
    app.state.source = selected_source
    report_root = Path(
        report_directory
        or os.environ.get("ROLLOUTPLANE_VIZ_REPORT_DIR", ".rolloutplane-viz/reports")
    )

    def report_path(report_id: str) -> Path | None:
        if not REPORT_ID_PATTERN.fullmatch(report_id):
            return None
        return report_root / f"{report_id}.json"

    async def load_report(report_id: str) -> tuple[ReportReceipt, Dashboard] | None:
        path = report_path(report_id)
        if path is None or not path.is_file():
            return None
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        body = json.loads(raw)
        return (
            ReportReceipt.model_validate(body["receipt"]),
            Dashboard.model_validate(body["dashboard"]),
        )

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "serving", "source": type(selected_source).__name__}

    @app.get("/api/v1/runs", response_model=list[RunSummary])
    async def runs() -> list[RunSummary]:
        return await selected_source.runs()

    @app.get("/api/v1/runs/{run_id}/dashboard", response_model=Dashboard)
    async def dashboard(run_id: str) -> Dashboard:
        try:
            return await selected_source.dashboard(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.get("/api/v1/rollouts/{rollout_id}", response_model=RolloutTrace)
    async def rollout(rollout_id: str) -> RolloutTrace:
        trace = await selected_source.trace(rollout_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="rollout not found")
        return trace

    @app.get("/api/v1/runs/{run_id}/compare", response_model=Comparison)
    async def compare(run_id: str, baseline: str, candidate: str) -> Comparison:
        try:
            data = await selected_source.dashboard(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        if baseline == candidate:
            raise HTTPException(status_code=400, detail="comparison bundles must differ")
        if baseline not in data.bundles or candidate not in data.bundles:
            raise HTTPException(status_code=404, detail="bundle not found")
        estimates: list[Estimate] = []
        comparison_series: list[Series] = []
        for item in data.series:
            baseline_values = [point.value for point in item.points if point.bundle_id == baseline]
            candidate_values = [
                point.value for point in item.points if point.bundle_id == candidate
            ]
            if not baseline_values or not candidate_values:
                continue
            baseline_mean = statistics.fmean(baseline_values)
            candidate_mean = statistics.fmean(candidate_values)
            delta = candidate_mean - baseline_mean
            variance = (
                statistics.variance(baseline_values) / len(baseline_values)
                if len(baseline_values) > 1
                else 0
            )
            variance += (
                statistics.variance(candidate_values) / len(candidate_values)
                if len(candidate_values) > 1
                else 0
            )
            margin = 1.96 * math.sqrt(variance)
            estimates.append(
                Estimate(
                    metric=item.name,
                    unit=item.unit,
                    baseline_mean=baseline_mean,
                    candidate_mean=candidate_mean,
                    absolute_delta=delta,
                    relative_delta=delta / abs(baseline_mean) if baseline_mean else None,
                    confidence_low=delta - margin,
                    confidence_high=delta + margin,
                    sample_count_baseline=len(baseline_values),
                    sample_count_candidate=len(candidate_values),
                )
            )
            comparison_series.append(
                Series(
                    name=item.name,
                    unit=item.unit,
                    points=[
                        point for point in item.points if point.bundle_id in {baseline, candidate}
                    ],
                )
            )
        return Comparison(
            run_id=run_id,
            baseline_bundle=baseline,
            candidate_bundle=candidate,
            estimates=estimates,
            series=comparison_series,
        )

    @app.post("/api/v1/reports", response_model=ReportReceipt)
    async def create_report(request: ReportRequest) -> ReportReceipt:
        try:
            data = await selected_source.dashboard(request.run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        ranged_series = []
        for series in data.series:
            start = math.floor(len(series.points) * request.range_start_percent / 100)
            end = math.ceil(len(series.points) * request.range_end_percent / 100)
            ranged_series.append(series.model_copy(update={"points": series.points[start:end]}))
        snapshot = data.model_copy(update={"series": ranged_series})
        canonical = json.dumps(
            {
                "request": request.model_dump(mode="json"),
                "dashboard": snapshot.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        receipt = ReportReceipt(
            report_id=f"report_{uuid.uuid4().hex[:16]}",
            created_at_ns=time.time_ns(),
            source_generated_at_ns=snapshot.generated_at_ns,
            data_digest=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
            request=request,
            metric_count=sum(len(series.points) for series in snapshot.series),
            rollout_count=len(snapshot.rollouts),
        )
        stored = json.dumps(
            {
                "receipt": receipt.model_dump(mode="json"),
                "dashboard": snapshot.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        path = report_path(receipt.report_id)
        assert path is not None
        temporary_path = path.with_suffix(".tmp")
        await asyncio.to_thread(report_root.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(temporary_path.write_text, stored, encoding="utf-8")
        await asyncio.to_thread(os.replace, temporary_path, path)
        return receipt

    @app.get("/api/v1/reports/{report_id}", response_model=ReportReceipt)
    async def get_report(report_id: str) -> ReportReceipt:
        stored = await load_report(report_id)
        if not stored:
            raise HTTPException(status_code=404, detail="report not found")
        return stored[0]

    @app.get("/api/v1/reports/{report_id}/metrics.csv")
    async def report_metrics(report_id: str) -> Response:
        stored = await load_report(report_id)
        if not stored:
            raise HTTPException(status_code=404, detail="report not found")
        receipt, data = stored
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["metric", "unit", "timestamp_ns", "value", "bundle_id"])
        for series in data.series:
            for point in series.points:
                writer.writerow(
                    [series.name, series.unit, point.timestamp_ns, point.value, point.bundle_id]
                )
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{receipt.report_id}-metrics.csv"'
            },
        )

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.exists():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/{path:path}", response_class=FileResponse)
        async def spa(path: str) -> FileResponse:
            candidate = (frontend / path).resolve()
            if path and candidate.is_relative_to(frontend.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend / "index.html")

    return app


app = create_app()
