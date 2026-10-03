"""Real 3D Allsolve placement search, with reusable complex FEM fields.

Every source/layout basis is a separate immutable harmonic solve. The current
planner minimizes listener RMS pressure across every layout within a panel cap.
The earlier count-first quiet-area search remains for saved API jobs.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import time
import tempfile
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import allsolve
import h5py
import meshio
import numpy as np
import requests
from dotenv import dotenv_values
from allsolve.api import get_api, get_auth
from allsolve.http_transfer import (CONNECT_TIMEOUT_S, TRANSFER_TIMEOUT_S,
                                   stream_response_to_file, validate_url_scheme)
from allsolve.simulation.simulation import _decompress_downloaded_hdf

CASE = Path(__file__).resolve().parents[1]
HERE = CASE / "experiments" / "room3d_optimizer"
DATA = CASE / "datasets" / "dechorate" / "catalog.json"
FREQUENCY = 125.0
SOURCE_RADIUS = .08
DAMPING = .5
PRESSURE_REFERENCE_PA = 20e-6
DEFAULT_SOURCE_LEVEL_DB = 20*math.log10(1/(math.sqrt(2)*PRESSURE_REFERENCE_PA))
EDGE_PAIRS = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
BASIS_CORES = 4


def download_field_manifest(simulation, project_id, folder):
    """Read SDK metadata and URLs on the coordinator, never inside a worker."""
    missing = [label for label in ("Real", "Imag") if not list(folder.glob(label+"_*.hdf"))]
    if not missing:
        return []
    output = simulation.get_output_data(refresh=True)
    job_id = output.get_simulation_job_id(0, None)
    filenames = []
    for label in missing:
        names = output.get_filenames_for_output_field(label, 0, None)
        if len(names) != 1:
            raise ValueError("Expected one cloud HDF export per pressure component")
        name = names[0]
        if Path(name).name != name or not name.startswith(label+"_") or not name.endswith(".hdf"):
            raise ValueError("Unsafe or unexpected cloud field filename")
        filenames.append(name)
    with get_api() as api:
        urls = api.get_simulation_output_data_download_urls(
            authorization=get_auth(), project_id=project_id, simulation_id=simulation.id,
            job_id=job_id, request_body=filenames)
    if len(urls) != len(filenames):
        raise ValueError("Incomplete cloud field download manifest")
    for url in urls:
        validate_url_scheme(url, False)
    return list(zip(filenames, urls))


def download_field_bundle(manifest, folder, staging_root, session_factory=requests.Session):
    """Stream independently, decompress off-cache, exclusively publish complete HDFs.

    This worker never calls the SDK API, mutates simulation objects, writes job
    JSON, or reads pressure arrays. Staging is outside the harvester's glob.
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="field-", dir=staging_root))
    published, skipped = 0, 0
    with session_factory() as session:
        for filename, url in manifest:
            destination = folder / filename
            if destination.exists():
                skipped += 1
                continue
            temporary = staging / filename
            with session.get(url, stream=True, timeout=(CONNECT_TIMEOUT_S, TRANSFER_TIMEOUT_S)) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    stream_response_to_file(response, output)
            # Reuse the pinned SDK's streamed zstd transport handling. It
            # validates decompressed HDF magic and atomically replaces staging.
            _decompress_downloaded_hdf(temporary)
            with temporary.open("rb") as output:
                if output.read(8) != b"\x89HDF\r\n\x1a\n":
                    raise ValueError("Downloaded pressure field is not HDF5")
            folder.mkdir(parents=True, exist_ok=True)
            try:
                # Unlike replace(), this can never overwrite a concurrent SDK
                # downloader's existing file. Source/destination share a drive.
                os.link(temporary, destination)
                published += 1
            except FileExistsError:
                skipped += 1
            temporary.unlink()
    staging.rmdir()
    return {"published_files": published, "skipped_files": skipped}


def prefetch_existing_fields(cache_dir, workers=4, progress=lambda event: None):
    """Accelerate an active harvester without starting or changing cloud jobs."""
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 4:
        raise ValueError("Download workers must be between one and four")
    cache_dir = Path(cache_dir).resolve()
    if not cache_dir.is_relative_to(HERE.resolve()):
        raise ValueError("Prefetch cache must be inside the RoomValue optimizer cache")
    state = read_json(cache_dir / "state.json")
    env = dotenv_values(CASE.parent / ".env")
    sdk_cache_dir = cache_dir / "prefetch-sdk-cache"
    sdk_cache_dir.mkdir(exist_ok=True)
    client = allsolve.Client(api_key=os.environ.get("ALLSOLVE_ACCESS_KEY") or env.get("ALLSOLVE_ACCESS_KEY"),
                             api_secret=os.environ.get("ALLSOLVE_SECRET_KEY") or env.get("ALLSOLVE_SECRET_KEY"),
                             host=os.environ.get("ALLSOLVE_HOST") or env.get("ALLSOLVE_HOST") or "https://allsolve.quanscient.com/",
                             cache_base_dir=str(sdk_cache_dir), dotenv_file=None)
    project = client.get_project(state["project_id"])
    simulations = {simulation.id: simulation for simulation in project.get_simulations()}
    summary = {"download_workers": workers, "planned_bases": 0, "completed_bases": 0,
               "published_files": 0, "skipped_files": 0, "failed_bases": 0,
               "cloud_jobs_started": 0}
    futures = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="roomvalue-field-prefetch") as executor:
        # Reverse order targets future cases before the current forward-order
        # harvester reaches them. No coordinator or worker modifies state.json.
        for name, run in reversed(list(state["runs"].items())):
            if Path(name).name != name:
                raise ValueError("Unsafe basis cache name")
            folder = cache_dir / "fields" / name
            if run.get("status") == "SUCCESS" and (folder / "complex.npz").is_file():
                continue
            simulation = simulations.get(run["simulation_id"])
            if simulation is None or simulation.get_status() != allsolve.Job.SUCCESS:
                continue
            try:
                manifest = download_field_manifest(simulation, project.id, folder)
            except Exception as exc:
                summary["failed_bases"] += 1
                progress({"stage": "prefetching_fields", "message": "Skipped a field manifest; the original harvester remains authoritative",
                          "basis": name, "error_type": type(exc).__name__, **summary})
                continue
            if not manifest:
                continue
            futures[executor.submit(download_field_bundle, manifest, folder, cache_dir / ".prefetch-staging")] = name
            summary["planned_bases"] += 1
            progress({"stage": "prefetching_fields", "message": "Planned independent field downloads", **summary})
        for future in as_completed(futures):
            try:
                downloaded = future.result()
                summary["completed_bases"] += 1
                summary["published_files"] += downloaded["published_files"]
                summary["skipped_files"] += downloaded["skipped_files"]
                progress({"stage": "prefetching_fields", "message": "Complete HDFs published; solver checks still run in the original harvester", **summary})
            except Exception as exc:
                summary["failed_bases"] += 1
                # Exception strings can contain signed URLs. Only their types
                # are safe to report; partial staging is kept for inspection.
                progress({"stage": "prefetching_fields", "message": "A download failed; existing files and original processing are preserved",
                          "basis": futures[future], "error_type": type(exc).__name__, **summary})
    return summary


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def quota_values(quota):
    values = {"max_concurrent_cores": quota.max_concurrent_cores,
              "account_running_cores": quota.total_running_cores,
              "account_reserved_cores": getattr(quota, "total_reserved_cores", 0)}
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values.values()):
        raise RuntimeError("Invalid Allsolve core quota response")
    return {key: int(value) for key, value in values.items()}


