# RolloutPlane Viz

A read-only research visualization surface for RolloutPlane. It turns rollout,
reward, wall-clock, speculative-decoding, and termination evidence into linked,
publication-quality operational views without adding work to the training path.

## Boundary

The dashboard polls a separate FastAPI gateway. The gateway queries RolloutPlane
over gRPC or serves a deterministic demonstration dataset. It never imports into
the trainer, inference engine, or environment worker.

The live gateway caches snapshots so concurrent browser viewers do not multiply
control-plane queries. At large scale, point it at a read replica or exported
telemetry store; visualization should never compete with rollout writers for CPU,
I/O, or database locks.

## Development

```bash
cd backend
uv sync --extra dev
uv run pytest
uv run rolloutplane-viz

cd ../frontend
npm ci
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8057`. For a production artifact:

```bash
cd frontend && npm run build
cd ../backend && uv run rolloutplane-viz
```

The backend serves `frontend/dist` automatically when it exists.

Set `ROLLOUTPLANE_TARGET=host:50051` to use a live control plane. With no target,
the UI uses a seeded demonstration run designed to exercise every visualization.
