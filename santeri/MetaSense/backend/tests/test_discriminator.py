"""Real optimization orchestration is durable, bounded, and never substitutes data."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import discriminator, main
from app.discriminator_models import DiscriminatorRequest


client = TestClient(main.app)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    runner = tmp_path / "runner.py"
    runner.write_text("# Cloud runner placeholder for orchestration tests only\n", encoding="utf-8")
    manager = discriminator.DiscriminatorManager(tmp_path / "jobs", runner)
    monkeypatch.setattr(main, "discriminator_manager", manager)
    monkeypatch.setenv("ALLSOLVE_ACCESS_KEY", "private-test-access")
    monkeypatch.setenv("ALLSOLVE_SECRET_KEY", "private-test-secret")
    monkeypatch.setenv("ALLSOLVE_HOST", "https://allsolve.quanscient.com/")
    monkeypatch.setattr(discriminator, "allsolve_sdk_installed", lambda: True)
    monkeypatch.setattr(discriminator, "_process_identity", lambda pid: "process-start" if pid else None)
    monkeypatch.setattr(discriminator.DiscriminatorManager, "_watch", lambda *args: None)
    launched = []

    def launch(arguments, **kwargs):
        launched.append((arguments, kwargs))
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(discriminator.subprocess, "Popen", launch)
    manager.test_launches = launched
    return manager


def test_default_search_is_explicit_and_feasible() -> None:
    request = DiscriminatorRequest()
    assert request.liquids[0].n == 1.33
    assert request.liquids[1].n == 1.38
    assert request.geometry_bounds.period_nm.max == 550
    assert request.candidate_count == 24
    assert request.max_parallel_cores == 64
    assert request.objective == "max_abs_reflectance_contrast"


def test_exact_minimum_gap_is_not_rejected_by_float_roundoff() -> None:
    request = DiscriminatorRequest.model_validate({
        "geometry_bounds": {"period_nm": {"min": 500, "max": 550}, "fill_factor": {"min": 0.3, "max": 0.9}},
    })
    assert request.minimum_feature_nm == 50


@pytest.mark.parametrize("changes", [
    {"liquids": [{"label": "A", "n": 1.33}, {"label": "B", "n": 1.33}]},
    {"liquids": [{"label": "A", "n": 1.33}, {"label": "a", "n": 1.38}]},
    {"liquids": [{"label": "A", "n": 1.33}, {"label": "B", "n": 1.9}]},
    {"liquids": [{"label": "A", "n": True}, {"label": "B", "n": 1.38}]},
    {"candidate_count": 129},
    {"max_parallel_cores": 257},
    {"wavelength_samples": 42},
    {"wavelength_min_nm": 1100},
    {"wavelength_min_nm": float("nan")},
    {"geometry_bounds": {"period_nm": {"min": 450, "max": 600}}},
    {"geometry_bounds": {"fill_factor": {"min": 0.05, "max": 0.7}}},
    {"geometry_bounds": {"fill_factor": {"min": 0.3, "max": 0.95}}},
    {"geometry_bounds": {"ridge_height_nm": {"min": 20, "max": 220}}},
    {"geometry_bounds": {"period_nm": {"min": 550, "max": 450}}},
    {"secret_key": "must-not-be-accepted"},
])
def test_unsafe_or_impossible_search_inputs_are_rejected(changes) -> None:
    with pytest.raises(ValidationError):
        DiscriminatorRequest.model_validate(changes)


def test_configuration_and_latest_are_read_only(manager) -> None:
    response = client.get("/api/optimization/config")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["synthetic"] is False
    assert response.json()["limits"]["max_parallel_cores"]["max"] == 256
    assert client.get("/api/optimization/jobs/latest").json() is None
    assert client.get("/api/optimization/jobs/no-such-job").status_code == 404
    assert manager.test_launches == []
    assert not manager.job_root.exists()
    assert "private-test-secret" not in response.text


def test_missing_credentials_never_launches_or_creates_job(manager, monkeypatch) -> None:
    monkeypatch.delenv("ALLSOLVE_SECRET_KEY")
    response = client.post("/api/optimization/jobs", json={})
    assert response.status_code == 503
    assert manager.test_launches == []
    assert not manager.job_root.exists()


def test_validation_precedes_process_launch(manager) -> None:
    response = client.post("/api/optimization/jobs", json={"candidate_count": 129})
    assert response.status_code == 422
    assert manager.test_launches == []


def test_job_persists_and_passes_credentials_only_in_worker_environment(manager) -> None:
    response = client.post("/api/optimization/jobs", json={})
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["synthetic"] is False
    assert job["report"] is None
    assert job["reused"] is False
    folder = manager.job_root / job["id"]
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    assert request == job["request"]
    assert request["max_parallel_cores"] == 64
    assert "private-test-secret" not in (folder / "job.json").read_text(encoding="utf-8")
    arguments, options = manager.test_launches[0]
    assert arguments[2:4] == ["run", "--job-dir"]
    assert arguments[4] == str(folder.resolve())
    assert "private-test-secret" not in str(arguments)
    assert options["env"]["ALLSOLVE_SECRET_KEY"] == "private-test-secret"
    assert options["shell"] is False
    assert "private-test-secret" not in response.text
    assert client.get("/api/optimization/jobs/latest").json()["id"] == job["id"]


def test_identical_active_request_is_reused_after_api_restart(manager, monkeypatch) -> None:
    first = client.post("/api/optimization/jobs", json={}).json()
    restarted = discriminator.DiscriminatorManager(manager.job_root, manager.runner_path)
    monkeypatch.setattr(main, "discriminator_manager", restarted)
    reused = client.post("/api/optimization/jobs", json={})
    assert reused.status_code == 202
    assert reused.json()["id"] == first["id"]
    assert reused.json()["reused"] is True
    assert len(manager.test_launches) == 1
    different = client.post("/api/optimization/jobs", json={"candidate_count": 25})
    assert different.status_code == 409
    assert first["id"] in different.json()["detail"]
    assert len(manager.test_launches) == 1


def test_cross_manager_concurrent_submissions_launch_one_worker(manager) -> None:
    second_manager = discriminator.DiscriminatorManager(manager.job_root, manager.runner_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda service: service.create(DiscriminatorRequest()), [manager, second_manager]))
    assert jobs[0]["id"] == jobs[1]["id"]
    assert sum(job["reused"] for job in jobs) == 1
    assert len(manager.test_launches) == 1


def test_worker_failure_is_durable_and_does_not_expose_logs(manager, monkeypatch) -> None:
    job = client.post("/api/optimization/jobs", json={}).json()
    (manager.job_root / job["id"] / "worker.log").write_text("private-test-secret exception", encoding="utf-8")
    monkeypatch.setattr(discriminator, "_process_identity", lambda pid: None)
    failed = client.get(f"/api/optimization/jobs/{job['id']}")
    assert failed.json()["status"] == "failed"
    assert failed.json()["report"] is None
    assert "worker stopped" in failed.json()["error"]
    assert "private-test-secret" not in failed.text
    restarted = discriminator.DiscriminatorManager(manager.job_root, manager.runner_path)
    assert restarted.latest()["status"] == "failed"


def test_terminal_report_survives_restart_and_has_public_secret_redaction(manager, monkeypatch) -> None:
    job = client.post("/api/optimization/jobs", json={}).json()
    report = {
        "label": "allsolve_liquid_discriminator", "synthetic": False, "status": "completed",
        "best_design": {"period_nm": 500, "objective": 0.3},
        "provenance": {"simulation_id": "cloud-sim", "secret_key": "private-test-secret"},
        "errors": ["Private diagnostic private-test-secret"],
    }
    discriminator._atomic_json(manager.job_root / job["id"] / "report.json", report)
    monkeypatch.setattr(discriminator, "_process_identity", lambda pid: None)
    restarted = discriminator.DiscriminatorManager(manager.job_root, manager.runner_path)
    completed = restarted.get(job["id"])
    assert completed["status"] == "completed"
    assert completed["report"]["best_design"] == report["best_design"]
    assert completed["report"]["provenance"] == {"simulation_id": "cloud-sim"}
    assert "private-test-secret" not in json.dumps(completed)
    assert completed["report"]["errors"] == ["Private diagnostic [redacted]"]


def test_disappeared_completed_report_is_not_presented_as_a_valid_result(manager) -> None:
    job = client.post("/api/optimization/jobs", json={}).json()
    path = manager.job_root / job["id"] / "report.json"
    discriminator._atomic_json(path, {
        "label": "allsolve_liquid_discriminator", "synthetic": False, "status": "completed",
    })
    assert manager.get(job["id"])["status"] == "completed"
    path.unlink()
    result = manager.get(job["id"])
    assert result["status"] == "failed"
    assert result["report"] is None
    assert "missing or invalid" in result["error"]


@pytest.mark.parametrize("content", ["{partial", '{"label":"synthetic_demo","synthetic":true,"status":"completed"}'])
def test_bad_report_never_becomes_a_real_result(manager, monkeypatch, content) -> None:
    job = client.post("/api/optimization/jobs", json={}).json()
    (manager.job_root / job["id"] / "report.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(discriminator, "_process_identity", lambda pid: None)
    result = client.get(f"/api/optimization/jobs/{job['id']}").json()
    assert result["status"] == "failed"
    assert result["report"] is None


def test_verifying_phase_remains_active_and_legacy_sensor_mode_stays_disabled(manager) -> None:
    job = client.post("/api/optimization/jobs", json={}).json()
    discriminator._atomic_json(manager.job_root / job["id"] / "report.json", {
        "label": "allsolve_liquid_discriminator", "synthetic": False,
        "status": "verifying", "progress": {"completed_candidates": 24},
    })
    result = client.get(f"/api/optimization/jobs/{job['id']}").json()
    assert result["status"] == "verifying"
    assert result["report"]["progress"]["completed_candidates"] == 24
    assert client.post("/api/optimization/jobs", json={"seed": 43}).status_code == 409
    assert client.get("/api/health").json()["modes"]["allsolve"] is False