def quota_start_retry(exc):
    # Only explicit shared-resource contention is retryable. Authentication,
    # credits, malformed physics, and other failures must fail visibly.
    body = str(getattr(exc, "body", ""))
    return any(code in body for code in ("vcpu_limit_exceeded", "resource_unavailable"))


def run_parallel_tasks(tasks, progress, on_update=lambda *_: None, *, quota_provider=None,
                       refresh_many=None, sleep=time.sleep, clock=time.monotonic,
                       poll_seconds=2, timeout_seconds=1200):
    """Fill quota-bounded cloud batches and batch-poll; SDK mutation stays serial.

    Each pass snapshots free unreserved cores and reserves four locally before
    every start. Already submitted jobs also hold local shadow reservations,
    even if the quota API has not reported their cores yet. Counting a job in
    both reported running cores and that shadow is deliberately conservative.
    """
    quota_provider = quota_provider or allsolve.get_quota
    refresh_many = refresh_many or (lambda jobs: allsolve.Job.refresh_statuses(jobs, delay_s=0))
    cached = sum(task["cached"] for task in tasks)
    work = [task for task in tasks if not task["cached"]]
    telemetry = {"strategy": "quota_aware_parallel_refill", "basis_cores": BASIS_CORES,
                 "total_basis_solves": len(tasks), "cached_basis_fields": cached,
                 "newly_started_basis_solves": 0, "peak_parallel_solves": 0,
                 "peak_inflight_solves": 0, "peak_allocated_cores": 0,
                 "completed_simulation_ids": [task["run"]["simulation_id"] for task in tasks if task["cached"]],
                 "observations": [], "started_at": utc_now(), "polling": "Job.refresh_statuses"}
    capacity_deadline = None
    quota = None

    def observe(stage, message):
        active = [task for task in work if task["status"] not in (allsolve.Job.NOT_STARTED, allsolve.Job.SUCCESS)]
        running = [task for task in active if task["status"] == allsolve.Job.RUNNING]
        completed = cached + sum(task["status"] == allsolve.Job.SUCCESS for task in work)
        fields = {"active_solves": len(active), "allocated_cores": BASIS_CORES*len(active),
                  "cached_basis_fields": cached, "completed_basis_solves": completed,
                  "remaining_basis_solves": len(tasks)-completed, "total_basis_solves": len(tasks),
                  "queued_basis_solves": sum(task["status"] == allsolve.Job.NOT_STARTED for task in work),
                  "running_simulation_ids": [task["run"]["simulation_id"] for task in active],
                  "cloud_running_solves": len(running)}
        if quota is not None:
            fields.update(quota)
        telemetry["peak_parallel_solves"] = max(telemetry["peak_parallel_solves"], len(running))
        telemetry["peak_inflight_solves"] = max(telemetry["peak_inflight_solves"], len(active))
        telemetry["peak_allocated_cores"] = max(telemetry["peak_allocated_cores"], fields["allocated_cores"])
        fields["peak_parallel_solves"] = telemetry["peak_parallel_solves"]
        if running and (not telemetry["observations"] or len(running) > telemetry["observations"][-1]["running_count"]):
            telemetry["observations"].append({"observed_at": utc_now(), "running_count": len(running),
                "running_simulation_ids": [task["run"]["simulation_id"] for task in running],
                "cloud_job_ids": [task["job"].id for task in running], **(quota or {})})
        progress({"stage": stage, "message": message, **fields})

    if not work:
        observe("cached", "All requested pressure fields are verified cache hits; no cloud jobs started")
        telemetry["finished_at"] = utc_now()
        return telemetry
    for task in work:
        task["job"] = task["simulation"]._get_job()
        task["status"] = task["simulation"].get_status()
        # A reconstructed tracked job may briefly have no reported status.
        # Reserve its resume window too; newly started jobs reset this below.
        task["deadline"] = clock() + timeout_seconds
    while True:
        # _get_job is the 0.5.2 SDK adapter to its tracked public Job. Batch
        # refresh updates that same object; Simulation.get_status reads it.
        tracked = [task["job"] for task in work if task["job"] is not None and task["status"] != allsolve.Job.SUCCESS]
        if tracked:
            refresh_many(tracked)
        for task in work:
            previous = task["status"]
            observed = task["simulation"].get_status()
            task["status"] = (previous or allsolve.Job.QUEUED) if observed == allsolve.Job.NOT_STARTED and task["job"] is not None else observed
            if task["status"] in (allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.PARTIAL_SUCCESS):
                on_update(task, task["status"], False)
                raise RuntimeError(f"Cloud {task['name']} {task['run']['simulation_id']} ended with {task['status']}; inspect before replacing")
            if task["status"] != previous:
                on_update(task, task["status"], False)
        if all(task["status"] == allsolve.Job.SUCCESS for task in work):
            observe("cloud_complete", "All independent cloud solves succeeded; verifying pressure fields locally")
            telemetry["completed_simulation_ids"] = [task["run"]["simulation_id"] for task in tasks]
            telemetry["finished_at"] = utc_now()
            return telemetry
        active = [task for task in work if task["status"] not in (allsolve.Job.NOT_STARTED, allsolve.Job.SUCCESS)]
        if any(clock() > task["deadline"] for task in active):
            raise TimeoutError("An independent cloud job is still running; resume to reuse its existing simulation")
        if active:
            capacity_deadline = None
        else:
            if capacity_deadline is None:
                capacity_deadline = clock() + timeout_seconds
            if clock() > capacity_deadline:
                raise TimeoutError("Still waiting for shared cloud cores; resume to reuse its jobs and caches")
        quota = quota_values(quota_provider())
        telemetry.update(quota)
        active = [task for task in work if task["status"] not in (allsolve.Job.NOT_STARTED, allsolve.Job.SUCCESS)]
        available = max(0, quota["max_concurrent_cores"]-quota["account_running_cores"]
                        -quota["account_reserved_cores"]-BASIS_CORES*len(active))
        capacity = available // BASIS_CORES
        pending = [task for task in work if task["status"] == allsolve.Job.NOT_STARTED]
        if not capacity or not pending:
            if active:
                observe("parallel_solving", f"{len(active)} independent Allsolve jobs in flight")
            else:
                observe("waiting_for_quota", "Waiting for shared Allsolve cores; existing jobs and caches are preserved")
            sleep(poll_seconds)
            continue
        started = 0
        for task in pending[:capacity]:
            try:
                task["simulation"].start()
            except Exception as exc:
                if quota_start_retry(exc):
                    observe("waiting_for_quota", "Shared compute changed during submission; retrying within quota")
                    break
                raise
            task["job"] = task["simulation"]._get_job()
            if task["job"] is None:
                raise RuntimeError("Allsolve start returned no tracked cloud job; inspect before retrying")
            task["status"] = task["simulation"].get_status()
            # The local slot is occupied even if server bookkeeping lags.
            if task["status"] == allsolve.Job.NOT_STARTED:
                task["status"] = allsolve.Job.QUEUED
            task["deadline"] = clock() + timeout_seconds
            started += 1
            telemetry["newly_started_basis_solves"] += 1
            on_update(task, task["status"], True)
            observe("parallel_submitting", f"Submitted {started} independent jobs in this quota-sized batch")
        if not started:
            sleep(poll_seconds)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def get_catalog():
    data = read_json(DATA)
    width, _, height = data["room"]["size_m"]
    slots = [
        ("east_a", "East wall · south", [width-.2, 1, .6], [.2, 2, 1]),
        ("east_b", "East wall · north", [width-.2, 3.5, .6], [.2, 2, 1]),
        ("west", "West wall", [0, 1, .6], [.2, 2, 1]),
        ("south", "South wall", [2, 0, .6], [2, .2, 1]),
        ("ceiling_a", "Ceiling · west", [.8, 2, height-.2], [2, 1, .2]),
        ("ceiling_b", "Ceiling · east", [3, 2, height-.2], [2, 1, .2]),
    ]
    microphones = {m["id"]: m for m in data["microphones"]}
    return {
        "room": {"id": "dechorate", **data["room"]}, "frequency_hz": FREQUENCY,
        "sources": data["sources"], "microphones": data["microphones"],
        "slots": [{"id": i, "name": n, "position_m": p, "size_m": s, "area_m2": 2}
                  for i, n, p, s in slots],
        "quietness_metric": "relative_pressure_reduction_db", "samples_per_zone": 81,
        "point_defaults": {"sources": [{"id": "src1", "position_m": data["sources"][0]["position_m"],
                                        "level_db": DEFAULT_SOURCE_LEVEL_DB}],
                           "listener_m": microphones["mic1"]["position_m"], "max_panels": 1,
                           "allowed_slot_ids": [s[0] for s in slots]},
        "source_level_reference": {"reference_pressure_pa": PRESSURE_REFERENCE_PA,
                                   "metric": "normalized_spl_db", "location": "source sphere boundary",
                                   "default_level_db": DEFAULT_SOURCE_LEVEL_DB},
        "defaults": {"sources": [{"id": "src1", "strength": 1}],
                     "quiet_zones": [{"id": f"zone{i+1}", "center_m": microphones[mid]["position_m"],
                                      "size_m": [.4, .4], "target_pressure_pa": .05, "target_reduction_db": 6}
                                     for i, mid in enumerate(("mic1", "mic26"))],
                     "quietness_metric": "relative_pressure_reduction_db",
                     "budget_eur": 600, "max_objects": 3, "object_cost_eur": 120,
                     "allowed_slot_ids": [s[0] for s in slots]},
        "maximums": {"sources": 3, "quiet_zones": 4, "objects": 6},
        "dataset": {"name": "dEchorate", "url": "https://zenodo.org/records/4626590", "license": "MIT"},
        "assumptions": [
            "Room dimensions and source coordinates come from the dEchorate laboratory dataset.",
            "125 Hz harmonic model; rigid room boundaries and omnidirectional 0.08 m spherical sources.",
            "Source strength 1 imposes 1 Pa peak at its sphere; optional absolute area ceilings are normalized RMS pressure.",
            "Independent source powers are summed; coherent phase relationships are not modeled.",
            "Each object is a 0.4 m3 air region with illustrative volumetric damping 0.5, not a calibrated commercial absorber.",
            "Optimum means fewest affordable objects among six fixed placements, then greatest minimum margin in the selected metric.",
            "Quietness is checked at 81 samples per horizontal area; unsampled positions and other frequencies are not guaranteed.",
            "Prices are editable planning inputs; absolute pressure is not calibrated to recorded sound power or dB(A).",
        ],
    }


