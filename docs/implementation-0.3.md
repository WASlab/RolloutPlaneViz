# RolloutPlane Viz 0.3 technical implementation

## 1. Outcome

RolloutPlane Viz 0.3 is a read-only research workbench over the RolloutPlane 0.2 control plane. It is designed to answer four operationally distinct questions:

1. What is happening in a run now?
2. Did a candidate runtime and policy bundle outperform a baseline?
3. Which tasks, stop conditions, or individual trajectories explain the aggregate result?
4. Can the exact evidence behind a conclusion be frozen, verified, and transported?

The release intentionally keeps visualization outside the trainer, inference server, and environment-worker processes. The only live integration is a read-only gRPC client. UI polling therefore cannot mutate leases, publish bundles, append rollout events, or alter training state.

The distributable Python metadata and lockfile pin RolloutPlane to the exact public 0.2 implementation commit `41b585e5111e5087251ee24ec54c3e96712aeff7`. Hatch explicitly permits this direct reference. A clean install therefore receives the same contracts on Windows, Ubuntu, and CI without a machine-specific sibling checkout.

## 2. System shape

```text
┌──────────────────────────────────────────────────────────────┐
│ React 19 + ECharts 6                                        │
│ observe · compare · reports · rollout inspector             │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP/JSON
┌──────────────────────────────▼───────────────────────────────┐
│ FastAPI projection and evidence service                     │
│ source cache · statistics · snapshots · exports             │
└──────────────────────────────┬───────────────────────────────┘
                               │ read-only gRPC / optional mTLS
┌──────────────────────────────▼───────────────────────────────┐
│ RolloutPlane 0.2                                            │
│ runs · checkpoints · bundles · leases · events · metrics    │
└──────────────────────────────────────────────────────────────┘
```

`DemoSource` provides a deterministic development dataset. `LiveSource` implements the same interface against RolloutPlane. The frontend does not know which source is active; `/api/v1/metadata` exposes the source kind, refresh interval, chart cap, report store, and supported feature flags.

## 3. RolloutPlane 0.2 live adapter

### 3.1 Source contracts

The adapter consumes the following RolloutPlane records:

- `TrainingRun` for identity, algorithm, model, environment, lifecycle, and timestamps.
- `Checkpoint` for the latest policy checkpoint and its associated bundle.
- `InferenceBundle` for target, tokenizer, engine, optional speculator, sampling contract, policy step, environment contract, reward contract, labels, and content digests.
- `RolloutLease` for authoritative rollout-to-run, bundle, worker, task, checkpoint, attempt, and decision-chunk association.
- `RolloutEvent` for ordered lifecycle, termination, actor-state, reward, and trace evidence.
- `MetricRecord` for time-series analysis and display.

Runs, checkpoints, leases, events, and metrics are read through their paginated APIs until the server returns no cursor. Each scan is bounded by `ROLLOUTPLANE_VIZ_MAX_SOURCE_RECORDS`; exceeding the bound fails the projection instead of silently returning partial analytical evidence.

Metric and event scans for a dashboard share a nanosecond cutoff captured before the concurrent requests begin. This prevents new event or metric pages from extending beyond the declared source timestamp while the snapshot is assembled.

### 3.2 Strict rollout projection

Rollout rows are reconstructed from the authoritative lease and event stream rather than inferred from metric labels. The projection retains:

- rollout and task identities;
- task family;
- pinned bundle and worker;
- attempt and decision-chunk number;
- exact start and end times;
- turns, reward, state, and stop reason.

Terminal events remain visible in traces, including `agent death`, environment faults, truncation, and successful completion. This matters for Factorio: a rollout can stop progressing because of game-state failure rather than policy indecision, and those cases must be distinguishable during curriculum design.

### 3.3 Provenance

Every observed bundle is resolved with a concurrency-limited fetch and exposed as a `BundleSummary`. The UI can therefore show the exact policy step and the identities and digests of the target model, tokenizer, inference engine, and speculator, plus sampling and environment/reward contracts. Comparisons are between complete runtime bundles, not merely friendly model names.

### 3.4 TLS

The live client supports insecure development transport, server-authenticated TLS, and mTLS. Root certificate, client key, certificate chain, security override, and test server-name override are supplied by file path through environment variables. No TLS material is serialized to the browser.

