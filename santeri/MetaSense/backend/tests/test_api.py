"""API checks for the scaffold's honesty and deterministic demo behavior."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_reports_allsolve_as_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("ALLSOLVE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("ALLSOLVE_SECRET_KEY", raising=False)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["modes"] == {"surrogate_demo": True, "allsolve": False}
    assert response.json()["allsolve_configured"] is False


def test_surrogate_is_synthetic_repeatable_and_retrievable() -> None:
    payload = {
        "mode": "surrogate_demo",
        "sample": {
            "receptor": "streptavidin",
            "analyte": "biotin",
            "surface_coverage": 0.4,
        },
        "seed": 123,
    }
    first_response = client.post("/api/jobs", json=payload)
    second_response = client.post("/api/jobs", json=payload)
    assert first_response.status_code == second_response.status_code == 201
    first = first_response.json()
    second = second_response.json()
    assert first["id"] != second["id"]
    assert first["mode"] == "surrogate_demo"
    assert first["status"] == "completed"
    assert first["result"] == second["result"]
    assert first["result"]["label"] == "synthetic_surrogate_demo"
    assert "not an Allsolve result" in first["result"]["disclaimer"]
    assert first["result"]["assumed_surface_coverage"] == 0.4
    assert len(first["result"]["wavelength_nm"]) == 451
    assert len(first["result"]["noisy_bound_response"]) == 451
    assert client.get(f"/api/jobs/{first['id']}").json() == first


def test_input_validation_and_unknown_job() -> None:
    invalid = client.post(
        "/api/jobs", json={"design": {"period_nm": 500, "pillar_diameter_nm": 500}}
    )
    assert invalid.status_code == 422
    assert client.get("/api/jobs/no-such-job").status_code == 404


def test_toy_inverse_fit_recovers_coverage_without_noise() -> None:
    response = client.post(
        "/api/jobs",
        json={
            "sample": {"surface_coverage": 0.37},
            "detector": {"noise_std_fraction": 0.0},
        },
    )
    assert response.status_code == 201
    result = response.json()["result"]
    assert abs(result["estimated_surface_coverage"] - 0.37) < 0.001


def test_allsolve_never_returns_synthetic_job_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("ALLSOLVE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("ALLSOLVE_SECRET_KEY", raising=False)
    response = client.post("/api/jobs", json={"mode": "allsolve"})
    assert response.status_code == 503
    assert "ALLSOLVE_ACCESS_KEY" in response.json()["detail"]
    assert "result" not in response.json()


def test_allsolve_stays_explicitly_unimplemented_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ALLSOLVE_ACCESS_KEY", "test-id")
    monkeypatch.setenv("ALLSOLVE_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALLSOLVE_HOST", "https://allsolve.quanscient.com/")
    response = client.post("/api/jobs", json={"mode": "allsolve"})
    assert response.status_code == 501
    assert "pending verified" in response.json()["detail"]
    assert "test-secret" not in response.text
    assert "result" not in response.json()
