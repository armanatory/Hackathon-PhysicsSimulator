"""The slab status route serves artifacts and fails closed on unverified content."""

import json

import pytest
from fastapi.testclient import TestClient

from app import slab_validation
from app.main import app


client = TestClient(app)


@pytest.fixture
def report_path(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    monkeypatch.setattr(slab_validation, "REPORT_PATH", path)
    return path


def _completed_report() -> dict[str, object]:
    return {
        "label": "allsolve_slab_validation",
        "status": "completed",
        "validated": True,
        "wavelength_nm": 800.0,
        "slab_index": 1.5,
        "slab_thickness_nm": 200.0,
        "project_id": "slab-project",
        "project_url": "https://allsolve.quanscient.com/project/slab-project",
        "runs": [{"mesh_id": "mesh-1", "simulation_id": "sim-1", "job_id": "job-1"}],
        "results": {"reflection": 0.08, "transmission": 0.92},
        "analytical_reference": {"reflection": 0.08, "transmission": 0.92},
        "checks": {"energy_balance": True, "fresnel_agreement": True},
    }


def test_missing_slab_report_is_not_run(report_path) -> None:
    response = client.get("/api/validation/slab")
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_run",
        "validated": False,
        "purpose": "optical_slab_benchmark",
        "synthetic": False,
    }
    assert not report_path.exists()


def test_completed_slab_report_preserves_results_and_provenance(report_path) -> None:
    report = _completed_report()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    before = report_path.read_bytes()
    response = client.get("/api/validation/slab")
    assert response.status_code == 200
    assert response.json() == {
        **report,
        "purpose": "optical_slab_benchmark",
        "synthetic": False,
    }
    assert report_path.read_bytes() == before


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_incomplete_slab_report_cannot_be_validated(report_path, status) -> None:
    report = {**_completed_report(), "status": status}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    response = client.get("/api/validation/slab")
    assert response.json()["status"] == status
    assert response.json()["validated"] is False


def test_slab_report_without_runs_cannot_be_validated(report_path) -> None:
    report_path.write_text(json.dumps({**_completed_report(), "runs": []}), encoding="utf-8")
    assert client.get("/api/validation/slab").json()["validated"] is False


@pytest.mark.parametrize(
    "content",
    [
        "{unfinished",
        "[]",
        json.dumps({**_completed_report(), "label": "synthetic_surrogate_demo"}),
        json.dumps({**_completed_report(), "validated": "true"}),
        json.dumps({**_completed_report(), "status": []}),
        json.dumps({**_completed_report(), "runs": "job-1"}),
        json.dumps({**_completed_report(), "runs": [None]}),
        json.dumps({**_completed_report(), "wavelength_nm": float("nan")}),
        json.dumps(_completed_report()).replace("800.0", "1e309"),
    ],
)
def test_malformed_slab_report_is_unverified(report_path, content) -> None:
    report_path.write_text(content, encoding="utf-8")
    response = client.get("/api/validation/slab")
    assert response.status_code == 200
    assert response.json()["status"] == "unverified"
    assert response.json()["validated"] is False
    assert response.json()["synthetic"] is False
    assert "error" in response.json()


def test_slab_report_does_not_enable_allsolve_jobs(report_path, monkeypatch) -> None:
    report_path.write_text(json.dumps(_completed_report()), encoding="utf-8")
    monkeypatch.setenv("ALLSOLVE_ACCESS_KEY", "test-id")
    monkeypatch.setenv("ALLSOLVE_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALLSOLVE_HOST", "https://allsolve.quanscient.com/")
    assert client.get("/api/validation/slab").json()["validated"] is True
    assert client.get("/api/health").json()["modes"]["allsolve"] is False
    assert client.post("/api/jobs", json={"mode": "allsolve"}).status_code == 501
