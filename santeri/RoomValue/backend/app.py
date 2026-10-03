"""Local API for real Allsolve 3D room optimization and the original 2D experiment."""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
import traceback
from contextlib import asynccontextmanager
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .job_store import JobStore


LOG = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roomvalue-allsolve")
_lock = Lock()
_store = JobStore(ROOT / ".runtime" / "jobs")
_active_job: str | None = None


def _log_failure(context: str, exc: Exception) -> None:
    # SDK exception text can contain request headers or credential-bearing URLs.
    # Keep failure locations and exception types without persisting that text.
    LOG.error("%s (%s)\n%s", context, type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))


class Point(BaseModel):
    x_m: float = Field(ge=0)
    y_m: float = Field(ge=0)


class Room(BaseModel):
    width_m: float = Field(gt=0, le=20)
    length_m: float = Field(gt=0, le=20)


class Listener(Point):
    id: str = Field(min_length=1, max_length=40)


class Treatment(Point):
    id: str = Field(min_length=1, max_length=40)
    cost_eur: float = Field(ge=0, le=100_000)
    selected: bool = True


class CompareRequest(BaseModel):
    room: Room
    frequency_hz: float = Field(gt=0, le=2000)
    source: Point
    listeners: list[Listener] = Field(min_length=2, max_length=6)
    treatments: list[Treatment] = Field(min_length=1, max_length=4)
    budget_eur: float = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def validate_layout(self) -> "CompareRequest":
        items = [self.source, *self.listeners, *self.treatments]
        if any(p.x_m > self.room.width_m or p.y_m > self.room.length_m for p in items):
            raise ValueError("Source, listener, and treatment points must lie inside the room")
        if len({x.id for x in self.listeners}) != len(self.listeners):
            raise ValueError("Listener IDs must be unique")
        if len({x.id for x in self.treatments}) != len(self.treatments):
            raise ValueError("Treatment IDs must be unique")
        if not any(x.selected for x in self.treatments):
            raise ValueError("Select at least one treatment candidate")
        return self


class StrictModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class Source3D(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    strength: float = Field(default=1.0, ge=0.01, le=10)


class QuietZone3D(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    center_m: tuple[float, float, float]
    size_m: tuple[float, float]
    target_reduction_db: float | None = Field(default=None, ge=0, le=30)
    target_pressure_pa: float | None = Field(default=None, ge=0.000001, le=100)

    @model_validator(mode="after")
    def validate_size(self) -> "QuietZone3D":
        if any(value <= 0 for value in self.size_m):
            raise ValueError("Quiet area width and length must be positive")
        return self


class OptimizeRequest3D(StrictModel):
    quietness_metric: Literal["relative_pressure_reduction_db", "absolute_rms_pressure_pa"] = "relative_pressure_reduction_db"
    sources: list[Source3D] = Field(min_length=1, max_length=3)
    quiet_zones: list[QuietZone3D] = Field(min_length=1, max_length=4)
    budget_eur: float = Field(default=500, ge=0, le=100_000)
    max_objects: int = Field(default=3, ge=0, le=6, strict=True)
    allowed_slot_ids: list[str] = Field(max_length=6)
    object_cost_eur: float = Field(default=120, ge=0, le=100_000)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_absolute_request(cls, value):
        if isinstance(value, dict) and "quietness_metric" not in value:
            zones = value.get("quiet_zones")
            if isinstance(zones, list) and zones and all(
                isinstance(zone, dict)
                and zone.get("target_pressure_pa") is not None
                and zone.get("target_reduction_db") is None
                for zone in zones
            ):
                return {**value, "quietness_metric": "absolute_rms_pressure_pa"}
        return value

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "OptimizeRequest3D":
        target_field = "target_reduction_db" if self.quietness_metric == "relative_pressure_reduction_db" else "target_pressure_pa"
        if any(getattr(zone, target_field) is None for zone in self.quiet_zones):
            raise ValueError(f"Every quiet area requires {target_field} for the selected quietness metric")
        for name, values in (
            ("source", [source.id for source in self.sources]),
            ("quiet area", [zone.id for zone in self.quiet_zones]),
            ("placement", self.allowed_slot_ids),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{name.capitalize()} IDs must be unique")
        return self


class PointSource3D(StrictModel):
    id: str = Field(min_length=1, max_length=40)
    position_m: tuple[float, float, float]
    level_db: float = Field(ge=0, le=120)


class PointPlan3D(StrictModel):
    sources: list[PointSource3D] = Field(min_length=1, max_length=3)
    listener_m: tuple[float, float, float]
    max_panels: int = Field(default=3, ge=0, le=6, strict=True)
    allowed_slot_ids: list[str] = Field(max_length=6)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "PointPlan3D":
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("Source IDs must be unique")
        if len(set(self.allowed_slot_ids)) != len(self.allowed_slot_ids):
            raise ValueError("Placement IDs must be unique")
        return self


def _get_catalog() -> dict:
    from experiments.optimizer3d import get_catalog

    return get_catalog()


def _run_optimization(request: dict, progress) -> dict:
    from experiments.optimizer3d import run_optimization

    return run_optimization(request, progress)


def _run_point_optimization(request: dict, progress) -> dict:
    from experiments.optimizer3d import run_point_optimization

    return run_point_optimization(request, progress)


def _optimizer_available() -> bool:
    return (ROOT / "experiments" / "optimizer3d.py").is_file()


def _ready3d() -> bool:
    return _credentials_configured() and _sdk_available() and _optimizer_available()


def _validate_room3d(request: OptimizeRequest3D, catalog: dict) -> None:
    """Keep arbitrary client geometry out of the measured room model."""
    room = catalog["room"]
    dimensions = room.get("size_m", room.get("dimensions_m"))
    width, length, height = dimensions
    sources = {source["id"]: source for source in catalog["sources"]}
    slots = {slot["id"]: slot for slot in catalog["slots"]}
    if any(source.id not in sources for source in request.sources):
        raise HTTPException(status_code=422, detail="Select sound sources from the measured room catalog")
    if any(slot_id not in slots for slot_id in request.allowed_slot_ids):
        raise HTTPException(status_code=422, detail="Select treatment placements from the room catalog")
    for zone in request.quiet_zones:
        x, y, z = zone.center_m
        dx, dy = zone.size_m
        if not (
            0 < x - dx / 2 and x + dx / 2 < width
            and 0 < y - dy / 2 and y + dy / 2 < length
            and 0 < z < height
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Quiet area {zone.id} must lie wholly inside the measured room, including its height",
            )
        samples = [
            (x + (ix / 8 - 0.5) * dx, y + (iy / 8 - 0.5) * dy, z)
            for ix in range(9) for iy in range(9)
        ]
        for source in request.sources:
            position = sources[source.id]["position_m"]
            if any(math.dist(point, position) <= 0.08 for point in samples):
                raise HTTPException(
                    status_code=422,
                    detail=f"Quiet area {zone.id} has a sample inside source {source.id}; move or resize the area",
                )
        for slot_id in request.allowed_slot_ids:
            slot = slots[slot_id]
            origin = slot.get("position_m", slot.get("origin_m"))
            if any(all(lo <= coordinate <= lo + size for coordinate, lo, size in zip(
                point, origin, slot["size_m"]
            )) for point in samples):
                raise HTTPException(
                    status_code=422,
                    detail=f"Quiet area {zone.id} has a sample inside treatment {slot_id}; move or resize the area",
                )


def _validate_result3d(result: dict) -> None:
    if (
        result.get("dimension") != 3
        or result.get("frequency_hz") != 125
        or not isinstance(result.get("project_id"), str)
        or not result["project_id"]
        or not isinstance(result.get("project_url"), str)
        or not result["project_url"].startswith("https://allsolve.quanscient.com/")
    ):
        raise ValueError("3D result is missing solver project provenance")
    evaluations = result.get("evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        raise ValueError("3D result contains no evaluated layouts")
    for evaluation in evaluations:
        if not isinstance(evaluation, dict) or evaluation.get("status") != "SUCCESS":
            raise ValueError("3D result contains a layout without successful solver provenance")
        ids = evaluation.get("simulation_ids")
        values = list(ids.values()) if isinstance(ids, dict) else ids
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Completed 3D layout is missing cloud simulation IDs")


def _validate_point_plan(request: PointPlan3D, catalog: dict) -> None:
    dimensions = catalog["room"].get("size_m", catalog["room"].get("dimensions_m"))
    known_sources = {source["id"] for source in catalog["sources"]}
    slots = {slot["id"]: slot for slot in catalog["slots"]}
    if any(source.id not in known_sources for source in request.sources):
        raise HTTPException(status_code=422, detail="Select sound source IDs from the room catalog")
    if any(slot_id not in slots for slot_id in request.allowed_slot_ids):
        raise HTTPException(status_code=422, detail="Select panel placements from the room catalog")
    if not all(0 < coordinate < size for coordinate, size in zip(request.listener_m, dimensions)):
        raise HTTPException(status_code=422, detail="The listener must lie strictly inside the measured room")
    for index, source in enumerate(request.sources):
        if not all(0.08 < coordinate < size - 0.08 for coordinate, size in zip(source.position_m, dimensions)):
            raise HTTPException(status_code=422, detail=f"Source {source.id}'s 0.08 m sphere must lie wholly inside the measured room")
        if math.dist(request.listener_m, source.position_m) <= 0.08:
            raise HTTPException(status_code=422, detail=f"The listener must lie outside source {source.id}'s sphere")
        if any(math.dist(source.position_m, other.position_m) <= 0.16 for other in request.sources[:index]):
            raise HTTPException(status_code=422, detail="Active sound source spheres must not overlap or touch")
    for slot_id in request.allowed_slot_ids:
        slot = slots[slot_id]
        origin = slot.get("position_m", slot.get("origin_m"))
        size = slot["size_m"]
        if all(lo <= coordinate <= lo + extent for coordinate, lo, extent in zip(request.listener_m, origin, size)):
            raise HTTPException(status_code=422, detail=f"The listener is inside allowed panel {slot_id}; move the listener or exclude that placement")
        for source in request.sources:
            closest = [max(lo, min(coordinate, lo + extent)) for coordinate, lo, extent in zip(source.position_m, origin, size)]
            if math.dist(source.position_m, closest) <= 0.08:
                raise HTTPException(status_code=422, detail=f"Source {source.id}'s sphere intersects allowed panel {slot_id}; move the source or exclude that placement")


def _validate_point_result(result: dict) -> None:
    _validate_result3d(result)
    if result.get("objective") != "minimize_listener_noise" or result.get("noise_metric") != "normalized_spl_db":
        raise ValueError("Point optimization returned a different objective or pressure metric")
    baseline = result.get("baseline")
    optimum = result.get("optimal_layout")
    if not isinstance(baseline, dict) or not isinstance(optimum, dict):
        raise ValueError("Point result is missing baseline or optimal layout")
    for layout in [baseline, optimum, *result["evaluations"]]:
        ids = layout.get("simulation_ids")
        values = list(ids.values()) if isinstance(ids, dict) else ids
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Point result is missing cloud simulation IDs")
        for field in ("pressure_rms_pa", "noise_db"):
            value = layout.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Point result has missing or nonfinite pressure or dB values")
        if layout["pressure_rms_pa"] < 0:
            raise ValueError("Point result contains negative RMS pressure")
    if optimum.get("status") != "SUCCESS":
        raise ValueError("Optimal point layout is missing successful solver provenance")


def _credentials_configured() -> bool:
    private_file = dotenv_values(WORKSPACE / ".env")
    return bool(
        (os.environ.get("ALLSOLVE_ACCESS_KEY") or private_file.get("ALLSOLVE_ACCESS_KEY"))
        and (os.environ.get("ALLSOLVE_SECRET_KEY") or private_file.get("ALLSOLVE_SECRET_KEY"))
    )


def _sdk_available() -> bool:
    return importlib.util.find_spec("allsolve") is not None


def _comparison_available() -> bool:
    experiment_dir = ROOT / "experiments"
    return (experiment_dir / "comparison.py").is_file() and (
        experiment_dir / "VERIFIED_COMPARISON.json"
    ).is_file()


def _ready() -> bool:
    return _credentials_configured() and _sdk_available() and _comparison_available()


def _validate_verified_preset(request: CompareRequest) -> None:
    marker = json.loads(
        (ROOT / "experiments" / "VERIFIED_COMPARISON.json").read_text(encoding="utf-8")
    )

    def same_point(a: Point, b: dict) -> bool:
        return math.isclose(a.x_m, float(b["x_m"]), abs_tol=1e-6) and math.isclose(
            a.y_m, float(b["y_m"]), abs_tol=1e-6
        )

    room = marker["room"]
    if not (
        math.isclose(request.frequency_hz, float(marker["frequency_hz"]), abs_tol=1e-6)
        and math.isclose(request.room.width_m, float(room["width_m"]), abs_tol=1e-6)
        and math.isclose(request.room.length_m, float(room["length_m"]), abs_tol=1e-6)
        and same_point(request.source, marker["source"])
    ):
        raise HTTPException(status_code=422, detail="Only the verified cafeteria preset is supported")
    expected_listeners = {p["id"]: p for p in marker["listeners"]}
    if {p.id for p in request.listeners} != set(expected_listeners) or any(
        not same_point(p, expected_listeners[p.id]) for p in request.listeners
    ):
        raise HTTPException(status_code=422, detail="Only the verified listener positions are supported")
    verified_treatments = {p["id"]: p for p in marker["treatments"]}
    if any(
        p.id not in verified_treatments or not same_point(p, verified_treatments[p.id])
        for p in request.treatments
        if p.selected
    ):
        raise HTTPException(status_code=422, detail="One or more treatment placements are not verified")


def _amplitude(value: object, name: str) -> float:
    try:
        amplitude = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing solver amplitude for {name}") from exc
    if not math.isfinite(amplitude) or amplitude <= 0:
        raise ValueError(f"Nonpositive or nonfinite solver amplitude for {name}")
    return amplitude


def _calculate_result(raw: dict, request: CompareRequest) -> dict:
    """Calculate only relative changes from solver-returned pressure amplitudes."""
    frequency = float(raw["frequency_hz"])
    if not math.isclose(frequency, request.frequency_hz, rel_tol=1e-9):
        raise ValueError("Solver frequency does not match request")
    baseline_id = str(raw["baseline_simulation_id"])
    if not baseline_id:
        raise ValueError("Baseline simulation ID is missing")
    listener_ids = [listener.id for listener in request.listeners]
    baseline = {
        listener_id: {"amplitude_pa": _amplitude(raw["baseline"][listener_id], listener_id)}
        for listener_id in listener_ids
    }
    requested = {t.id: t for t in request.treatments if t.selected}
    candidates = []
    seen: set[str] = set()
    for item in raw["candidates"]:
        candidate_id = str(item["id"])
        if candidate_id not in requested or candidate_id in seen:
            raise ValueError("Solver returned an unexpected treatment candidate")
        seen.add(candidate_id)
        simulation_id = str(item["simulation_id"])
        if not simulation_id:
            raise ValueError("Candidate simulation ID is missing")
        changes = {
            listener_id: 20.0
            * math.log10(
                _amplitude(item["amplitudes"][listener_id], f"{candidate_id}/{listener_id}")
                / baseline[listener_id]["amplitude_pa"]
            )
            for listener_id in listener_ids
        }
        candidates.append(
            {
                "id": candidate_id,
                "cost_eur": requested[candidate_id].cost_eur,
                "pressure_db_change_by_listener": changes,
                "worst_listener_db_change": max(changes.values()),
                "simulation_id": simulation_id,
            }
        )
    if seen != set(requested):
        raise ValueError("Solver did not return every selected treatment candidate")
    affordable_improvements = [
        c
        for c in candidates
        if c["cost_eur"] <= request.budget_eur and c["worst_listener_db_change"] < 0
    ]
    best = None
    if affordable_improvements:
        strongest = min(c["worst_listener_db_change"] for c in affordable_improvements)
        # Differences below 0.1 dB are too small to justify a higher cost in
        # this exploratory mesh, so choose the cheaper near-equivalent option.
        near_equivalent = [
            c for c in affordable_improvements
            if c["worst_listener_db_change"] <= strongest + 0.1
        ]
        best = min(near_equivalent, key=lambda c: (c["cost_eur"], c["worst_listener_db_change"]))
    return {
        "frequency_hz": frequency,
        "model_label": "2D single-frequency Allsolve",
        "baseline": baseline,
        "baseline_simulation_id": baseline_id,
        "candidates": candidates,
        "recommended_id": best["id"] if best else None,
        "decision_rule": "Best worst-listener reduction within budget; within 0.1 dB, choose lower cost.",
        "assumptions": [
            "One controlled source area and rigid room boundaries are used.",
            "The damped region is an illustrative treatment proxy, not a calibrated product.",
            "Pressure changes apply only at this frequency and modeled listener positions.",
            "Entered prices are user assumptions, not market quotes.",
        ],
    }


def _run_job(job_id: str, request: CompareRequest) -> None:
    global _active_job
    try:
        _store.update(job_id, status="running", progress={"stage": "solving_2d"})
        from experiments.comparison import run_comparison

        raw = run_comparison(request.model_dump())
        result = _calculate_result(raw, request)
        _store.update(job_id, status="completed", result=result, progress={"stage": "completed"})
    except Exception as exc:
        _log_failure(f"Allsolve comparison failed for job {job_id}", exc)
        _store.update(job_id, status="failed", error=f"{type(exc).__name__}: simulation failed; see server log")
    finally:
        with _lock:
            _active_job = None


def _run_job3d(job_id: str, request: OptimizeRequest3D) -> None:
    _run_3d_worker(job_id, request, _run_optimization, _validate_result3d)


def _run_point_job(job_id: str, request: PointPlan3D) -> None:
    _run_3d_worker(job_id, request, _run_point_optimization, _validate_point_result)


def _run_3d_worker(job_id: str, request: BaseModel, runner, validator) -> None:
    global _active_job
    try:
        _store.update(job_id, status="running", error=None, progress={"stage": "starting"})

        def report(progress: dict | str) -> None:
            if isinstance(progress, str):
                progress = {"stage": progress}
            # Engine progress contains controlled stage names and cloud job IDs,
            # never SDK exception messages or credentials.
            previous = _store.get(job_id).get("progress", {})
            _store.update(job_id, progress={**previous, **deepcopy(progress)})

        result = runner(request.model_dump(mode="json"), report)
        if not isinstance(result, dict):
            raise ValueError("3D optimizer returned no solver result")
        validator(result)
        # JSON serialization also rejects nonfinite pressure/decision metrics.
        json.dumps(result, allow_nan=False)
        final_progress = {**_store.get(job_id).get("progress", {}), "stage": "completed"}
        _store.update(job_id, status="completed", result=result, progress=final_progress)
    except Exception as exc:
        _log_failure(f"Allsolve 3D optimization failed for job {job_id}", exc)
        _store.update(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: 3D simulation failed. Resume to reuse completed cloud runs; see server log.",
        )
    finally:
        with _lock:
            if _active_job == job_id:
                _active_job = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _active_job
    _store.load(interrupt_unfinished=True)
    _active_job = None
    yield


app = FastAPI(title="RoomValue", version="0.2.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, object]:
    sdk = _sdk_available()
    credentials = _credentials_configured()
    return {
        "status": "ok",
        "sdk_available": sdk,
        "credentials_configured": credentials,
        "allsolve_ready": sdk and credentials and _comparison_available(),
        "room3d_ready": sdk and credentials and _optimizer_available(),
    }


@app.post("/api/compare", status_code=202)
def compare(request: CompareRequest) -> dict[str, str]:
    global _active_job
    if not _ready():
        raise HTTPException(status_code=503, detail="Verified Allsolve comparison is not ready")
    _validate_verified_preset(request)
    with _lock:
        if _active_job is not None:
            raise HTTPException(status_code=409, detail="An Allsolve comparison is already running")
        job_id = str(uuid4())
        _store.create(job_id, "comparison2d", request.model_dump(mode="json"))
        _active_job = job_id
    _executor.submit(_run_job, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/room3d/catalog")
def room3d_catalog() -> dict:
    if not _optimizer_available():
        raise HTTPException(status_code=503, detail="The 3D optimization module is not installed")
    try:
        catalog = _get_catalog()
    except (ImportError, OSError, ValueError, KeyError) as exc:
        _log_failure("Could not load the 3D room catalog", exc)
        raise HTTPException(status_code=503, detail="The 3D room dataset or its server dependencies are unavailable")
    return {**catalog, "allsolve_ready": _ready3d()}


@app.post("/api/room3d/optimize", status_code=202)
def optimize_room3d(request: OptimizeRequest3D) -> dict[str, str]:
    global _active_job
    if not _ready3d():
        raise HTTPException(status_code=503, detail="3D Allsolve is not ready; check server dependencies and credentials")
    _validate_room3d(request, room3d_catalog())
    with _lock:
        if _active_job is not None:
            raise HTTPException(status_code=409, detail="An Allsolve simulation is already running", headers={"Retry-After": "10"})
        job_id = str(uuid4())
        _store.create(job_id, "room3d", request.model_dump(mode="json"))
        _active_job = job_id
    _executor.submit(_run_job3d, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/jobs/{job_id}/resume", status_code=202)
def resume_job(job_id: str) -> dict[str, str]:
    global _active_job
    if not _ready3d():
        raise HTTPException(status_code=503, detail="3D Allsolve is not ready; check server dependencies and credentials")
    with _lock:
        job = _store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("kind") not in {"room3d", "room3d_point"} or job["status"] not in {"failed", "interrupted"}:
            raise HTTPException(status_code=409, detail="Only a failed or interrupted 3D job can be resumed")
        if _active_job is not None:
            raise HTTPException(status_code=409, detail="An Allsolve simulation is already running", headers={"Retry-After": "10"})
        if job["kind"] == "room3d_point":
            request = PointPlan3D.model_validate(job["request"])
            _validate_point_plan(request, room3d_catalog())
            worker = _run_point_job
        else:
            request = OptimizeRequest3D.model_validate(job["request"])
            _validate_room3d(request, room3d_catalog())
            worker = _run_job3d
        _store.update(job_id, status="queued", error=None, attempt=job.get("attempt", 1) + 1, progress={"stage": "resuming"})
        _active_job = job_id
    _executor.submit(worker, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/room3d/latest")
def latest_room3d() -> dict:
    job = _store.latest_completed("room3d")
    if job is None:
        raise HTTPException(status_code=404, detail="No 3D optimization has completed yet")
    return job


@app.post("/api/room3d/minimize", status_code=202)
def minimize_listener(request: PointPlan3D) -> dict[str, str]:
    global _active_job
    if not _ready3d():
        raise HTTPException(status_code=503, detail="3D Allsolve is not ready; check server dependencies and credentials")
    _validate_point_plan(request, room3d_catalog())
    with _lock:
        if _active_job is not None:
            raise HTTPException(status_code=409, detail="An Allsolve simulation is already running", headers={"Retry-After": "10"})
        job_id = str(uuid4())
        _store.create(job_id, "room3d_point", request.model_dump(mode="json"))
        _active_job = job_id
    _executor.submit(_run_point_job, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/room3d/minimize/latest")
def latest_point_minimization() -> dict:
    job = _store.latest_completed("room3d_point")
    if job is None:
        raise HTTPException(status_code=404, detail="No listener noise minimization has completed yet")
    return job


@app.get("/api/room3d/preview/{view}")
def room3d_preview(view: str) -> FileResponse:
    filename = {"room": "room3d.png", "field": "pressure_slice_mic1.png"}.get(view)
    if filename is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    path = ROOT / "experiments" / "room3d" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Preview has not been generated")
    return FileResponse(path, media_type="image/png")
