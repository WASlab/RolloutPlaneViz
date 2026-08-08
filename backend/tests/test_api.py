import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from rolloutplane_viz.app import create_app
from rolloutplane_viz.source import DemoSource


def test_dashboard_trace_metadata_and_rollout_filters() -> None:
    with TestClient(create_app(DemoSource())) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["source"] == "demo"
        metadata = client.get("/api/v1/metadata").json()
        assert metadata["version"] == "0.3.0"
        assert "moving-block-bootstrap" in metadata["features"]

        runs = client.get("/api/v1/runs").json()
        assert len(runs) == 1
        dashboard = client.get(f"/api/v1/runs/{runs[0]['run_id']}/dashboard").json()
        assert len(dashboard["series"]) == 4
        assert dashboard["kpis"][0]["label"] == "Validation success"
        assert dashboard["series"][0]["points"][0]["timestamp_ms"] < 10**13
        assert dashboard["bundle_details"][-1]["policy_step"] == 184

        rollout_id = dashboard["rollouts"][0]["rollout_id"]
        trace = client.get(f"/api/v1/rollouts/{rollout_id}").json()
        assert trace["events"][-1]["event_type"] == "rollout.completed"

        filtered = client.get(
            f"/api/v1/runs/{runs[0]['run_id']}/rollouts",
            params={"query": "depleted", "limit": 5},
        ).json()
        assert 0 < filtered["total"]
        assert all("depleted" in row["task"].lower() for row in filtered["items"])


def test_missing_run_is_404() -> None:
    with TestClient(create_app(DemoSource())) as client:
        assert client.get("/api/v1/runs/missing/dashboard").status_code == 404


def test_block_bootstrap_comparison() -> None:
    with TestClient(create_app(DemoSource())) as client:
        response = client.post(
            "/api/v1/comparisons",
            json={
                "run_id": "repair-grpo-4b-v1",
                "baseline_bundle": "theta-042 / phi-04",
                "candidate_bundle": "theta-184 / phi-12",
                "method": "moving_block_bootstrap",
                "resamples": 500,
                "block_length": 4,
            },
        )
        assert response.status_code == 200
        comparison = response.json()
        assert comparison["method"] == "moving_block_bootstrap"
        assert comparison["data_digest"].startswith("sha256:")
        assert comparison["estimates"][0]["sample_count_baseline"] == 24
        assert comparison["estimates"][0]["block_length"] == 4
        assert 0 <= comparison["estimates"][0]["probability_candidate_greater"] <= 1
        assert len(comparison["bundle_details"]) == 2


def test_reproducible_report_catalog_verify_and_export(tmp_path: Path) -> None:
    # A report written by an older schema must not make newer receipts undiscoverable.
    (tmp_path / "report_0000000000000000.json").write_text(
        '{"receipt":{"legacy":true}}', encoding="utf-8"
    )
    with TestClient(create_app(DemoSource(), report_directory=tmp_path)) as client:
        receipt_response = client.post(
            "/api/v1/reports",
            json={
                "run_id": "repair-grpo-4b-v1",
                "baseline_bundle": "theta-042 / phi-04",
                "candidate_bundle": "theta-184 / phi-12",
                "range_start_percent": 20,
                "range_end_percent": 80,
            },
        )
        assert receipt_response.status_code == 200
        receipt = receipt_response.json()
        report_id = receipt["report_id"]
        assert receipt["data_digest"].startswith("sha256:")
        assert receipt["range_start_ns"] < receipt["range_end_ns"]
        path = tmp_path / f"{report_id}.json"
        assert path.is_file()

        catalog = client.get("/api/v1/reports").json()
        assert [item["report_id"] for item in catalog] == [report_id]
        snapshot = client.get(f"/api/v1/reports/{report_id}/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["receipt"]["task_count"] == len(
            snapshot.json()["dashboard"]["tasks"]
        )
        verification = client.get(f"/api/v1/reports/{report_id}/verify").json()
        assert verification["verified"] is True

        csv_response = client.get(f"/api/v1/reports/{report_id}/metrics.csv")
        assert csv_response.status_code == 200
        assert csv_response.text.startswith("metric,unit,timestamp_ns")
        export = client.get(f"/api/v1/reports/{report_id}/export.zip")
        assert export.status_code == 200
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            assert set(archive.namelist()) == {
                "report.json",
                "metrics.csv",
                "rollouts.csv",
                "tasks.csv",
                "manifest.json",
            }
            assert json.loads(archive.read("manifest.json"))["report_id"] == report_id

        body = json.loads(path.read_text(encoding="utf-8"))
        body["dashboard"]["kpis"][0]["value"] += 0.01
        path.write_text(json.dumps(body), encoding="utf-8")
        assert client.get(f"/api/v1/reports/{report_id}/verify").json()["verified"] is False
        assert client.get(f"/api/v1/reports/{report_id}/export.zip").status_code == 409
        assert client.get("/api/v1/reports/not-a-report").status_code == 404
