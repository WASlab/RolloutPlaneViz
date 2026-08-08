from __future__ import annotations

from pathlib import Path

import grpc  # type: ignore[import-untyped]
import pytest
from rolloutplane import (
    ArtifactRef,
    Checkpoint,
    EventType,
    InferenceBundle,
    MetricPoint,
    RunStatus,
    RuntimeComponent,
    TrainingRun,
)
from rolloutplane.adapters import EnvironmentRecorder
from rolloutplane.contracts.proto import rolloutplane_pb2_grpc as rpc
from rolloutplane.registry import SQLiteStore
from rolloutplane.server.service import RolloutPlaneService

from rolloutplane_viz.source import LiveSource


@pytest.mark.asyncio
async def test_live_source_projects_rolloutplane_v02_contracts(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "live.db")
    run = store.register_run(
        TrainingRun(
            name="live-viz-smoke",
            algorithm="grpo",
            model="tiny-policy",
            environment="factorio/microtasks-v1",
        )
    )
    run = store.update_run_status(run.run_id, RunStatus.RUNNING)
    bundle = store.register_bundle(
        InferenceBundle(
            target=RuntimeComponent(
                name="tiny-policy", version="step-7", digest="sha256:target-step-7"
            ),
            tokenizer=RuntimeComponent(name="tokenizer", version="1", digest="sha256:tokenizer"),
            engine=RuntimeComponent(name="vllm", version="0.24", digest="sha256:vllm"),
            policy_step=7,
            sampling={
                "temperature": 1.0,
                "top_p": 1.0,
                "logprobs": True,
                "max_completion_tokens": 128,
            },
            environment_contract="factorio/microtasks-v1",
            reward_contract="factorio/reward-vector/v1",
        )
    )
    checkpoint = store.register_checkpoint(
        Checkpoint(
            run_id=run.run_id,
            step=7,
            artifact=ArtifactRef(uri="memory://step-7", digest="sha256:checkpoint-step-7"),
            bundle_id=bundle.bundle_id,
        )
    )
    lease = store.acquire_lease(
        rollout_id="live-rollout-1",
        bundle_id_or_alias=bundle.bundle_id or "",
        worker_id="worker-1",
        ttl_seconds=3_600,
        run_id=run.run_id,
        task_id="repair/reversed-inserter/0001",
        checkpoint_id=checkpoint.checkpoint_id,
        labels={"task_family": "repair"},
    )
    recorder = EnvironmentRecorder(lease)
    events = [
        recorder.event(EventType.ROLLOUT_STARTED),
        recorder.event(
            EventType.REWARD_RECORDED,
            payload={"reward_vector": {"task_success": 1.0}},
            metrics=(
                MetricPoint(name="reward.mean", value=1.0, unit="reward"),
                MetricPoint(name="success.rate", value=1.0, unit="ratio"),
                MetricPoint(name="throughput.target_tokens", value=120.0, unit="token/s"),
            ),
        ),
    ]
    events.extend(
        recorder.event(
            EventType.CUSTOM,
            metrics=(MetricPoint(name="reward.mean", value=index / 10, unit="reward"),),
        )
        for index in range(12)
    )
    events.extend(
        [
            recorder.termination(
                reason="success",
                terminal=True,
                truncated=False,
                actor_state={"alive": True},
            ),
            recorder.event(EventType.ROLLOUT_COMPLETED),
        ]
    )
    store.append_events(events)
    store.release_lease(lease.lease_id)

    server = grpc.aio.server()
    rpc.add_RolloutPlaneServicer_to_server(  # type: ignore[no-untyped-call]
        RolloutPlaneService(store), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    source = LiveSource(f"127.0.0.1:{port}", refresh_seconds=0.1, max_series_points=4)
    try:
        runs = await source.runs()
        assert [item.run_id for item in runs] == [run.run_id]
        assert runs[0].current_checkpoint == checkpoint.checkpoint_id
        assert runs[0].current_bundle == bundle.bundle_id

        dashboard = await source.dashboard(run.run_id)
        assert dashboard.bundle_details[0].policy_step == 7
        assert dashboard.bundle_details[0].target_digest == "sha256:target-step-7"
        assert dashboard.series[0].points[0].timestamp_ms is not None
        assert dashboard.rollouts[0].task == "repair/reversed-inserter/0001"
        assert dashboard.rollouts[0].task_family == "repair"
        assert dashboard.rollouts[0].status == "completed"
        reward_display = next(item for item in dashboard.series if item.name == "reward.mean")
        evidence = await source.evidence(run.run_id)
        reward_evidence = next(item for item in evidence.series if item.name == "reward.mean")
        assert len(reward_display.points) <= 4
        assert len(reward_evidence.points) == 13

        page = await source.rollouts(
            run.run_id,
            offset=0,
            limit=10,
            query="reversed",
        )
        assert page.total == 1
        trace = await source.trace("live-rollout-1")
        assert trace is not None
        assert trace.events[-1].event_type == EventType.ROLLOUT_COMPLETED
    finally:
        await source.close()
        await server.stop(grace=None)
        store.close()