def vector(values):
    return dict(zip(("x", "y", "z"), values))


def model_config(catalog):
    geometries = [{"type": "box", "name": "room", "position": vector([0, 0, 0]),
                   "size": vector(catalog["room"]["size_m"]), "alignment": "corner"}]
    for source in catalog["sources"]:
        geometries.append({"type": "sphere", "name": source["id"], "position": vector(source["position_m"]), "radius": SOURCE_RADIUS})
    for slot in catalog["slots"]:
        geometries.append({"type": "box", "name": slot["id"], "position": vector(slot["position_m"]),
                           "size": vector(slot["size_m"]), "alignment": "corner"})
    geometries.append({"type": "fragmentAll", "name": "partition_room"})
    names = ["room", *[s["id"] for s in catalog["sources"]], *[s["id"] for s in catalog["slots"]]]
    regions = [{"name": name, "type": "regionRule", "entityType": "volume",
                "attributePath": [{"key": "name", "value": name}]} for name in names]
    regions.append({"name": "all_volumes", "type": "computed", "entityType": "volume", "operation": "union", "regions": names})
    for source in catalog["sources"]:
        regions.append({"name": source["id"]+"_boundary", "type": "computed", "entityType": "surface",
                        "operation": "boundary", "regions": [source["id"]]})
    return {"name": "RoomValue dEchorate 3D placement optimizer", "dimension": 3,
            "description": "Normalized 125 Hz discrete absorber placement search; actual measured room geometry",
            "labels": ["roomvalue", "dechorate", "3d-optimizer"], "verbose": False,
            "geometries": geometries, "regions": regions,
            "materials": [{"name": "Assumed air", "target": "all_volumes", "density": 1.2,
                           "speedOfSound": catalog["room"]["speed_of_sound_m_s"]}],
            "meshes": [{"name": "optimizer_3d", "nodeType": "lambda", "scaleFactor": 1,
                        "useMeshRefiner": False, "curvedMesh": False, "curvatureEnhancement": 6,
                        "maxRunTimeMinutes": 10, "meshSizeMin": .025, "meshSizeMax": .24,
                        "refinements": [*[{"region": s["id"]+"_boundary", "maxSize": .04} for s in catalog["sources"]],
                                        *[{"region": s["id"], "maxSize": .10} for s in catalog["slots"]]]}]}


