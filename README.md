# RolloutPlane Viz

RolloutPlane Viz is the evidence workbench for [RolloutPlane](https://github.com/WASlab/RolloutPlane). It projects live rollout, reward, wall-clock, speculative-decoding, task, termination, and runtime-provenance records into linked SVG charts and reproducible research artifacts. It stays outside the rollout hot path.

Version 0.3 adds the production RolloutPlane 0.2 adapter, autocorrelation-aware bundle comparisons, server-filtered rollout inspection, and verifiable evidence packages.

## Workspaces

- **Observe** links learning and inference charts by cursor and time range, summarizes curriculum and termination behavior, and opens event-level rollout traces.
- **Compare** evaluates a candidate inference bundle against a baseline with either a moving-block bootstrap or an independent normal approximation. Every result includes exact bundle provenance and a digest of the selected inputs.
- **Reports** freezes an exact time slice into an immutable receipt. Stored snapshots can be verified later and exported as a deterministic ZIP containing canonical JSON, metrics, rollouts, tasks, and a file-hash manifest.

Interactive charts use a bounded min/max projection. Comparisons and reports use the complete source evidence up to the configured safety limit, never the downsampled display points.

## Architecture boundary

```text
browser
  │ HTTP / JSON
  ▼
RolloutPlane Viz gateway
  │ read-only gRPC, optionally mTLS
  ▼
RolloutPlane 0.2 control plane
  │
  ├─ trainer / Prime-RL
  ├─ inference / vLLM + speculator
  └─ environment workers
```

The gateway performs no writes to RolloutPlane. A short source cache prevents browser fan-out from multiplying control-plane reads. At training scale, run Viz separately from latency-sensitive inference and point it at a read replica or exported telemetry service when available.

## Development

Python 3.11+ and Node.js 24 are used in CI.

```bash
cd backend
uv sync --extra dev --locked
uv run ruff check rolloutplane_viz tests
uv run mypy rolloutplane_viz tests
uv run pytest

cd ../frontend
npm ci
npm run typecheck
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8057`. To build and serve the integrated artifact:

```bash
cd frontend
npm run build

cd ../backend
uv run rolloutplane-viz --host 127.0.0.1 --port 8057
```

If `frontend/dist` is present, the backend serves the SPA and its assets. With no live target, the application starts with a seeded deterministic dataset that exercises every visualization.

## Live configuration

| Variable | Default | Purpose |
|---|---:|---|
| `ROLLOUTPLANE_TARGET` | unset | RolloutPlane gRPC target, for example `control-plane:50051` |
| `ROLLOUTPLANE_SECURE` | inferred | Force secure or insecure gRPC transport |
| `ROLLOUTPLANE_ROOT_CERTIFICATE` | unset | PEM root certificate path |
| `ROLLOUTPLANE_CLIENT_PRIVATE_KEY` | unset | PEM mTLS client key path |
| `ROLLOUTPLANE_CLIENT_CERTIFICATE_CHAIN` | unset | PEM mTLS client certificate path |
| `ROLLOUTPLANE_SERVER_NAME_OVERRIDE` | unset | TLS server-name override for controlled test deployments |
| `ROLLOUTPLANE_VIZ_REFRESH_SECONDS` | `10` | Live source snapshot cache duration |
| `ROLLOUTPLANE_VIZ_MAX_SERIES_POINTS` | `2000` | Per-series interactive chart limit |
| `ROLLOUTPLANE_VIZ_MAX_SOURCE_RECORDS` | `1000000` | Hard bound for any paginated source scan |
| `ROLLOUTPLANE_VIZ_REPORT_DIR` | `.rolloutplane-viz/reports` | Durable immutable report directory |

The complete 0.3 design, statistical assumptions, API, deployment notes, validation record, limitations, and next questions are documented in [docs/implementation-0.3.md](docs/implementation-0.3.md).
