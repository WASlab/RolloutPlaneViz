from fastapi.testclient import TestClient

from rolloutplane_viz.app import create_app
from rolloutplane_viz.source import DemoSource


def test_dashboard_and_trace() -> None:
    with TestClient(create_app(DemoSource())) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        runs = client.get("/api/v1/runs").json()
        assert len(runs) == 1
        dashboard = client.get(f"/api/v1/runs/{runs[0]['run_id']}/dashboard").json()
        assert len(dashboard["series"]) == 4
        assert dashboard["kpis"][0]["label"] == "Validation success"
        rollout_id = dashboard["rollouts"][0]["rollout_id"]
        trace = client.get(f"/api/v1/rollouts/{rollout_id}").json()
        assert trace["events"][-1]["event_type"] == "rollout.termination.recorded"


def test_missing_run_is_404() -> None:
    with TestClient(create_app(DemoSource())) as client:
        assert client.get("/api/v1/runs/missing/dashboard").status_code == 404