def model_signature(config):
    return hashlib.sha256(json.dumps({"config": config, "frequency": FREQUENCY,
                                      "damping": DAMPING, "order": 2, "source": "sn(1)"}, sort_keys=True).encode()).hexdigest()


def point_catalog(request, catalog):
    """Reuse canonical fields; moved sources get isolated geometry and caches."""
    source_map = {source["id"]: source for source in catalog["sources"]}
    selected = {source["id"]: source for source in request["sources"]}
    if not selected or not selected.keys() <= source_map.keys():
        raise ValueError("Choose source IDs from the dataset catalog")
    canonical = all(np.allclose(source["position_m"], source_map[source["id"]]["position_m"],
                                rtol=0, atol=1e-9) for source in selected.values())
    profile = deepcopy(catalog)
    if not canonical:
        profile["sources"] = [{**source, "position_m": list(selected[source["id"]]["position_m"]),
                               "position_status": "user_input", "original_dataset_position_m": source["position_m"]}
                              for source in catalog["sources"] if source["id"] in selected]
    profile["assumptions"] = [
        "Room dimensions come from the dEchorate laboratory dataset; edited source positions are user inputs.",
        "125 Hz harmonic model; rigid room boundaries and omnidirectional 0.08 m spherical sources.",
        "Source dB levels prescribe RMS pressure at the source sphere boundary, referenced to 20 microPa; this is an uncalibrated normalized model, not measured loudness or dB(A).",
        "Independent source powers are summed; coherent phase relationships are not modeled.",
        "Each panel is a 0.4 m3 air region with illustrative volumetric damping 0.5, not a calibrated commercial absorber.",
        "The minimum is at one XYZ listener among all allowed fixed panel placements up to the panel limit; no budget or cost is used.",
        "Other listening positions and frequencies are not optimized; continuous placement and global room quietness are not guaranteed.",
    ]
    signature = model_signature(model_config(profile))
    return profile, HERE if canonical else HERE / "scenarios" / signature[:16]


def zone_points(zone):
    center = np.asarray(zone["center_m"], dtype=float)
    width, length = zone["size_m"]
    xs, ys = np.meshgrid(np.linspace(center[0]-width/2, center[0]+width/2, 9),
                         np.linspace(center[1]-length/2, center[1]+length/2, 9))
    return np.column_stack((xs.ravel(), ys.ravel(), np.full(xs.size, center[2])))


class FieldMesh:
    """Verified straight quadratic tetrahedra; no extrapolation or nearest node."""
    def __init__(self, points, cells):
        self.points, self.cells = points, cells
        if cells.ndim != 2 or cells.shape[1] != 10:
            raise ValueError("Expected ten-node quadratic tetrahedra")
        self.vertices = points[cells[:, :4]]
        midpoints = np.stack([(self.vertices[:, a]+self.vertices[:, b])/2 for a, b in EDGE_PAIRS], axis=1)
        if not np.allclose(points[cells[:, 4:]], midpoints, atol=1e-8, rtol=0):
            raise ValueError("Unsupported curved geometry or tetrahedron ordering")
        self.lower, self.upper = self.vertices.min(axis=1), self.vertices.max(axis=1)
        self.inverse = np.linalg.inv(self.vertices[:, 1:]-self.vertices[:, :1])

    def locate(self, queries):
        queries = np.asarray(queries, dtype=float)
        if queries.ndim != 2 or queries.shape[1] != 3 or not np.isfinite(queries).all():
            raise ValueError("Expected finite XYZ sample coordinates")
        indices, weights = [], []
        for query in queries:
            candidates = np.flatnonzero(np.all((self.lower <= query+1e-8) & (self.upper >= query-1e-8), axis=1))
            last = np.einsum("ni,nij->nj", query-self.vertices[candidates, 0], self.inverse[candidates])
            bary = np.column_stack((1-last.sum(axis=1), last))
            matches = np.flatnonzero(np.all((bary >= -1e-8) & (bary <= 1+1e-8), axis=1))
            if not len(matches):
                raise ValueError(f"Quietness sample outside solved 3D field: {query.tolist()}")
            index = matches[0]
            b = bary[index]
            indices.append(candidates[index])
            weights.append(np.r_[b*(2*b-1), [4*b[a]*b[c] for a, c in EDGE_PAIRS]])
        return self.cells[indices], np.asarray(weights)

    def sample(self, values, locations):
        cells, weights = locations
        return np.einsum("ij,ij->i", values[cells], weights)