## 4. Presentation data versus evidence data

The source has two projections:

- `dashboard(run_id)` returns data bounded for interactive presentation: each series is min/max downsampled and the live rollout table initially contains the most recent 200 rows.
- `evidence(run_id)` returns the complete records fetched under the same cutoff, subject only to the explicit source-record safety bound.

Comparisons and reports always call `evidence`. This prevents a chart rendering optimization from changing sample counts, confidence intervals, task aggregates, report hashes, or exported records.

The min/max downsampler preserves the first and last point and retains local extrema within each bucket. It is intended to preserve spikes for diagnosis, not to supply analytical samples.

Rollout search, status filters, and bundle filters use the source-side rollout endpoint. The endpoint returns a bounded page and a total count so the browser need not receive the entire ledger merely to inspect a task or stop reason.

## 5. Timestamp integrity

Contemporary Unix nanosecond timestamps exceed JavaScript's exact integer range. Each point therefore has two time fields:

- `timestamp_ns`: the exact integer used in reports, filters, cutoffs, digests, and exports;
- `timestamp_ms`: a derived browser-safe integer used only by ECharts and date formatting.

This prevents visually plausible but non-reproducible time shifts caused by converting a nanosecond epoch directly into a JavaScript `number`.

## 6. Statistical comparison

`POST /api/v1/comparisons` accepts the run, baseline bundle, candidate bundle, optional metric list, confidence level, and estimator settings. The response records the normalized request, source snapshot time, estimate generation time, selected full-resolution series, bundle provenance, and a SHA-256 digest over the request and selected evidence.

### 6.1 Moving-block bootstrap

The default estimator is a circular moving-block bootstrap. Values are ordered by metric timestamp separately within each bundle. A resample is constructed by selecting random contiguous circular blocks until the original sample length is reached. Candidate and baseline means are resampled independently, and their difference is recorded.

The default block length is:

```text
round(min(n_baseline, n_candidate) ** (1 / 3))
```

clamped to the shorter series. An explicit block length can be supplied. The confidence interval uses percentile quantiles from the bootstrap deltas. The response also includes bootstrap standard error, the empirical probability that the candidate delta is positive, absolute and relative change, sample sizes, and a pooled standardized effect where defined.

The pseudo-random seed is derived from the run, bundles, metric, resample count, block setting, and confidence level. Repeating an identical request over identical evidence yields identical estimates.

This estimator preserves short-range ordering within blocks and is a better default than pretending sequential rollout measurements are independent. It does not solve cross-seed confounding, nonstationary curriculum allocation, unequal checkpoint windows, or paired-task design.

### 6.2 Independent normal approximation

The compatibility estimator computes a difference of means, the independent-sample standard error, and a normal confidence interval. It remains useful for controlled independent samples and regression comparison with the 0.2 interface. It should not be the default for a temporally autocorrelated training trace.

## 7. Reproducible reports

`POST /api/v1/reports` converts a visible percentage range or supplied exact nanosecond range into an exact immutable snapshot. It then:

1. filters full-resolution metric evidence to the exact range;
2. filters rollouts by exact start timestamp;
3. recomputes task aggregates, KPI values, termination percentages, and present bundles from the filtered evidence;
4. records the selected report sections and baseline/candidate bundle choices;
5. computes a canonical SHA-256 digest over the normalized request and snapshot;
6. writes the complete `ReportDocument` atomically through a temporary file and `os.replace`.

The receipt reports metric, rollout, and task counts, exact bounds, source timestamp, source kind, capture timestamp, and data digest.

### 7.1 Verification and corruption behavior

`GET /api/v1/reports/{id}/verify` recomputes the digest from the stored request and snapshot. A syntactically valid but modified document returns `verified: false`. Export fails closed with HTTP 409 when verification fails. A structurally invalid individual report also fails closed.

The catalog is availability-isolated: legacy or malformed files are skipped so they cannot hide valid receipts. Direct access to such a known report still returns a conflict rather than pretending it is valid.

### 7.2 Portable evidence ZIP

The export contains:

- `report.json`: canonical report document;
- `metrics.csv`: full-resolution metric points;
- `rollouts.csv`: selected rollout evidence and stop metadata;
- `tasks.csv`: task-family aggregates;
- `manifest.json`: schema version, receipt digest, and the size and SHA-256 of each other file.

ZIP member timestamps and permissions are fixed, so packaging metadata does not introduce meaningless variation between downloads of the same stored report.

## 8. Frontend implementation

The UI is a quiet graphite research workbench with one electric cyan accent. Dense scientific evidence—not cards or decoration—sets the hierarchy.

### 8.1 Observe

- current run, lifecycle, algorithm, active bundle, source snapshot, and policy step;
- learning-signal and inference-plane SVG time series;
- connected ECharts groups for synchronized cursor and zoom range;
- LTTB rendering support in ECharts over the server-bounded point projection;
- task success, wall-clock allocation, and termination distributions;
- server-filtered rollout table;
- an event-level trace inspector with explicit close and keyboard dismissal behavior.

### 8.2 Compare

- baseline and candidate bundle selection;
- moving-block or independent-normal estimator selection;
- 90%, 95%, or 99% confidence controls;
- resample and optional block-length controls;
- relative movement chart;
- interval, probability, effect-size, block-length, and sample-count table;
- comparison evidence digest;
- side-by-side content-addressed runtime provenance.

### 8.3 Reports

- report-section selection;
- current linked-chart range capture;
- immutable receipt creation;
- digest verification status;
- stored report catalog;
- deterministic evidence ZIP and metrics CSV links;
- vector print styling.

Charts render as SVG for inspection and publication. ECharts ARIA output gives the charts textual series summaries. Navigation buttons expose explicit pressed state. The responsive layout was exercised at a 375-pixel browser content width without horizontal body overflow.

## 9. HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | liveness and source kind |
| `GET` | `/api/v1/metadata` | version, limits, report store, features |
| `GET` | `/api/v1/runs` | run catalog |
| `GET` | `/api/v1/runs/{run}/dashboard` | bounded interactive projection |
| `GET` | `/api/v1/runs/{run}/rollouts` | searched and filtered rollout page |
| `GET` | `/api/v1/rollouts/{rollout}` | ordered rollout trace |
| `POST` | `/api/v1/comparisons` | full-evidence statistical comparison |
| `GET` | `/api/v1/runs/{run}/compare` | compatibility comparison endpoint |
| `POST` | `/api/v1/reports` | create immutable snapshot |
| `GET` | `/api/v1/reports` | valid receipt catalog |
| `GET` | `/api/v1/reports/{id}` | receipt metadata |
| `GET` | `/api/v1/reports/{id}/snapshot` | complete stored document |
| `GET` | `/api/v1/reports/{id}/verify` | recompute snapshot digest |
| `GET` | `/api/v1/reports/{id}/metrics.csv` | metric evidence export |
| `GET` | `/api/v1/reports/{id}/export.zip` | verified portable package |

All public request and response bodies use Pydantic models with extra fields forbidden. Comparison bundles must differ, ranges must have positive width, exact bounds must be supplied together, and resample, confidence, page, and block controls are bounded.

## 10. Operational configuration

The live source is activated by `ROLLOUTPLANE_TARGET`. Security and performance controls are documented in the repository README. The essential production behavior is:

- use mTLS where the RolloutPlane control plane requires authenticated readers;
- mount `ROLLOUTPLANE_VIZ_REPORT_DIR` on durable storage;
- keep the Viz service off inference-critical CPU paths;
- tune the refresh interval before increasing browser concurrency;
- treat the source-record limit as a safety boundary, not as a sampling mechanism;
- place a read replica or telemetry warehouse behind the adapter when million-record scans become routine.

The project runs on Windows for local development and is CI-tested on Windows and Ubuntu. It is not coupled to Docker Desktop. Production training clusters can run the same Python service on Ubuntu while the browser remains platform-independent.

## 11. Validation completed

The 0.3 implementation has been validated with:

- Ruff over backend source and tests;
- strict mypy over backend source and tests;
- six backend tests, including an in-process real RolloutPlane 0.2 gRPC service;
- a live-adapter test proving chart downsampling does not alter evidence-series cardinality;
- report creation, catalog, exact snapshot, verification, CSV, deterministic ZIP, legacy-file isolation, and tamper-failure tests;
- npm lockfile installation with zero reported vulnerabilities;
- TypeScript project compilation;
- a production Vite build;
- desktop browser inspection of Observe, Compare, Reports, receipt verification, and rollout traces;
- narrow-screen inspection at 375 pixels with no page-level horizontal overflow;
- a browser console check with no warnings or errors.

## 12. Known limitations

- The moving-block bootstrap operates on each metric stream independently. It is not yet seed-stratified, task-paired, or curriculum-reweighted.
- Runs, checkpoints, and leases do not currently share an MVCC transaction with event and metric reads; the explicit event/metric cutoff prevents forward drift but does not make the entire remote projection transactionally atomic.
- The live cache is process-local. Multiple Viz replicas will each query RolloutPlane unless a shared cache or read replica is introduced.
- Reports are immutable files, not signed attestations. A digest detects modification but does not prove who created the report.
- Catalog schema migration is not implemented; legacy invalid entries are isolated and skipped.
- Report section selection is recorded in the receipt, while the stored evidence document intentionally remains complete enough for later verification and alternate rendering.
- Rollout pagination is offset-based at the Viz HTTP layer even though the upstream source scan is keyset-paginated.
- The frontend build includes ECharts in a sizeable client bundle. It is acceptable for a local research console but should be split or cached aggressively before wide-area multi-user deployment.
- Viz currently consumes RolloutPlane directly. It does not yet have an adapter for an external warehouse, OpenTelemetry store, or AgentENV-native telemetry source.
- Until RolloutPlane is published to a Python package registry, the Viz wheel intentionally carries a direct GitHub commit dependency and requires Git/network access during a fresh dependency install.

## 13. Prioritized future work

1. Add seed-, task-, and checkpoint-window-aware comparison designs, including paired bootstrap and hierarchical estimates.
2. Add a warehouse/read-replica adapter so historical analysis never scans the active control-plane database.
3. Add cryptographic report signing and optional Sigstore provenance for published benchmark artifacts.
4. Add a schema-versioned report migration tool and catalog diagnostics for isolated legacy files.
5. Add comparison gates that can be evaluated by automation before a new inference bundle or speculator is promoted.
6. Add per-turn reward-vector, advantage, policy-lag, KL, entropy, and process-credit views needed by Prime-RL experiments.
7. Add Factorio-specific causal panels: production dependency graphs, bottleneck shifts, actor-state transitions, intervention deltas, and holdout verifier timelines.
8. Add speculator drift views correlating acceptance, rejected draft length, verifier time, target policy step, and wall-clock benefit.
9. Add streaming deltas or server-sent events after measurement proves polling to be a limiting cost.
10. Split the frontend by workspace and publish a production container or Helm chart once the deployment target is fixed.

## 14. Potential extensions

- A benchmark publication mode that emits a static site from signed report packages.
- Cross-run and multi-seed experiment collections rather than only within-run bundle comparison.
- OPSD views that place student state, privileged teacher diagnosis, chosen intervention, and verified state delta on one timeline.
- Counterfactual branch visualization for shared checkpoints and group-local credit.
- A curriculum scheduler feedback view showing difficulty, learning progress, sampling probability, and state coverage.
- A common telemetry adapter for Factorio, Unciv, and later environments while preserving game-specific evidence panels.
- Notebook bindings that load a verified report ZIP directly into Polars, pandas, or DuckDB without querying the live service.

## 15. Open questions

1. What is the correct experimental unit for Factorio learning curves: rollout, checkpoint, shared initial state, map seed, task template, or a hierarchy of these?
2. Which state-quality signals are stable enough to compare policy bundles without rewarding mere factory size or short-lived inventory accumulation?
3. Should report receipts remain local research artifacts, or become signed promotion records consumed by RolloutPlane itself?
4. At what scale should Viz stop reading control-plane records and require a telemetry warehouse?
5. Which privileged-teacher facts should be visualized for research but provably withheld from the student trajectory?
6. How should target-model and DSpark speculator updates be aligned in comparisons when they advance at different cadences?
7. Should cross-game views share one strict schema, or should RolloutPlane Viz expose a stable core plus environment-owned extension documents?
