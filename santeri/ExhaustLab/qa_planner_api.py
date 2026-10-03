"""Exercise the running planner's physical source and constraint semantics."""
from __future__ import annotations

import argparse
import copy
import json
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8003"


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-cloud", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    config = request("/api/planner/config")
    inputs = config["defaults"]
    result = request("/api/planner/solve", inputs)
    assert result["status"] == "feasible" and result["recommended"] is not None
    assert result["summary"]["evaluated"] == 81
    selected = result["recommended"]
    assert selected["feasible"] and not selected["violations"]
    assert selected["worst_loaded_backpressure_kpa"] >= selected["worst_clean_backpressure_kpa"] > 0
    assert selected["specified_capture_pct"] == inputs["material"]["spec_capture_pct"]
    assert len(selected["duty_results"]) == len(inputs["duty_cycle"])
    assert all(row["pipe_velocity_m_s"] > 0 and row["gas_density_kg_m3"] > 0 for row in selected["duty_results"])
    if args.require_cloud:
        assert config["cloud_study"]["trusted"] is True
        assert result["mode"] == "allsolve_verified_screening"
        assert selected["source"]["mode"] == "allsolve_pressure_verified"
        assert len(config["cloud_study"]["cases"]) >= 9

    for name, changes, expected in [
        ("budget", {"constraints": {"budget_eur": 0}}, "budget"),
        ("packaging", {"constraints": {"max_outer_diameter_mm": 80}}, "outer_diameter"),
        ("capture", {"material": {"spec_capture_pct": 80}}, "capture_specification"),
        ("pressure", {"constraints": {"max_backpressure_kpa": 0.01}}, "backpressure"),
    ]:
        outcome = request("/api/planner/solve", changes)
        assert outcome["status"] == "infeasible" and outcome["recommended"] is None, name
        assert expected in {row["constraint"] for row in outcome["constraint_failures"]}, name

    impossible_thermal = copy.deepcopy(inputs)
    impossible_thermal["constraints"]["min_hot_time_fraction"] = 0.5
    for point in impossible_thermal["duty_cycle"]:
        point["inlet_temp_c"] = 20
    thermal = request("/api/planner/solve", impossible_thermal)
    assert thermal["status"] == "infeasible" and thermal["recommended"] is None
    assert "hot_time_screen" in {row["constraint"] for row in thermal["constraint_failures"]}

    for invalid in ({"duty_cycle": []}, {"environment": {"pressure_kpa": -1}}, {"unknown": 1},
                    {"material": {"effective_permeability_m2": float("inf")}}):
        try:
            request("/api/planner/solve", invalid)
            raise AssertionError("Invalid request was accepted")
        except urllib.error.HTTPError as error:
            assert error.code == 400

    if args.require_cloud:
        unsupported = request("/api/planner/solve", {"search": {"diameters_mm": [130]}})
        assert unsupported["status"] == "infeasible" and unsupported["recommended"] is None
        assert "cloud_geometry_not_verified" in {row["constraint"] for row in unsupported["constraint_failures"]}

    health = request("/api/health")
    assert health["planner_version"] == 1 and health["cloud_jobs_launched"] is False
    print(json.dumps({"passed": True, "mode": result["mode"], "seconds": round(time.monotonic()-started, 2),
        "design": selected["id"], "cost_eur": selected["cost_eur"],
        "loaded_backpressure_kpa": selected["worst_loaded_backpressure_kpa"],
        "evaluated": result["summary"]["evaluated"], "feasible": result["summary"]["feasible"]}, indent=2))


if __name__ == "__main__":
    main()
