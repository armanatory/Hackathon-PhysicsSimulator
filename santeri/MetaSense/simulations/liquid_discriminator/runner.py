"""Durable, bounded real Allsolve batch search. No synthetic solver fallback."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
sys.path.insert(0, str(CASE))
sys.path.insert(0, str(CASE / "backend"))

import allsolve
from allsolve_rawapi.exceptions import ApiException
from app.discriminator_models import DiscriminatorRequest
from simulations.liquid_discriminator.physics import create_experiment, create_batch
from simulations.liquid_discriminator.search import (
    generate_candidates, make_points, scalar_outputs, validate_outputs, update_candidates,
)
from simulations.liquid_discriminator.reference import reflectance_transmittance
from simulations.liquid_discriminator.mesh_guard import validate_mesh

LABEL = "allsolve_liquid_discriminator"
TERMINAL = {allsolve.Job.SUCCESS, allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.PARTIAL_SUCCESS}
FAILED = {allsolve.Job.ERROR, allsolve.Job.ABORTED}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def chunks(points, core_budget, cores_per_child):
    size = core_budget // cores_per_child
    if size < 1:
        raise ValueError("The requested core budget cannot run one solver child")
    return [points[i:i + size] for i in range(0, len(points), size)]


def indices(wavelength_nm):
    """Real Sellmeier indices; wavelength in micrometres, absorption omitted."""
    x = (wavelength_nm / 1000.0) ** 2
    sin = math.sqrt(1 + 3.0249*x/(x-.1353406**2) + 40314*x/(x-1239.842**2))
    silica = math.sqrt(1 + .6961663*x/(x-.0684043**2) + .4079426*x/(x-.1162414**2) + .8974794*x/(x-9.896161**2))
    return sin, silica


def dense_refinement_summaries(results, expected_points=None):
    """Describe saved dense evidence without changing selection or physics gates.

    Passing means at least one common wavelength has two valid cloud points. It
    does not establish the finalist's finer-mesh or independent-reference checks.
    """
    rows = [row for row in results if row.get("stage") == "dense"]
    expected = rows if expected_points is None else expected_points
    grids = {}
    for point in expected:
        key = (point["input_index"], point["wavelength_nm"])
        grids.setdefault(point["candidate_id"], set()).add(key)
    observed = {}
    for row in rows:
        key = (row["input_index"], row["wavelength_nm"])
        observed.setdefault(row["candidate_id"], {}).setdefault(key, []).append(row)
    summaries = {}
    for candidate_id, grid in sorted(grids.items()):
        values, messages = {}, set()
        for key in sorted(grid, key=lambda item: (item[1], item[0])):
            matches = observed.get(candidate_id, {}).get(key, [])
            if len(matches) != 1:
                messages.add("Missing or duplicate dense point: input %s at %.9g nm" % key)
                continue
            row = matches[0]
            reflectance = (row.get("outputs") or {}).get("reflectance")
            valid = (row.get("valid") is True and isinstance(reflectance, (int, float))
                     and not isinstance(reflectance, bool) and math.isfinite(reflectance))
            if valid:
                values[key] = reflectance
            else:
                error = row.get("error") or "Dense point did not pass its fixed cloud readout checks"
                messages.update(piece.strip() for piece in str(error).split(";") if piece.strip())
        wavelengths = sorted({wavelength for _, wavelength in grid})
        pairs = [(abs(values[(0, wavelength)] - values[(1, wavelength)]), wavelength)
                 for wavelength in wavelengths if (0, wavelength) in values and (1, wavelength) in values]
        best = max(pairs, key=lambda pair: pair[0]) if pairs else None
        summaries[candidate_id] = {
            "status": "passed" if pairs else "failed",
            "valid_points": len(values), "total_points": len(grid),
            "valid_pairs": len(pairs), "total_pairs": len(wavelengths),
            "best_valid_score": best[0] if best else None,
            "best_valid_wavelength_nm": best[1] if best else None,
            "errors": [message[:180] for message in sorted(messages)[:6]],
        }
    return summaries


def add_dense_verification(candidates, results, expected_points=None):
    summaries = dense_refinement_summaries(results, expected_points)
    for candidate in candidates:
        if candidate["id"] in summaries:
            candidate["dense_verification"] = summaries[candidate["id"]]
    return summaries


def enrich_completed_report(job_dir):
    """Back up and enrich a completed report using only its saved dense rows."""
    folder = Path(job_dir).resolve()
    path = folder / "report.json"
    original = path.read_bytes()
    report = json.loads(original)
    state = read_json(folder / "state.json")
    if (report.get("label") != LABEL or report.get("synthetic") is not False
            or report.get("status") != "completed" or state.get("phase") != "completed"):
        raise ValueError("Only a completed real cloud report can be enriched")
    expected = [point for batch in state["batches"] if batch["stage"] == "dense" for point in batch["points"]]
    summaries = add_dense_verification(report["candidates"], state["results"], expected)
    if not summaries:
        raise ValueError("The completed report has no saved dense evidence")
    backup = folder / "report.before_dense_verification.json"
    if not backup.exists():
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    atomic_json(path, report)
    return {"report_path": str(path), "backup_path": str(backup), "dense_verification": summaries}


def initial_report(request):
    return {
        "label": LABEL, "synthetic": False, "status": "queued", "stage": "Connecting to Allsolve",
        "updated_at": now(), "model": {
            "geometry": "1D rectangular Si3N4 ridges on a continuous Si3N4 film and fused silica",
            "liquids": "Explicit constant real refractive indices; no concentration inference",
            "illumination": "Normal incidence, TE electric field parallel to ridges, propagation +z",
            "materials": "Luke 2015 Si3N4 and Malitson 1965 fused-silica Sellmeier; zero absorption",
            "period_y_nm": 100, "clearance_nm": 1000,
            "method": "Allsolve harmonic Maxwell FEM, E order 2, explicit periodic multiplier order 2",
        },
        "objective": {"formula": "max_geometry,max_sampled_wavelength |R_A(lambda)-R_B(lambda)|",
            "optimized_variables": ["period_nm", "fill_factor", "ridge_height_nm"],
            "selection": "Seeded Latin hypercube candidates; paired wavelength sweep; best sampled design"},
        "progress": {"planned_solve_count": request["candidate_count"]*2*request["wavelength_samples"],
            "completed_solve_count": 0, "failed_solve_count": 0, "queued_solve_count": 0,
            "running_solve_count": 0, "planned_candidates": request["candidate_count"],
            "completed_candidates": 0, "valid_candidates": 0, "batches_completed": 0,
            "batches_total": 0, "core_budget": request["max_parallel_cores"], "effective_parallel_cores": 0},
        "candidates": generate_candidates(request), "best_design": None, "spectra": [], "batches": [], "errors": [],
    }


class Worker:
    def __init__(self, job_dir):
        self.folder = Path(job_dir).resolve()
        self.request = DiscriminatorRequest.model_validate(read_json(self.folder / "request.json")).model_dump()
        self.source_path = self.folder / "source_readout.py"
        if not self.source_path.exists():
            self.source_path.write_text((HERE / "source_readout.py").read_text(encoding="utf-8"), encoding="utf-8")
        self.report = read_json(self.folder / "report.json") if (self.folder / "report.json").exists() else initial_report(self.request)
        self.state = read_json(self.folder / "state.json") if (self.folder / "state.json").exists() else {
            "source_sha256": hashlib.sha256(self.source_path.read_text(encoding="utf-8").encode()).hexdigest(),
            "request_sha256": hashlib.sha256(json.dumps(self.request, sort_keys=True).encode()).hexdigest(),
            "batches": [], "results": [], "phase": "search"}
        digest = hashlib.sha256(self.source_path.read_text(encoding="utf-8").encode()).hexdigest()
        if digest != self.state["source_sha256"]:
            raise RuntimeError("The source changed since this job was created; preserve its evidence and start a new job")
        request_digest = hashlib.sha256(json.dumps(self.request, sort_keys=True).encode()).hexdigest()
        if request_digest != self.state["request_sha256"]:
            raise RuntimeError("The saved request changed; preserve this job and start a new one")
        self.active_statuses = []
        self.publish()
        cache = self.folder / "sdk-cache"
        cache.mkdir(exist_ok=True)
        # Backend passes credentials in inherited environment. Standalone CLI uses root .env.
        kwargs = {} if os.environ.get("ALLSOLVE_ACCESS_KEY") and os.environ.get("ALLSOLVE_SECRET_KEY") else {"dotenv_file": str(CASE.parent / ".env")}
        self.client = allsolve.Client(cache_base_dir=str(cache), **kwargs)
        if self.state.get("project_id"):
            self.project = self.client.get_project(self.state["project_id"])
        else:
            self.report.update(status="running", stage="Building the periodic unit cell")
            self.publish()
            self.project, metadata = create_experiment(self.client, self.request, self.source_path)
            self.state.update(metadata)
            self.state["project_id"] = self.project.id
            self.state["project_url"] = self.client.get_url(self.project)
            self.publish()

    def publish(self):
        progress = self.report["progress"]
        results = self.state["results"]
        progress.update(
            completed_solve_count=sum(bool(r.get("outputs")) for r in results),
            failed_solve_count=sum(r.get("status") == "failed" for r in results),
            queued_solve_count=sum(s in {allsolve.Job.QUEUED, allsolve.Job.SUBMITTED, None} for s in self.active_statuses),
            running_solve_count=sum(s not in TERMINAL and s not in {allsolve.Job.QUEUED, allsolve.Job.SUBMITTED, None} for s in self.active_statuses),
            completed_candidates=sum(c["status"] in {"completed", "invalid", "failed"} for c in self.report["candidates"]),
            valid_candidates=sum(c.get("valid", False) for c in self.report["candidates"]),
            batches_completed=sum(b.get("status") in {"completed", "failed"} for b in self.state["batches"]),
            batches_total=len(self.state["batches"]),
        )
        self.report["batches"] = [{k:v for k,v in b.items() if k not in {"points"}} for b in self.state["batches"]]
        self.report["updated_at"] = now()
        atomic_json(self.folder / "state.json", self.state)
        atomic_json(self.folder / "report.json", self.report)

    def capacity(self, required):
        while True:
            quota = allsolve.get_quota()
            free = quota.max_concurrent_cores - quota.total_running_cores - quota.total_reserved_cores
            # Allsolve schedules queued children against the shared organization quota.
            # Wait for one child, rather than requiring the whole batch to fit at once.
            if free >= min(required, 4):
                return
            self.report["stage"] = f"Waiting for Allsolve capacity ({free} cores available)"
            self.publish()
            time.sleep(10)

    def append_batch(self, points, stage, clearance_nm, write_fields):
        cores = 3 if stage in {"search", "dense"} else 4
        name = f"{stage} {1+sum(b['stage']==stage for b in self.state['batches'])}"
        instance, simulation, metadata = create_batch(
            self.project, self.request, points,
            stage="coarse" if cores == 3 else "fine", clearance_nm=clearance_nm, write_fields=write_fields, source_path=self.source_path,
        )
        record = dict(metadata, name=name, stage=stage, project_id=self.project.id,
            project_url=self.state["project_url"], point_count=len(points), points=points,
            cores_per_child=cores, status="configured", clearance_nm=clearance_nm,
            write_fields=write_fields, mesh_job_id=None, simulation_job_id=None)
        self.state["batches"].append(record)
        # Save IDs before submitting any cloud job. Finished batches are never restarted.
        self.publish()
        self.run_batch(record, instance, simulation)

    def batch_objects(self, batch):
        mesh = next(m for m in self.project.get_meshes() if m.id == batch["mesh_id"])
        instance = mesh.get_override(batch["sweep_id"])
        simulation = next(s for s in self.project.get_simulations() if s.id == batch["simulation_id"])
        return instance, simulation

    def audit_mesh(self, batch, instance):
        if batch.get("mesh_geometry_verified"):
            return
        instance.refresh()
        folder=self.folder / "batches" / batch["name"].replace(" ", "_") / "meshes"
        folder.mkdir(parents=True,exist_ok=True)
        guards=[]
        for mesh_file in instance._raw_instance.files or []:
            overrides={o.name:float(o.value) for o in mesh_file.overrides}
            required={"period_x":"period_nm","fill_factor":"fill_factor","ridge_height":"ridge_height_nm"}
            if not all(name in overrides for name in required):
                raise RuntimeError("Mesh geometry override metadata is incomplete")
            candidates=[p for p in batch["points"] if all(math.isclose(overrides[name]*(1 if name=="fill_factor" else 1e9),p[key],rel_tol=1e-8,abs_tol=1e-6) for name,key in required.items())]
            if not candidates:
                raise RuntimeError("A physical mesh does not match any submitted geometry")
            point=candidates[0]
            path=folder / (mesh_file.id + ".msh")
            if not path.exists():
                instance.save_mesh_file(output_dir=str(folder),filename=path.name,sweep_index=mesh_file.index)
            guard=validate_mesh(path,point,batch["clearance_nm"])
            guard.update(mesh_file_id=mesh_file.id,mesh_file_index=mesh_file.index,candidate_id=point["candidate_id"],overrides=overrides)
            atomic_json(folder / (mesh_file.id + ".json"),guard)
            guards.append(guard)
        batch["mesh_guards"]=guards
        batch["mesh_geometry_verified"]=bool(guards) and all(g["passed"] for g in guards)
        self.publish()
        if not batch["mesh_geometry_verified"]:
            raise RuntimeError("Downloaded mesh dimensions differ from the submitted geometry; no solve is accepted")

    def collect(self, batch, simulation, terminal):
        try:
            data = simulation.get_output_data(refresh=True)
            rows = data._get_simulations_sorted()
        except (ValueError, FileNotFoundError, ApiException) as exc:
            if isinstance(exc, ApiException) and exc.status != 404:
                raise
            if terminal:
                rows = []
            else:
                return
        child_jobs = [allsolve.Job(self.project.id, row.job_id) for row in rows]
        if child_jobs:
            allsolve.Job.refresh_statuses(child_jobs, delay_s=0)
        self.active_statuses = [j.get_status() for j in child_jobs]
        existing = {(r["batch_name"],r["sweep_index"]):r for r in self.state["results"]}
        for row_position, (row, job) in enumerate(zip(rows, child_jobs)):
            key = (batch["name"], row.job_index)
            if key in existing and (not terminal or existing[key].get("valid")):
                continue
            if row.job_index < 0 or row.job_index >= len(batch["points"]):
                raise RuntimeError("Cloud sweep index does not match the saved point table")
            point = batch["points"][row.job_index]
            status = job.get_status()
            if status not in TERMINAL and not terminal:
                continue
            output = {}
            errors = []
            if status not in FAILED:
                try:
                    # SDK to_dict indexes the sorted available-row list, which can be
                    # sparse during publication; job_index identifies the submitted point.
                    output = scalar_outputs(data.to_dict(row_position))
                    errors = validate_outputs(output)
                    errors += self.match_point(point, output)
                except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                    errors = [f"Invalid or missing cloud scalar outputs: {type(exc).__name__}"]
            else:
                errors = ["Allsolve child failed; inspect its saved private logs"]
            if status != allsolve.Job.SUCCESS:
                errors.append("Cloud child did not finish successfully")
            # A successful child's values can lag its status in the sweep database.
            # Do not commit an empty snapshot while the parent is still assembling it.
            if errors and status == allsolve.Job.SUCCESS and not terminal:
                continue
            result = dict(point, outputs=output, valid=bool(output) and not errors,
                error="; ".join(errors) if errors else None, status="failed" if not output else "completed",
                batch_name=batch["name"], stage=batch["stage"], sweep_index=row.job_index, cloud_job_id=row.job_id)
            folder = self.folder / "batches" / batch["name"].replace(" ", "_")
            if key in existing:
                previous = existing[key]
                atomic_json(folder / f"point_{row.job_index}_earlier_collection.json", previous)
                self.state["results"].remove(previous)
            self.state["results"].append(result)
            atomic_json(folder / f"point_{row.job_index}.json", result)
            if errors:
                try:
                    events = job._get_logs(limit=1000)
                    atomic_json(folder / f"point_{row.job_index}_private_logs.json",
                        {"job_id":row.job_id,"events":[e.model_dump(mode="json") for e in events]})
                except Exception:
                    traceback.print_exc()
        if terminal:
            existing = {(r["batch_name"],r["sweep_index"]) for r in self.state["results"]}
            for i, point in enumerate(batch["points"]):
                if (batch["name"],i) not in existing:
                    self.state["results"].append(dict(point, outputs={}, valid=False, error="Cloud output is missing",
                        status="failed",batch_name=batch["name"],stage=batch["stage"],sweep_index=i))
        self.update_search()
        self.publish()

    @staticmethod
    def match_point(point, output):
        errors = []
        for key in ("candidate_id", "input_index", "wavelength_nm", "n_liquid", "period_nm", "fill_factor", "ridge_height_nm", "film_thickness_nm"):
            if key not in output or not math.isclose(output[key], point[key], rel_tol=1e-8, abs_tol=1e-8):
                errors.append("Submitted/output metadata mismatch: " + key)
        return errors

    def run_batch(self, batch, instance=None, simulation=None):
        if batch["status"] == "failed":
            return
        if batch["status"] == "completed":
            if not batch.get("mesh_geometry_verified"):
                if instance is None:
                    instance, simulation = self.batch_objects(batch)
                self.audit_mesh(batch,instance)
            incomplete = any(r["batch_name"]==batch["name"] and not r.get("valid") for r in self.state["results"])
            if incomplete:
                if simulation is None:
                    instance, simulation = self.batch_objects(batch)
                self.collect(batch, simulation, terminal=True)
            return
        if instance is None:
            instance, simulation = self.batch_objects(batch)
        self.report["stage"] = "Meshing " + batch["name"]
        self.report["progress"]["effective_parallel_cores"] = len(batch["points"]) * batch["cores_per_child"]
        self.publish()
        mesh_job = instance._job
        if mesh_job is None:
            self.capacity(len(batch["points"]) * batch["cores_per_child"])
            instance.start()
            mesh_job = instance._job
            batch.update(status="meshing", mesh_job_id=getattr(mesh_job,"id",None))
            self.publish()
        while mesh_job.refresh_status(delay_s=0) not in TERMINAL:
            self.publish()
            time.sleep(5)
        if mesh_job.get_status() != allsolve.Job.SUCCESS:
            batch["status"] = "failed"
            self.publish()
            raise RuntimeError(f"Allsolve mesh failed for {batch['name']}; project and mesh IDs retained")
        instance.refresh()
        batch["mesh_count"] = instance.get_sweep_count()
        self.report["stage"] = "Checking mesh dimensions for " + batch["name"]
        self.publish()
        self.audit_mesh(batch,instance)
        self.report["stage"] = "Solving " + batch["name"]
        job = simulation._get_job()
        if job is None:
            self.capacity(len(batch["points"]) * batch["cores_per_child"])
            simulation.start()
            job = simulation._get_job()
            batch.update(status="running", simulation_job_id=job.id)
            self.publish()
        while True:
            status = job.refresh_status(delay_s=0)
            batch["cloud_status"] = status
            self.collect(batch, simulation, terminal=status in TERMINAL)
            if status in TERMINAL:
                break
            time.sleep(5)
        batch["status"] = "completed" if status == allsolve.Job.SUCCESS else "failed"
        self.active_statuses = []
        self.publish()
        if status != allsolve.Job.SUCCESS:
            raise RuntimeError(f"Allsolve simulation failed for {batch['name']}; saved outputs and cloud IDs retained")

    def run_points(self, points, stage, clearance_nm=1000, write_fields=False):
        # On resume complete saved unfinished batches first, then submit only missing points.
        relevant = [b for b in self.state["batches"] if b["stage"] == stage]
        for batch in relevant:
            self.run_batch(batch)
        scheduled = {(p["candidate_id"],p["input_index"],p["wavelength_nm"]) for b in relevant for p in b["points"]}
        remaining = [p for p in points if (p["candidate_id"],p["input_index"],p["wavelength_nm"]) not in scheduled]
        cores = 3 if stage in {"search", "dense"} else 4
        plans = self.state.setdefault("stage_plans", {})
        plans[stage] = len(points)
        self.report["progress"]["planned_solve_count"] = self.request["candidate_count"]*2*self.request["wavelength_samples"] + sum(count for key,count in plans.items() if key != "search")
        self.publish()
        for point_chunk in chunks(remaining, self.request["max_parallel_cores"], cores):
            self.append_batch(point_chunk, stage, clearance_nm, write_fields)
        return [r for r in self.state["results"] if r["stage"] == stage]

    def spectra(self, candidate_id):
        spectra = []
        for stage in ("search", "dense", "fine", "clearance"):
            for i, liquid in enumerate(self.request["liquids"]):
                rows = [r for r in self.state["results"] if r["candidate_id"]==candidate_id and r["input_index"]==i and r["stage"]==stage and r["outputs"]]
                if rows:
                    spectra.append({"candidate_id":candidate_id,"input_label":liquid["label"],"n":liquid["n"],
                        "stage":stage,"mesh_resolution_per_wavelength":12 if stage in {"search","dense"} else 18,
                        "points":[{"wavelength_nm":r["wavelength_nm"],"R":r["outputs"]["reflectance"],
                            "T":r["outputs"]["transmittance"],"energy_residual":r["outputs"]["energy_residual"],"valid":r["valid"]}
                            for r in sorted(rows,key=lambda r:r["wavelength_nm"])]})
        return spectra

    def update_search(self):
        rows = [r for r in self.state["results"] if r["stage"] == "search"]
        update_candidates(self.report["candidates"], self.request, rows)
        eligible = [c for c in self.report["candidates"] if c["valid"] and c["score"] is not None]
        if eligible and self.report["status"] == "running" and not (self.report.get("best_design") or {}).get("validated", False):
            best = max(eligible,key=lambda c:c["score"])
            self.report["best_design"] = {"candidate_id":best["id"],"geometry":best["geometry"],"score":best["score"],
                "wavelength_nm":best["wavelength_nm"],"R_A":best["R_A"],"R_B":best["R_B"],"validated":False}
            self.report["spectra"] = self.spectra(best["id"])

    def run(self):
        if self.report["status"] == "completed":
            return
        self.report.update(status="running",stage="Sampling the fabrication bounds")
        self.publish()
        self.run_points(make_points(self.report["candidates"], self.request), "search")
        eligible = sorted([c for c in self.report["candidates"] if c["valid"]],key=lambda c:c["score"],reverse=True)
        if not eligible:
            raise RuntimeError("No complete candidate spectrum passed the fixed physics checks")
        self.report.update(status="verifying",stage="Resolving the best sampled spectral contrast")
        self.publish()
        step = (self.request["wavelength_max_nm"]-self.request["wavelength_min_nm"])/(self.request["wavelength_samples"]-1)
        dense_candidates = []
        dense_points = []
        for c in eligible[:2]:
            lo=max(self.request["wavelength_min_nm"],c["wavelength_nm"]-step)
            hi=min(self.request["wavelength_max_nm"],c["wavelength_nm"]+step)
            wavelengths=[lo+(hi-lo)*i/20 for i in range(21)]
            dense_candidates.append((c, wavelengths))
            dense_points += make_points([c], self.request, wavelengths=wavelengths)
        dense = self.run_points(dense_points,"dense")
        add_dense_verification(self.report["candidates"], dense, dense_points)
        self.publish()
        choices=[]
        for c, wavelengths in dense_candidates:
            for wavelength in wavelengths:
                pair=[next((r for r in dense if r["candidate_id"]==c["id"] and r["input_index"]==i and math.isclose(r["wavelength_nm"],wavelength,abs_tol=1e-8)),None) for i in (0,1)]
                if all(r is not None and r["valid"] for r in pair):
                    choices.append((abs(pair[0]["outputs"]["reflectance"]-pair[1]["outputs"]["reflectance"]),c,wavelength,pair))
        if not choices:
            raise RuntimeError("No paired dense readout passed the fixed physics checks")
        score, candidate, wavelength, coarse_pair = max(choices,key=lambda item:item[0])
        self.report["best_design"] = {"candidate_id":candidate["id"],"geometry":candidate["geometry"],"score":score,
            "wavelength_nm":wavelength,"R_A":coarse_pair[0]["outputs"]["reflectance"],"R_B":coarse_pair[1]["outputs"]["reflectance"],"validated":False}
        self.report["spectra"] = self.spectra(candidate["id"])
        self.publish()
        points = make_points([candidate], self.request,wavelengths=[wavelength])
        fine=self.run_points(points,"fine",write_fields=True)
        clearance=self.run_points(points,"clearance",clearance_nm=1500)
        fine=sorted(fine,key=lambda r:r["input_index"])
        clearance=sorted(clearance,key=lambda r:r["input_index"])
        if len(fine)!=2 or len(clearance)!=2 or not all(r["valid"] for r in fine+clearance):
            raise RuntimeError("The finalist failed the fine-mesh or clearance readout checks")
        fine_R=[r["outputs"]["reflectance"] for r in fine]
        coarse_R=[r["outputs"]["reflectance"] for r in coarse_pair]
        clearance_R=[r["outputs"]["reflectance"] for r in clearance]
        n_sin,n_substrate=indices(wavelength)
        reference=[]
        reference_convergence=[]
        g=candidate["geometry"]
        for liquid in self.request["liquids"]:
            kwargs={k:g[k] for k in ("period_nm","fill_factor","ridge_height_nm","film_thickness_nm")}
            kwargs.update(wavelength_nm=wavelength,n_liquid=liquid["n"],n_sin=n_sin,n_substrate=n_substrate)
            r9=reflectance_transmittance(**kwargs,orders=9)
            r13=reflectance_transmittance(**kwargs,orders=13)
            reference.append(r13["R0"])
            reference_convergence.append(abs(r9["R0"]-r13["R0"]))
        fine_score=abs(fine_R[0]-fine_R[1])
        checks={
            "readout_checks":True,
            "mesh_max_R_change":max(abs(a-b) for a,b in zip(fine_R,coarse_R)),
            "mesh_contrast_change":abs(fine_score-score),
            "clearance_max_R_change":max(abs(a-b) for a,b in zip(fine_R,clearance_R)),
            "RCWA_max_R_error":max(abs(a-b) for a,b in zip(fine_R,reference)),
            "RCWA_order_convergence":max(reference_convergence),
            "RCWA_R":reference,"coarse_R":coarse_R,"fine_R":fine_R,"clearance_R":clearance_R,
            "limits":{"mesh_max_R_change":.01,"mesh_contrast_change":.01,"clearance_max_R_change":.005,"RCWA_max_R_error":.015,"RCWA_order_convergence":.002},
        }
        checks["passed"]=all(checks[key]<=limit for key,limit in checks["limits"].items())
        checks["checks"]={key:checks[key]<=limit for key,limit in checks["limits"].items()}
        checks["checks"]["readout_checks"]=True
        checks["checks"]["mesh_dimensions"]=all(b.get("mesh_geometry_verified") is True for b in self.state["batches"])
        checks["passed"]=checks["passed"] and checks["checks"]["mesh_dimensions"]
        self.report["best_design"]={"candidate_id":candidate["id"],"geometry":candidate["geometry"],"wavelength_nm":wavelength,
            "score":fine_score,"R_A":fine_R[0],"R_B":fine_R[1],"validated":checks["passed"],"verification":checks}
        self.report["spectra"]=self.spectra(candidate["id"])
        candidate["verified"]=checks["passed"]
        self.report["progress"]["effective_parallel_cores"]=0
        if not checks["passed"]:
            self.publish()
            raise RuntimeError("The finalist did not meet the fixed mesh, clearance, or independent-reference tolerance")
        self.report.update(status="completed",stage="Verified best sampled design")
        self.state["phase"]="completed"
        self.publish()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["run"])
    parser.add_argument("--job-dir",required=True,type=Path)
    args=parser.parse_args()
    worker=None
    try:
        worker=Worker(args.job_dir)
        worker.run()
    except Exception:
        traceback.print_exc()
        if worker is not None:
            # Detailed exception/logs remain private; public errors contain no SDK credentials.
            worker.report.update(status="failed",stage="Optimization failed")
            worker.active_statuses=[]
            worker.report["progress"]["effective_parallel_cores"]=0
            worker.report["errors"].append("A cloud job or a fixed physics check failed. Saved results and cloud IDs are retained.")
            worker.publish()
        else:
            path=args.job_dir / "report.json"
            report=read_json(path) if path.exists() else {"label":LABEL,"synthetic":False}
            report.update(status="failed",stage="Initialization failed",updated_at=now(),errors=["The Allsolve worker could not initialize. See its private log."])
            atomic_json(path,report)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
