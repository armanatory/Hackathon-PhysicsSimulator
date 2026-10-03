"""Local ExhaustLab planner and legacy pilot API; cloud credentials stay outside it."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from analyze_study import extract_case, read_json, require_field_validation
from particles import ParticleModel, RegularGridFieldSampler, flux_weighted_inlet, integrate_trajectories

BASE = Path(__file__).resolve().parent
CASE_FOLDERS = {"gap4": "gap4", "gap6": "gap6", "gap8": "gap8"}
ASSUMPTIONS = [
    "Cold, conditioned side-stream pilot: 0.2 L/min through one 60 × 20 mm straight plate channel. Gas density 1.2 kg/m³; viscosity 1.81×10⁻⁵ Pa·s.",
    "Allsolve computes the 3D incompressible velocity, pressure, potential and electric field. Particle paths are local postprocessing of exported fields.",
    "Fully developed straight-channel flow. The verified explicit stationary weak form omits advection, which vanishes for the reference developed profile. End effects are checked against that profile.",
    "Precharged dilute spherical particles with entered diameter and fixed positive charge; Stokes drag with Cunningham slip. All lateral walls perfectly capture particle centers.",
    "No charging/corona, Brownian diffusion, gravity, deposition feedback, resuspension, hot exhaust, turbulence, combustion chemistry or CO₂/NOx removal.",
    "Voltage changes linearly rescale the verified 200 V electrostatic field, valid for this constant-permittivity model with no space charge. Airflow is held fixed.",
    "Costs and electrical supply power are entered by you. The pressure × flow value is ideal hydraulic power, not measured fan or supply consumption.",
    "Capture is a conditional modeled single-pass outcome. Unresolved trajectories remain in the denominator. This is not measured or certified source-emission reduction.",
]
CONDITIONS = {"flow_l_min": .2, "length_mm": 60, "span_mm": 20,
              "temperature_model": "fixed-property cold pilot gas", "charge_e": 30, "diameter_um": 1, "voltage_v": 200}
LOCK = threading.Lock()
CACHE = {}


def planner_config():
    """Expose editable inputs and provenance, never cloud credentials."""
    from planner import get_defaults, get_default_sources, load_cloud_dataset
    dataset = load_cloud_dataset()
    return {
        "defaults": get_defaults(),
        "default_sources": get_default_sources(),
        "model_label": "Small stationary diesel engine · installation screening",
        "cloud_study": dataset,
        "assumptions": [
            "The search chooses the best feasible design from the displayed finite candidate grid under the selected objective.",
            "Filter capture is an entered supplier rating, not predicted pore-scale filtration.",
            "Bulk permeability, loaded resistance, material properties and costs are editable. Demonstration inputs require calibration before engineering use.",
            "The porous cartridge is an equivalent bulk pressure model. Temperature retention does not predict soot oxidation or regeneration completion.",
        ],
    }


def solve_planner(body):
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    from planner import plan_design, load_cloud_dataset
    return plan_design(body, cloud_dataset=load_cloud_dataset())


def optional_number(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1e9:
        raise ValueError(f"{label} must be a finite nonnegative number or null")
    return float(value)


def parameter(value, label, low, high):
    number = optional_number(value, label)
    if number is None or not low <= number <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return number


def sources(case):
    folder = BASE / "runs" / CASE_FOLDERS[case]
    fine = BASE / "runs" / (case + "fine")
    if (fine / "validation.json").exists() and read_json(fine / "validation.json").get("passed") is True:
        folder = fine
    paths = [folder / name for name in ("state.json", "flow_samples.json", "electric_samples.json")]
    blobs = [path.read_bytes() for path in paths]
    hashes = {path.name: hashlib.sha256(blob).hexdigest() for path, blob in zip(paths, blobs)}
    state, flow, electric = [json.loads(blob) for blob in blobs]
    validation = read_json(folder / "validation.json")
    require_field_validation(validation, state, hashes)
    channel, sampler, pressure, potential, provenance = extract_case(state, flow, electric)
    return state, channel, sampler, validation, provenance, tuple(hashes.values())


def compute_case(case, charge, diameter, voltage):
    state, channel, base_sampler, validation, provenance, hashes = sources(case)
    key = (case, hashes, charge, diameter, voltage)
    with LOCK:
        cached = CACHE.get(key)
    if cached is not None:
        return {**cached, "validation": validation}
    sampler = RegularGridFieldSampler(*base_sampler.axes_m, base_sampler.velocity_m_s,
                                     base_sampler.electric_v_m * voltage / state["voltage_v"], provenance=provenance)
    inlet = flux_weighted_inlet(sampler, channel, n_y=48, n_z=32)
    indices = tuple(np.linspace(0, len(inlet.points_m)-1, 24, dtype=int).tolist())
    particle = ParticleModel(diameter_m=diameter*1e-6, charge_e=charge, gas_viscosity_pa_s=state["mu_pa_s"])
    result = integrate_trajectories(sampler, channel, particle, inlet, max_step_s=.01,
                                    max_time_s=30, track_indices=indices, path_stride=5)
    summary = result.summary()
    # The simulated pressure penalty is the area-averaged inlet/outlet pressure;
    # validation also supplies the fitted developed gradient as a benchmark.
    flow_validation = validation["flow"]
    pressure_drop = flow_validation["surface_mean_pressure_drop_pa"]
    if pressure_drop < 0:
        raise ValueError("Simulated pressure penalty is negative; study requires review")
    item = {"case": case, "gap_mm": channel.gap_m*1000,
            "capture_fraction": summary["captured_fraction"], "outlet_fraction": summary["outlet_fraction"],
            "unresolved_fraction": summary["unresolved_fraction"], "capture_upper_bound": summary["capture_upper_bound"],
            "captured_by_wall": summary["captured_by_wall"], "pressure_drop_pa": pressure_drop,
            "developed_pressure_drop_pa": flow_validation["developed_pressure_drop_pa"],
            "air_power_w": pressure_drop*state["flow_m3_s"], "validation": validation, "provenance": provenance,
            "paths": [{"seed_index": i, "state": str(result.states[i]), "points": path.tolist()}
                      for i, path in result.paths.items()],
            "integration": {"seeds": len(inlet.points_m), "max_step_s": .01, "max_time_s": 30}}
    with LOCK:
        if len(CACHE) > 40:
            CACHE.clear()
        CACHE[key] = item
    return dict(item)


def evaluate(body):
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    charge = parameter(body.get("charge_e", 30), "charge_e", 0, 60)
    diameter = parameter(body.get("diameter_um", 1), "diameter_um", .5, 2)
    voltage = parameter(body.get("voltage_v", 200), "voltage_v", 0, 200)
    costs = body.get("costs", {})
    if not isinstance(costs, dict):
        raise ValueError("costs must be an object")
    budget = optional_number(body.get("budget_eur"), "budget_eur")
    supply = optional_number(body.get("supply_power_w"), "supply_power_w")
    power_budget = optional_number(body.get("power_budget_w"), "power_budget_w")
    cases = []
    for case in CASE_FOLDERS:
        item = compute_case(case, charge, diameter, voltage)
        cost = optional_number(costs.get(case), f"costs.{case}")
        total = supply + item["air_power_w"] if supply is not None else None
        checks = []
        if budget is not None and cost is not None:
            checks.append(cost <= budget)
        if power_budget is not None and total is not None:
            checks.append(total <= power_budget)
        missing = (budget is None or cost is None or power_budget is None or total is None)
        eligible = False if False in checks else None if missing else True
        item.update(entered_cost_eur=cost, total_entered_power_w=total, within_budget=eligible)
        cases.append(item)
    return {"cases": cases, "conditions": CONDITIONS, "parameters": {"charge_e": charge, "diameter_um": diameter, "voltage_v": voltage},
            "assumptions": ASSUMPTIONS, "source": "Recorded and validated Allsolve cloud fields; local particle evaluation"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, value):
        data = json.dumps(value, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5176")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_json(200, {})

    def do_GET(self):
        if self.path == "/api/health":
            return self.send_json(200, {"status": "ok", "cloud_jobs_launched": False, "planner_version": 1})
        if self.path == "/api/planner/config":
            try:
                return self.send_json(200, planner_config())
            except (ImportError, FileNotFoundError, ValueError, KeyError) as error:
                return self.send_json(503, {"detail": f"Planner configuration unavailable: {error}"})
        if self.path != "/api/study":
            return self.send_json(404, {"detail": "Unknown endpoint"})
        try:
            self.send_json(200, evaluate({}))
        except (FileNotFoundError, ValueError, KeyError) as error:
            self.send_json(503, {"detail": f"Validated study unavailable: {error}"})

    def do_POST(self):
        if self.path not in ("/api/evaluate", "/api/planner/solve"):
            return self.send_json(404, {"detail": "Unknown endpoint"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 100000:
                raise ValueError("Request body must be 1–100000 bytes")
            body = json.loads(self.rfile.read(length))
            self.send_json(200, solve_planner(body) if self.path == "/api/planner/solve" else evaluate(body))
        except (ValueError, TypeError) as error:
            self.send_json(400, {"detail": str(error)})
        except (ImportError, FileNotFoundError, KeyError) as error:
            self.send_json(503, {"detail": f"Study unavailable: {error}"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8003)
    parser.add_argument("--frontend-port", type=int, default=5176)
    args = parser.parse_args()
    frontend = ThreadingHTTPServer(("127.0.0.1", args.frontend_port),
                  partial(SimpleHTTPRequestHandler, directory=str(BASE / "frontend")))
    api = ThreadingHTTPServer(("127.0.0.1", args.api_port), Handler)
    threading.Thread(target=frontend.serve_forever, daemon=True).start()
    print(f"ExhaustLab: http://127.0.0.1:{args.frontend_port}/ API: http://127.0.0.1:{args.api_port}", flush=True)
    try:
        api.serve_forever()
    finally:
        frontend.shutdown()
        frontend.server_close()
        api.server_close()


if __name__ == "__main__":
    main()
