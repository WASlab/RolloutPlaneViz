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


def test_compare_and_reproducible_report(tmp_path) -> None:
    with TestClient(create_app(DemoSource(), report_directory=tmp_path)) as client:
        comparison = client.get(
            "/api/v1/runs/repair-grpo-4b-v1/compare",
            params={
                "baseline": "theta-042 / phi-04",
                "candidate": "theta-184 / phi-12",
            },
        )
        assert comparison.status_code == 200
        assert comparison.json()["estimates"][0]["sample_count_baseline"] == 24
        receipt = client.post(
            "/api/v1/reports",
            json={
                "run_id": "repair-grpo-4b-v1",
                "baseline_bundle": "theta-042 / phi-04",
                "candidate_bundle": "theta-184 / phi-12",
            },
        )
        assert receipt.status_code == 200
        report_id = receipt.json()["report_id"]
        assert receipt.json()["data_digest"].startswith("sha256:")
        assert (tmp_path / f"{report_id}.json").is_file()
        csv_response = client.get(f"/api/v1/reports/{report_id}/metrics.csv")
        assert csv_response.status_code == 200
        assert csv_response.text.startswith("metric,unit,timestamp_ns")
        assert client.get("/api/v1/reports/not-a-report").status_code == 404