def read_field(path, room_size):
    with h5py.File(path, "r") as file:
        group = file["VTKHDF"]
        points = np.asarray(group["Points"], dtype=float)
        fields = list(group["PointData"])
        if len(fields) != 1:
            raise ValueError("Expected exactly one requested pressure component per field export")
        values = np.asarray(group["PointData"][fields[0]], dtype=float)
        connectivity = np.asarray(group["Connectivity"], dtype=np.int64)
        offsets = np.asarray(group["Offsets"], dtype=np.int64)
        types = np.asarray(group["Types"], dtype=np.uint8)
    if not np.isfinite(points).all() or not np.isfinite(values).all() or values.shape != (len(points),):
        raise ValueError("Invalid or nonfinite cloud field")
    if not np.all(np.isin(types, [24, 71])) or not np.all(np.diff(offsets) == 10) or offsets[0] != 0 or offsets[-1] != len(connectivity):
        raise ValueError("Expected quadratic tetrahedral VTKHDF export")
    if not np.allclose(points.min(axis=0), 0, atol=1e-7) or not np.allclose(points.max(axis=0), room_size, atol=1e-7):
        raise ValueError("Field differs from dataset room bounds")
    cells = connectivity.reshape((-1, 10))
    if cells.min() < 0 or cells.max() >= len(points):
        raise ValueError("Invalid field connectivity")
    return points, cells, values


