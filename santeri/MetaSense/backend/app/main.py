"""MetaSense FastAPI entry point."""

from fastapi import FastAPI, HTTPException

from .allsolve_adapter import AllsolvePhysicsNotImplemented, start_allsolve_job
from .config import (
    AllsolveConfigurationError,
    allsolve_config_from_environment,
    allsolve_sdk_installed,
)
from .jobs import job_manager
from .models import JobRecord, JobRequest
from .slab_validation import read_slab_validation_report
from .discriminator import (
    OptimizationAlreadyActive,
    OptimizationUnavailable,
    discriminator_manager,
)
from .discriminator_models import DiscriminatorRequest


app = FastAPI(title="MetaSense", version="0.1.0")


@app.get("/api/optimization/config")
def optimization_configuration() -> dict[str, object]:
    return discriminator_manager.configuration()


@app.post("/api/optimization/jobs", status_code=202)
def create_optimization_job(request: DiscriminatorRequest) -> dict[str, object]:
    try:
        return discriminator_manager.create(request)
    except OptimizationAlreadyActive as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except OptimizationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/optimization/jobs/latest")
def latest_optimization_job() -> dict[str, object] | None:
    return discriminator_manager.latest()


@app.get("/api/optimization/jobs/{job_id}")
def get_optimization_job(job_id: str) -> dict[str, object]:
    job = discriminator_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Optimization job not found")
    return job


@app.get("/api/validation/slab")
def slab_validation() -> dict[str, object]:
    return read_slab_validation_report()


@app.get("/api/health")
def health() -> dict[str, object]:
    config = allsolve_config_from_environment()
    try:
        config.validate()
        configured = True
    except AllsolveConfigurationError:
        configured = False
    return {
        "status": "ok",
        "modes": {"surrogate_demo": True, "allsolve": False},
        "allsolve_configured": configured,
        "allsolve_sdk_installed": allsolve_sdk_installed(),
    }


@app.post("/api/jobs", response_model=JobRecord, status_code=201)
def create_job(request: JobRequest) -> JobRecord:
    if request.mode == "allsolve":
        try:
            start_allsolve_job(allsolve_config_from_environment())
        except AllsolveConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AllsolvePhysicsNotImplemented as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        raise AssertionError("Allsolve adapter unexpectedly returned without a job")
    return job_manager.create_surrogate_job(request)


@app.get("/api/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str) -> JobRecord:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
