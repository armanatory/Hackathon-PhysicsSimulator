"""Explicit real-cloud checks for the panel-cap / listener-dB website mode."""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone

from .live_verify3d import api, await_job
from .optimizer3d import HERE, point_catalog, get_catalog, read_json, write_json


def run(request):
    return await_job(api("/api/room3d/minimize", request)["job_id"])


def verify(job):
    result = job["result"]
    assert result["objective"] == "minimize_listener_noise"
    assert result["noise_metric"] == "normalized_spl_db" and result["frequency_hz"] == 125
    assert result["mesh"]["dimension"] == 3
    assert math.isclose(result["mesh"]["volume_m3"], 80.141415375, abs_tol=1e-6)
    _, cache = point_catalog(job["request"], get_catalog())
    state = read_json(cache / "state.json")
    saved = {basis["simulation_id"]: basis for basis in state["runs"].values() if basis.get("status") == "SUCCESS"}
    layouts = result["evaluations"]
    expected_count = sum(math.comb(len(job["request"]["allowed_slot_ids"]), count)
                         for count in range(min(job["request"]["max_panels"], len(job["request"]["allowed_slot_ids"]))+1))
    assert len(layouts) == result["search"]["total_layouts"] == expected_count
    for layout in layouts:
        assert layout["status"] == "SUCCESS" and layout["object_count"] <= job["request"]["max_panels"]
        assert len(layout["simulation_ids"]) == len(job["request"]["sources"])
        for sim_id in layout["simulation_ids"]:
            assert saved[sim_id]["independent_probe_validation"] is True
        assert math.isclose(layout["noise_db"], 20*math.log10(layout["pressure_rms_pa"]/20e-6), abs_tol=1e-10)
        assert math.isclose(layout["reduction_db"], result["baseline"]["noise_db"]-layout["noise_db"], abs_tol=1e-10)
    assert result["optimal_layout"] == min(layouts, key=lambda item: (item["pressure_rms_pa"], item["object_count"]))
    return {"job_id": job["job_id"], "project_id": result["project_id"], "project_url": result["project_url"],
            "model_sha256": result["model_sha256"], "source_geometry": result["source_geometry"],
            "sources": result["sources"], "listener_m": result["listener_m"], "mesh": result["mesh"],
            "layouts": len(layouts), "baseline_db": result["baseline"]["noise_db"],
            "optimal_layout": result["optimal_layout"]}


def main():
    catalog = api("/api/room3d/catalog")
    defaults = catalog["point_defaults"]
    default_job = run(defaults)
    checks = {"default_one_panel_cap": verify(default_job)}
    write_json(HERE / "default_point_result.json", default_job)

    moved = copy.deepcopy(defaults)
    moved["sources"][0]["position_m"][0] += .2
    moved.update(max_panels=0, allowed_slot_ids=[])
    moved_job = run(moved)
    checks["moved_source_new_geometry"] = verify(moved_job)
    assert moved_job["result"]["project_id"] != default_job["result"]["project_id"]

    quieter = copy.deepcopy(moved)
    quieter["sources"][0]["level_db"] -= 10
    quiet_job = run(quieter)
    checks["source_level_reuses_field"] = verify(quiet_job)
    assert quiet_job["result"]["optimal_layout"]["simulation_ids"] == moved_job["result"]["optimal_layout"]["simulation_ids"]
    assert math.isclose(quiet_job["result"]["optimal_layout"]["noise_db"], moved_job["result"]["optimal_layout"]["noise_db"]-10, abs_tol=1e-9)

    listener = copy.deepcopy(moved)
    listener["listener_m"][0] += .3
    listener_job = run(listener)
    checks["listener_position_reuses_full_field"] = verify(listener_job)
    assert listener_job["result"]["optimal_layout"]["simulation_ids"] == moved_job["result"]["optimal_layout"]["simulation_ids"]

    multiple = copy.deepcopy(defaults)
    source2 = catalog["sources"][1]
    multiple.update(max_panels=0, allowed_slot_ids=[])
    multiple["sources"].append({"id": source2["id"], "position_m": source2["position_m"], "level_db": 84.9485002168})
    multi_job = run(multiple)
    checks["two_independent_sources"] = verify(multi_job)
    assert multi_job["result"]["baseline"]["pressure_rms_pa"] >= default_job["result"]["baseline"]["pressure_rms_pa"]

    two = copy.deepcopy(defaults)
    two.update(max_panels=2, allowed_slot_ids=["ceiling_a", "ceiling_b"])
    two_job = run(two)
    checks["two_panel_cap_all_subsets"] = verify(two_job)
    assert len(two_job["result"]["evaluations"]) == 4

    restored = run(defaults)
    checks["restored_default"] = verify(restored)
    write_json(HERE / "default_point_result.json", restored)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "passed": True,
              "website_url": "http://127.0.0.1:5175/", "cases": checks}
    write_json(HERE / "point_website_validation.json", report)
    print(f"PASS: {len(checks)} real-cloud point planner checks", flush=True)


if __name__ == "__main__":
    main()