class Solver:
    def __init__(self, catalog, progress, cache_dir=None):
        self.here = Path(cache_dir) if cache_dir is not None else HERE
        self.here.mkdir(parents=True, exist_ok=True)
        self.catalog, self.progress = catalog, progress
        self.config = model_config(catalog)
        signature = model_signature(self.config)
        self.state_path = self.here / "state.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else {"model_sha256": signature, "runs": {}}
        if self.state["model_sha256"] != signature:
            raise RuntimeError("Optimizer geometry changed: preserve this cache and create a new experiment version")
        env = dotenv_values(CASE.parent / ".env")
        (self.here / "sdk-cache").mkdir(exist_ok=True)
        self.client = allsolve.Client(api_key=os.environ.get("ALLSOLVE_ACCESS_KEY") or env.get("ALLSOLVE_ACCESS_KEY"),
                                      api_secret=os.environ.get("ALLSOLVE_SECRET_KEY") or env.get("ALLSOLVE_SECRET_KEY"),
                                      host=os.environ.get("ALLSOLVE_HOST") or env.get("ALLSOLVE_HOST") or "https://allsolve.quanscient.com/",
                                      cache_base_dir=str(self.here / "sdk-cache"), dotenv_file=None)
        if self.state.get("project_id"):
            self.project = self.client.get_project(self.state["project_id"])
        else:
            self.project = self.client.create_project(name=self.config["name"], description=self.config["description"], dimension=3)
            self.state.update(project_id=self.project.id, project_url=self.client.get_url(self.project))
            self.save()
        self.emit("geometry", "Preparing the dataset room and six candidate placements")
        if not self.state.get("geometry_built"):
            write_json(self.here / "model_config.json", self.config)
            allsolve.import_project(self.config, project_to_modify=self.project, run_meshes_and_simulations=False)
            self.state["geometry_built"] = True
            self.save()
        self.regions = {r.name: r for r in self.project.get_regions()}
        for region in self.config["regions"]:
            if region["name"] not in self.regions or not self.regions[region["name"]].entity_tags:
                raise RuntimeError(f"Missing optimizer geometry region {region['name']}")
        self.mesh = next(m for m in self.project.get_meshes() if m.name == "optimizer_3d")
        self.ensure_run(self.mesh, "mesh", 3)
        if not self.state.get("mesh"):
            self.state["mesh"] = self.validate_mesh()
            self.save()
        self.psets = {p.name: p for p in self.project.get_physics_sets()}
        self.sims = {s.name: s for s in self.project.get_simulations()}
        self.field_mesh = None
        self.locations = None
        self.prepared = {}
        self.parallel_execution = None

    def emit(self, stage, message, **extra):
        self.progress({"stage": stage, "message": message, "project_url": self.state.get("project_url"), **extra})

    def save(self):
        write_json(self.state_path, self.state)

    def ensure_run(self, job, label, cores):
        status = job.get_status()
        if status == allsolve.Job.SUCCESS:
            return
        if status in (allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.PARTIAL_SUCCESS):
            raise RuntimeError(f"Cloud {label} {job.id} has status {status}; inspect the job before replacing it")
        if status is None or status == allsolve.Job.NOT_STARTED:
            quota = quota_values(allsolve.get_quota())
            if quota["max_concurrent_cores"]-quota["account_running_cores"]-quota["account_reserved_cores"] < cores:
                raise RuntimeError("Insufficient shared Allsolve cores; this job can be resumed later")
            job.start()
        self.emit("solving", f"Cloud {label} running", latest_simulation_id=job.id)
        deadline = time.monotonic()+1200
        while job.is_running(refresh_delay_s=3):
            if time.monotonic() > deadline:
                raise TimeoutError("Cloud solve remains running; resume this job to harvest its result")
        if job.get_status() != allsolve.Job.SUCCESS:
            raise RuntimeError(f"Cloud {label} {job.id} ended with {job.get_status()}")

    def validate_mesh(self):
        path = self.here / "mesh.msh"
        if not path.exists():
            self.mesh.save_mesh_file(output_dir=str(self.here), filename=path.name)
        mesh = meshio.read(path)
        bounds = np.column_stack((mesh.points.min(axis=0), mesh.points.max(axis=0)))
        size = self.catalog["room"]["size_m"]
        if not np.allclose(bounds[:, 0], 0, atol=1e-6) or not np.allclose(bounds[:, 1], size, atol=1e-6):
            raise RuntimeError("Mesh has wrong dataset room bounds")
        cells = np.concatenate([c.data[:, :4] for c in mesh.cells if c.type in ("tetra", "tetra10")])
        vertices = mesh.points[cells]
        volumes = np.abs(np.linalg.det(vertices[:, 1:]-vertices[:, :1]))/6
        if np.any(volumes <= 1e-15) or not math.isclose(float(volumes.sum()), float(np.prod(size)), rel_tol=1e-4):
            raise RuntimeError("Invalid tetrahedra or total mesh volume")
        max_edge = max(float(np.linalg.norm(vertices[:, a]-vertices[:, b], axis=1).max()) for a, b in EDGE_PAIRS)
        return {"mesh_id": self.mesh.id, "dimension": 3, "status": "SUCCESS", "bounds_m": bounds.tolist(),
                "tetrahedron_count": len(cells), "volume_m3": float(volumes.sum()), "max_edge_m": max_edge,
                "min_elements_per_wavelength": self.catalog["room"]["speed_of_sound_m_s"]/FREQUENCY/max_edge,
                "field_interpolation_order": 2}

    def prepare_basis(self, source_id, slots):
        name = source_id+"__"+("_".join(sorted(slots)) or "baseline")
        if name in self.prepared:
            return self.prepared[name]
        folder = self.here / "fields" / name
        folder.mkdir(parents=True, exist_ok=True)
        field_path = folder / "complex.npz"
        run = self.state["runs"].get(name, {})
        if field_path.exists() and run.get("status") == "SUCCESS":
            if hashlib.sha256(field_path.read_bytes()).hexdigest() != run.get("field_cache_sha256"):
                raise RuntimeError("Cached cloud pressure field checksum mismatch")
            task = {"name": name, "folder": folder, "field_path": field_path,
                    "run": run, "cached": True, "simulation": None}
            self.prepared[name] = task
            return task
        if not field_path.exists() or run.get("status") != "SUCCESS":
            pset = self.psets.get(name)
            if pset is None:
                pset = self.project.create_physics_set(name=name, description="Immutable source/layout basis")
                wave = pset.add_physics(allsolve.Physics.AcousticWaves(target=self.regions["all_volumes"]))
                wave.set_field_interpolation_order(2)
                wave.save()
                wave.add_interactions([allsolve.Interaction.AcousticWavesConstraint(
                    name="Normalized 1 Pa peak sphere", target=self.regions[source_id+"_boundary"], acoustic_waves_constraint="sn(1)")])
                for slot in slots:
                    wave.add_interactions([allsolve.Interaction.AcousticWavesAcousticDamping(
                        name="Illustrative finite damped object", target=self.regions[slot],
                        acoustic_waves_acoustic_damping_damping_value=DAMPING)])
                self.psets[name] = pset
            waves = pset.get_physics()
            if len(waves) != 1 or waves[0].definition != "acousticWaves":
                raise RuntimeError(f"Incomplete physics set {name}; inspect before resuming")
            wave = waves[0]
            if wave.target_region_id != self.regions["all_volumes"].id or wave.get_field_interpolation_order() != "2":
                raise RuntimeError(f"Physics domain or interpolation order changed in {name}")
            interactions = wave.get_interactions()
            constraints = [i for i in interactions if i.definition == "acousticWavesConstraint"]
            dampers = [i for i in interactions if i.definition == "acousticWavesAcousticDamping"]
            if len(interactions) != 1+len(slots) or len(constraints) != 1 or len(dampers) != len(slots):
                raise RuntimeError(f"Incomplete source or damping interactions in {name}; inspect before resuming")
            source = constraints[0]
            if (source.target_region_id() != self.regions[source_id+"_boundary"].id or source.enabled is False
                    or "sn(1)" not in [p.value for p in source.parameters]):
                raise RuntimeError(f"Source definition changed in {name}")
            for slot in slots:
                matching = [d for d in dampers if d.target_region_id() == self.regions[slot].id]
                if (len(matching) != 1 or matching[0].enabled is False
                        or str(DAMPING) not in [p.value for p in matching[0].parameters]):
                    raise RuntimeError(f"Damping definition changed for {slot} in {name}")
            sim = self.sims.get(name)
            if sim is None:
                sim = self.project.create_simulation_harmonic(name=name, description="Independent source/layout 3D basis",
                        max_run_time_minutes=10, mesh=self.mesh, physics_set=pset,
                        fundamental_frequency=str(FREQUENCY), solver_mode=allsolve.SolverMode.DIRECT)
                probe = self.catalog["microphones"][0]["position_m"]
                coords = ",".join(str(p) for p in probe)
                sim.add_outputs([*[allsolve.Output.FieldOutput(name=label, expression=f"getharmonic({h},p)")
                                   for label, h in (("Real", 2), ("Imag", 3))],
                                 *[allsolve.Output.ValueOutput(name=label+"_probe", expression=f"interpolate(reg.all_volumes,getharmonic({h},p),[{coords}])")
                                   for label, h in (("Real", 2), ("Imag", 3))]])
                sim.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_4_64GB, node_count=1))
                sim.save()
                self.sims[name] = sim
            run.update(simulation_id=sim.id, physics_set_id=pset.id, source_id=source_id, slot_ids=list(slots))
            self.state["runs"][name] = run
            self.save()
            task = {"name": name, "folder": folder, "field_path": field_path,
                    "run": run, "cached": False, "simulation": sim}
            self.prepared[name] = task
            return task

    def solve_batch(self, sources, layouts):
        tasks = []
        total = len(sources)*len(layouts)
        for slots in layouts:
            for source in sources:
                tasks.append(self.prepare_basis(source["id"], slots))
                self.emit("planning_parallel", f"Prepared {len(tasks)} of {total} independent basis definitions",
                          total_basis_solves=total, prepared_basis_solves=len(tasks))

        def update(task, status, started):
            task["run"]["cloud_status"] = status
            if task.get("job") is not None:
                task["run"]["cloud_job_id"] = task["job"].id
            if started:
                task["run"]["cloud_started_at"] = utc_now()
            self.save()

        def report(event):
            self.emit(event.pop("stage"), event.pop("message"), **event)

        telemetry = run_parallel_tasks(tasks, report, update)
        self.parallel_execution = telemetry
        self.state["last_parallel_execution"] = telemetry
        self.save()
        for task in tasks:
            if not task["cached"]:
                self.harvest_basis(task)
        return telemetry

    def harvest_basis(self, task):
        name, folder, field_path = task["name"], task["folder"], task["field_path"]
        run, sim = task["run"], task["simulation"]
        if sim.get_status() != allsolve.Job.SUCCESS:
            raise RuntimeError("Cannot harvest a basis without successful cloud provenance")
        if not task["cached"]:
            self.emit("downloading", f"Reading verified 3D pressure field for {name}", latest_simulation_id=sim.id)
            components = []
            for label in ("Real", "Imag"):
                files = list(folder.glob(label+"_*.hdf"))
                if not files:
                    sim.save_output_field(label, output_dir=str(folder), refresh=True)
                    files = list(folder.glob(label+"_*.hdf"))
                if len(files) != 1:
                    raise RuntimeError("Expected one cloud field export per component")
                points, cells, values = read_field(files[0], self.catalog["room"]["size_m"])
                geometry_path = self.here / "field_geometry.npz"
                if not geometry_path.exists():
                    np.savez_compressed(geometry_path, points=points, cells=cells)
                else:
                    with np.load(geometry_path) as g:
                        if not np.array_equal(g["points"], points) or not np.array_equal(g["cells"], cells):
                            raise RuntimeError("Cloud field geometry changed across cached basis runs")
                components.append(values)
            self.load_geometry()
            probe_values = sim.get_output_values(refresh=True)["nostep"]
            location = self.field_mesh.locate([self.catalog["microphones"][0]["position_m"]])
            for label, values in zip(("Real", "Imag"), components):
                expected = float(np.asarray(probe_values[label+"_probe"]).ravel()[0])
                actual = float(self.field_mesh.sample(values, location)[0])
                if not np.isclose(expected, actual, rtol=1e-5, atol=1e-7):
                    raise RuntimeError(f"Field interpolation failed independent {label} probe validation")
            np.savez_compressed(field_path, real=components[0], imag=components[1])
            run.update(status="SUCCESS", field_cache_sha256=hashlib.sha256(field_path.read_bytes()).hexdigest(),
                       independent_probe_validation=True)
            self.save()
            task["cached"] = True

    def basis(self, source_id, slots, queries):
        task = self.prepare_basis(source_id, slots)
        if not task["cached"]:
            self.solve_batch([{"id": source_id}], [tuple(slots)])
        field_path, run = task["field_path"], task["run"]
        self.load_geometry()
        if self.locations is None:
            self.locations = self.field_mesh.locate(queries)
        if hashlib.sha256(field_path.read_bytes()).hexdigest() != run["field_cache_sha256"]:
            raise RuntimeError("Cached cloud pressure field checksum mismatch")
        with np.load(field_path) as field:
            values = self.field_mesh.sample(field["real"], self.locations)+1j*self.field_mesh.sample(field["imag"], self.locations)
        return values, run["simulation_id"]

    def load_geometry(self):
        if self.field_mesh is None:
            with np.load(self.here / "field_geometry.npz") as mesh:
                self.field_mesh = FieldMesh(mesh["points"], mesh["cells"])


