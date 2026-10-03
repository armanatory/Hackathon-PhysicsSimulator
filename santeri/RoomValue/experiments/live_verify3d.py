"""Explicit live API checks, including two sources and two damped objects.

This driver runs real cloud jobs through the local website's API. It is not
part of offline unit-test discovery. Successful fields are reused on reruns.
"""
from __future__ import annotations

import copy
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .optimizer3d import HERE, read_json, write_json

API = "http://127.0.0.1:8002"
CASE = Path(__file__).resolve().parents[1]


def api(path, body=None):
    request = Request(API+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def await_job(job_id):
    last = None
    while True:
        job = api("/api/jobs/"+job_id)
        progress = job.get("progress", {})
        marker = (job["status"], progress.get("stage"), progress.get("evaluated"), progress.get("latest_simulation_id"))
        if marker != last:
            print(json.dumps({"job_id": job_id, "status": job["status"], "progress": progress}), flush=True)
            last = marker
        if job["status"] == "completed":
            return job
        if job["status"] in ("failed", "interrupted"):
            raise RuntimeError(f"Live API job {job_id} did not complete: {job['status']}")
        time.sleep(3)


def run(request):
    return await_job(api("/api/room3d/optimize", request)["job_id"])


def verify(job):
    result = job["result"]
    assert result["dimension"] == 3 and result["frequency_hz"] == 125
    assert result["project_id"] and result["mesh"]["tetrahedron_count"] > 0
    assert math.isclose(result["mesh"]["volume_m3"], 80.141415375, abs_tol=1e-6)
    state = read_json(HERE / "state.json")
    saved = {run["simulation_id"]: run for run in state["runs"].values() if run.get("status") == "SUCCESS"}
    for layout in result["evaluations"]:
        assert layout["status"] == "SUCCESS"
        assert len(layout["simulation_ids"]) == len(job["request"]["sources"])
        assert layout["object_count"] == len(layout["slot_ids"])
        for sim_id in layout["simulation_ids"]:
            assert saved[sim_id]["independent_probe_validation"] is True
        for zone in layout["zones"]:
            if "sample_rms_pa" in zone:
                assert len(zone["sample_rms_pa"]) == len(zone["sample_points_m"]) == 81
                assert zone["treated_peak_pa"] == max(zone["sample_rms_pa"])
            expected = 20*math.log10(zone["baseline_peak_pa"]/zone["treated_peak_pa"])
            assert math.isclose(expected, zone["reduction_db"], abs_tol=1e-10)
            passes = (expected >= zone["target_reduction_db"] if result["quietness_metric"] == "relative_pressure_reduction_db"
                      else zone["treated_peak_pa"] <= zone["target_pressure_pa"])
            assert zone["met_target"] == passes
        assert layout["feasible"] == all(zone["met_target"] for zone in layout["zones"])
    if result["feasible"]:
        chosen = result["optimal_layout"]
        assert chosen["feasible"]
        assert not any(layout["feasible"] and layout["object_count"] < chosen["object_count"] for layout in result["evaluations"])
        ties = [layout for layout in result["evaluations"] if layout["feasible"] and layout["object_count"] == chosen["object_count"]]
        assert chosen["selection_score"] == max(layout["selection_score"] for layout in ties)
    else:
        assert result["optimal_layout"] is None and not any(layout["feasible"] for layout in result["evaluations"])
    return {"job_id": job["job_id"], "metric": result["quietness_metric"], "feasible": result["feasible"],
            "evaluated_layouts": len(result["evaluations"]), "source_ids": [s["id"] for s in job["request"]["sources"]],
            "object_count": (result["optimal_layout"] or result["best_available_layout"])["object_count"],
            "simulation_ids": sorted({sim for layout in result["evaluations"] for sim in layout["simulation_ids"]})}


def main():
    catalog = api("/api/room3d/catalog")
    defaults = catalog["defaults"]
    initial_id = (CASE / ".runtime" / "demo3d-job.txt").read_text().strip()
    first = await_job(initial_id)
    checks = {"default_relative": verify(first)}
    assert first["result"]["feasible"] and first["result"]["optimal_layout"]["object_count"] == 1
    assert first["result"]["search"]["evaluated_layouts"] == 7
    write_json(HERE / "default_result.json", first)

    absolute = copy.deepcopy(defaults)
    absolute.update(quietness_metric="absolute_rms_pressure_pa", max_objects=0, allowed_slot_ids=[], budget_eur=0)
    job = run(absolute)
    checks["absolute_without_objects"] = verify(job)
    assert not job["result"]["feasible"]

    multiple = copy.deepcopy(defaults)
    multiple.update(sources=[{"id": "src1", "strength": 1}, {"id": "src2", "strength": .5}],
                    max_objects=0, allowed_slot_ids=[], budget_eur=0)
    for zone in multiple["quiet_zones"]:
        zone["target_reduction_db"] = 0
    job = run(multiple)
    checks["two_independent_sources"] = verify(job)
    assert job["result"]["feasible"] and job["result"]["optimal_layout"]["object_count"] == 0
    for original, combined in zip(first["result"]["evaluations"][0]["zones"], job["result"]["optimal_layout"]["zones"]):
        assert combined["baseline_peak_pa"] >= original["baseline_peak_pa"]-1e-10

    objects = copy.deepcopy(defaults)
    objects.update(max_objects=2, allowed_slot_ids=["ceiling_a", "ceiling_b"], budget_eur=240)
    for zone in objects["quiet_zones"]:
        zone["target_reduction_db"] = 30
    job = run(objects)
    checks["two_damped_objects"] = verify(job)
    assert len(job["result"]["evaluations"]) == 4
    assert any(layout["object_count"] == 2 for layout in job["result"]["evaluations"])

    restored = run(defaults)
    checks["restored_default"] = verify(restored)
    write_json(HERE / "default_result.json", restored)
    (CASE / ".runtime" / "demo3d-job.txt").write_text(restored["job_id"]+"\n")
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "passed": True,
              "website_url": "http://127.0.0.1:5175/", "browser_automation": "unavailable; API and source/build checks performed",
              "cases": checks, "project_id": restored["result"]["project_id"], "project_url": restored["result"]["project_url"]}
    write_json(HERE / "website_validation.json", report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
