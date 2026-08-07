from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rolloutplane_viz.models import Dashboard, RolloutTrace, RunSummary
from rolloutplane_viz.source import DataSource, DemoSource, LiveSource


def create_app(source: DataSource | None = None) -> FastAPI:
    target = os.environ.get("ROLLOUTPLANE_TARGET")
    selected_source = source or (LiveSource(target) if target else DemoSource())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(selected_source, "close", None)
        if close:
            await close()

    app = FastAPI(title="RolloutPlane Viz", version="0.1.0", lifespan=lifespan)
    app.state.source = selected_source

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