def affordable_layouts(request):
    allowed = sorted(request["allowed_slot_ids"])
    return [tuple(slots) for count in range(min(len(allowed), request["max_objects"])+1)
            if count*request["object_cost_eur"] <= request["budget_eur"]+1e-9
            for slots in itertools.combinations(allowed, count)]


def rms_pressure(bases, strengths):
    return np.sqrt(sum(strength**2*np.abs(basis)**2 for basis, strength in zip(bases, strengths))/2)


def quietness_metric(request):
    # Retain absolute semantics for pressure-only jobs saved before mode selection.
    return request.get("quietness_metric") or (
        "absolute_rms_pressure_pa" if all(z.get("target_pressure_pa") is not None and z.get("target_reduction_db") is None
                                           for z in request["quiet_zones"]) else "relative_pressure_reduction_db")


def evaluate_layout(slots, pressure, baseline, zones, queries, cost, simulation_ids, metric="absolute_rms_pressure_pa"):
    results = []
    for index, zone in enumerate(zones):
        values = pressure[index*81:(index+1)*81]
        untreated = baseline[index*81:(index+1)*81]
        worst = int(np.argmax(values))
        peak, base = float(values[worst]), float(untreated.max())
        reduction = 20*math.log10(max(base, 1e-30)/max(peak, 1e-30))
        relative = metric == "relative_pressure_reduction_db"
        target_db = zone["target_reduction_db"] if relative else None
        ceiling = base*10**(-target_db/20) if relative else zone["target_pressure_pa"]
        results.append({"id": zone["id"], "target_pressure_pa": ceiling, "target_reduction_db": target_db,
                        "baseline_peak_pa": base, "treated_peak_pa": peak, "reduction_db": reduction,
                        "met_target": reduction >= target_db if relative else peak <= ceiling, "sample_count": 81,
                        "sample_points_m": queries[index*81:(index+1)*81].tolist(),
                        "sample_rms_pa": values.tolist(),
                        "worst_point_m": queries[index*81+worst].tolist()})
    feasible = all(z["met_target"] for z in results)
    return {"slot_ids": list(slots), "object_count": len(slots), "cost_eur": len(slots)*cost,
            "zones": results, "simulation_ids": simulation_ids, "feasible": feasible, "status": "SUCCESS",
            "minimum_margin_pa": min(z["target_pressure_pa"]-z["treated_peak_pa"] for z in results),
            "selection_score": min(z["reduction_db"]-z["target_reduction_db"] for z in results) if metric == "relative_pressure_reduction_db"
                               else min(z["target_pressure_pa"]-z["treated_peak_pa"] for z in results)}


def search(request, basis_provider, progress, catalog, batch_provider=None):
    """Testable count-first exhaustive search; provider must supply solver bases."""
    queries = np.concatenate([zone_points(z) for z in request["quiet_zones"]])
    layouts = affordable_layouts(request)
    evaluations, baseline = [], None
    strengths = [s["strength"] for s in request["sources"]]
    metric = quietness_metric(request)
    chosen = None
    for count, group in itertools.groupby(layouts, key=len):
        group = list(group)
        if batch_provider is not None:
            batch_provider(request["sources"], group)
        feasible = []
        for slots in group:
            bases, ids = zip(*(basis_provider(s["id"], slots, queries) for s in request["sources"]))
            pressure = rms_pressure(bases, strengths)
            if baseline is None:
                baseline = pressure
            evaluation = evaluate_layout(slots, pressure, baseline, request["quiet_zones"], queries, request["object_cost_eur"], list(ids), metric)
            evaluations.append(evaluation)
            if evaluation["feasible"]:
                feasible.append(evaluation)
            progress({"stage": "searching", "message": f"Evaluated {len(evaluations)} of {len(layouts)} affordable layouts",
                      "evaluated": len(evaluations), "total": len(layouts), "best_count": count if feasible else None,
                      "latest_simulation_id": ids[-1]})
        if feasible:
            chosen = max(feasible, key=lambda e: e["selection_score"])
            break
    best = chosen or max(evaluations, key=lambda e: (e["selection_score"], -e["object_count"]))
    return {"dimension": 3, "frequency_hz": FREQUENCY, "quietness_metric": metric,
            "model_label": "3D Allsolve constrained placement search", "sources": request["sources"], "quiet_zones": request["quiet_zones"],
            "search": {"evaluated_layouts": len(evaluations), "total_layouts": len(layouts),
                       "candidate_slots": request["allowed_slot_ids"], "exhaustive_through_count": evaluations[-1]["object_count"],
                       "optimality_scope": "Fewest affordable objects within the allowed fixed placements and maximum count; tie broken by greatest minimum margin in the selected metric. All lower counts and layouts at the winning count were evaluated.",
                       "source_combination": "incoherent_power_sum"},
            "feasible": chosen is not None, "optimal_layout": chosen, "best_available_layout": best,
            "evaluations": evaluations, "assumptions": catalog["assumptions"]}


def run_optimization(request, progress=lambda event: None):
    catalog = get_catalog()
    solver = Solver(catalog, progress)
    result = search(request, solver.basis, progress, catalog, batch_provider=solver.solve_batch)
    result.update(project_id=solver.project.id, project_url=solver.state["project_url"],
                  mesh=solver.state["mesh"], model_sha256=solver.state["model_sha256"],
                  parallel_execution=solver.parallel_execution)
    write_json(HERE / "latest_result.json", result)
    progress({"stage": "complete", "message": "Minimum object count found" if result["feasible"] else "No feasible layout in the allowed search",
              "evaluated": result["search"]["evaluated_layouts"], "total": result["search"]["total_layouts"],
              "best_count": result["optimal_layout"]["object_count"] if result["feasible"] else None,
              "project_url": result["project_url"]})
    return result


def source_peak_strength(level_db):
    """Linear multiplier for a 1 Pa peak basis from sphere-boundary RMS SPL."""
    return math.sqrt(2)*PRESSURE_REFERENCE_PA*10**(level_db/20)


def pressure_db(pressure_rms_pa):
    return 20*math.log10(max(float(pressure_rms_pa), 1e-30)/PRESSURE_REFERENCE_PA)


def point_layouts(request):
    allowed = sorted(request["allowed_slot_ids"])
    return [slots for count in range(min(request["max_panels"], len(allowed))+1)
            for slots in itertools.combinations(allowed, count)]


def search_point(request, basis_provider, progress, catalog):
    """Minimize one listener's pressure over all subsets, including untreated."""
    queries = np.asarray([request["listener_m"]], dtype=float)
    layouts = point_layouts(request)
    strengths = [source_peak_strength(source["level_db"]) for source in request["sources"]]
    evaluations = []
    for slots in layouts:
        bases, ids = zip(*(basis_provider(source["id"], slots, queries) for source in request["sources"]))
        pressure = float(rms_pressure(bases, strengths)[0])
        noise = pressure_db(pressure)
        evaluation = {"slot_ids": list(slots), "object_count": len(slots), "pressure_rms_pa": pressure,
                      "noise_db": noise, "reduction_db": (evaluations[0]["noise_db"] if evaluations else noise)-noise,
                      "simulation_ids": list(ids), "status": "SUCCESS"}
        evaluations.append(evaluation)
        best = min(evaluations, key=lambda candidate: (candidate["pressure_rms_pa"], candidate["object_count"]))
        progress({"stage": "searching", "message": f"Evaluated {len(evaluations)} of {len(layouts)} panel layouts",
                  "evaluated": len(evaluations), "total": len(layouts), "best_count": best["object_count"],
                  "latest_simulation_id": ids[-1]})
    best = min(evaluations, key=lambda candidate: (candidate["pressure_rms_pa"], candidate["object_count"]))
    return {"objective": "minimize_listener_noise", "dimension": 3, "frequency_hz": FREQUENCY,
            "noise_metric": "normalized_spl_db", "pressure_reference_pa": PRESSURE_REFERENCE_PA,
            "sources": request["sources"], "listener_m": request["listener_m"], "max_panels": request["max_panels"],
            "baseline": evaluations[0], "optimal_layout": best, "evaluations": evaluations,
            "search": {"evaluated_layouts": len(evaluations), "total_layouts": len(layouts),
                       "candidate_slots": request["allowed_slot_ids"],
                       "optimality_scope": "Lowest RMS pressure at the chosen listener among every allowed fixed placement subset from zero through the maximum panel count; exact ties prefer fewer panels.",
                       "source_combination": "incoherent_power_sum"},
            "assumptions": catalog["assumptions"]}


def run_point_optimization(request, progress=lambda event: None):
    catalog, cache_dir = point_catalog(request, get_catalog())
    solver = Solver(catalog, progress, cache_dir=cache_dir)
    solver.solve_batch(request["sources"], point_layouts(request))
    result = search_point(request, solver.basis, progress, catalog)
    result.update(project_id=solver.project.id, project_url=solver.state["project_url"],
                  mesh=solver.state["mesh"], model_sha256=solver.state["model_sha256"],
                  parallel_execution=solver.parallel_execution,
                  source_geometry="dataset_positions" if cache_dir == HERE else "user_positions")
    if cache_dir != HERE:
        write_json(cache_dir / "latest_point_result.json", result)
    write_json(HERE / "latest_point_result.json", result)
    progress({"stage": "complete", "message": "Lowest listener noise found within the panel limit",
              "evaluated": result["search"]["evaluated_layouts"], "total": result["search"]["total_layouts"],
              "best_count": result["optimal_layout"]["object_count"], "project_url": result["project_url"]})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--legacy-area", action="store_true")
    parser.add_argument("--prefetch-cache-dir", type=Path)
    parser.add_argument("--download-workers", type=int, default=4)
    args = parser.parse_args()
    if args.prefetch_cache_dir:
        try:
            summary = prefetch_existing_fields(args.prefetch_cache_dir, args.download_workers,
                lambda event: print(json.dumps(event), flush=True))
            print(json.dumps(summary), flush=True)
        except Exception as exc:
            # HTTP exception text can contain signed URLs. Do not expose it in
            # stdout, stderr, a traceback, or a persistent progress record.
            print(json.dumps({"stage": "prefetch_failed", "error_type": type(exc).__name__,
                              "cloud_jobs_started": 0}), flush=True)
            raise SystemExit(1)
        raise SystemExit(1 if summary["failed_bases"] else 0)
    request = read_json(args.request) if args.request else get_catalog()["defaults" if args.legacy_area else "point_defaults"]
    run = run_point_optimization if "listener_m" in request else run_optimization
    print(json.dumps(run(request, lambda event: print(json.dumps(event), flush=True)), indent=2))
