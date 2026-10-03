"""Verified, fixed-layout Allsolve cafeteria treatment comparison.

Only the local 6 x 4 m, 250 Hz preset is accepted. Each reported pressure
amplitude comes from two harmonic components returned by a completed Allsolve
simulation. The damped 2D strip is an illustrative material-loss proxy, not
measured absorption, broadband response, sound isolation, or a commercial
product specification.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import allsolve
from dotenv import dotenv_values


EXPERIMENTS = Path(__file__).resolve().parent
WORKSPACE = EXPERIMENTS.parents[1]
STATE = EXPERIMENTS / "harmonic_state.json"

FREQUENCY_HZ = 250.0
ROOM = {"width_m": 6.0, "length_m": 4.0}
SOURCE = {"x_m": 1.0, "y_m": 2.0}
LISTENERS = {
    "near": {"x_m": 2.5, "y_m": 2.0},
    "far": {"x_m": 5.0, "y_m": 2.0},
}
TREATMENTS = {
    "east": {"x_m": 5.85, "y_m": 2.0, "region": "treatment_zone"},
    "north": {"x_m": 3.0, "y_m": 3.85, "region": "north_zone"},
    "south": {"x_m": 3.0, "y_m": 0.15, "region": "south_zone"},
}


def _same_number(value: Any, expected: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and math.isclose(number, expected, abs_tol=1e-9)


def _same_point(value: Any, expected: dict[str, float]) -> bool:
    keys = ("x_m", "y_m") if "x_m" in expected else expected.keys()
    return isinstance(value, dict) and all(_same_number(value.get(k), expected[k]) for k in keys)


def _validate_request(request: dict) -> list[dict]:
    if not isinstance(request, dict):
        raise ValueError("Comparison input must be an object")
    if not _same_number(request.get("frequency_hz"), FREQUENCY_HZ):
        raise ValueError("Only the verified 250 Hz harmonic model is available")
    if not _same_point(request.get("room"), ROOM) or not _same_point(request.get("source"), SOURCE):
        raise ValueError("Room/source must match the verified cafeteria preset")

    listeners = request.get("listeners")
    if not isinstance(listeners, list) or len(listeners) != len(LISTENERS):
        raise ValueError("Listener positions must match the verified preset")
    seen_listeners = set()
    for listener in listeners:
        if not isinstance(listener, dict) or listener.get("id") not in LISTENERS:
            raise ValueError("Unknown listener")
        listener_id = listener["id"]
        if listener_id in seen_listeners or not _same_point(listener, LISTENERS[listener_id]):
            raise ValueError("Listener positions must match the verified preset")
        seen_listeners.add(listener_id)

    treatments = request.get("treatments")
    if not isinstance(treatments, list):
        raise ValueError("Treatments must be a list")
    selected = []
    seen = set()
    for treatment in treatments:
        if not isinstance(treatment, dict) or treatment.get("id") not in TREATMENTS:
            raise ValueError("Unknown treatment location")
        treatment_id = treatment["id"]
        if treatment_id in seen or not _same_point(treatment, TREATMENTS[treatment_id]):
            raise ValueError("Treatment locations must match the verified preset")
        seen.add(treatment_id)
        if treatment.get("selected") is True:
            cost = treatment.get("cost_eur")
            try:
                cost = float(cost)
            except (TypeError, ValueError) as exc:
                raise ValueError("Treatment cost must be finite") from exc
            if not math.isfinite(cost) or cost < 0:
                raise ValueError("Treatment cost must be nonnegative and finite")
            selected.append({"id": treatment_id, "cost_eur": cost})
    if not selected:
        raise ValueError("Select at least one treatment")
    return selected


def _client() -> allsolve.Client:
    private_file = dotenv_values(WORKSPACE / ".env")
    key = os.environ.get("ALLSOLVE_ACCESS_KEY") or private_file.get("ALLSOLVE_ACCESS_KEY")
    secret = os.environ.get("ALLSOLVE_SECRET_KEY") or private_file.get("ALLSOLVE_SECRET_KEY")
    host = os.environ.get("ALLSOLVE_HOST") or private_file.get("ALLSOLVE_HOST") or "https://allsolve.quanscient.com/"
    if not key or not secret:
        raise RuntimeError("Allsolve credentials are not configured")
    return allsolve.Client(api_key=key, api_secret=secret, host=host, dotenv_file=None)


def _load_state() -> dict:
    marker_path = EXPERIMENTS / "VERIFIED_COMPARISON.json"
    if not marker_path.is_file():
        raise RuntimeError("Verified Allsolve project marker is missing")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if STATE.is_file():
        state = json.loads(STATE.read_text(encoding="utf-8"))
    else:
        # The runtime cache is ignored by Git. Rehydrate known completed jobs
        # from the checked-in verification marker after a fresh checkout.
        state = {
            "project_id": marker["project_id"],
            "simulations": {
                "baseline": marker["baseline_simulation_id"],
                **marker["candidate_simulation_ids"],
            },
        }
    if not state.get("project_id"):
        raise RuntimeError("Allsolve project ID is missing")
    if state["project_id"] != marker["project_id"]:
        raise RuntimeError("Runtime state project differs from verified project")
    verified_ids = {
        "baseline": marker["baseline_simulation_id"],
        **marker["candidate_simulation_ids"],
    }
    runtime_ids = state.setdefault("simulations", {})
    for name, simulation_id in verified_ids.items():
        if runtime_ids.get(name) not in (None, simulation_id):
            raise RuntimeError(f"Runtime {name} job differs from verified job")
        runtime_ids[name] = simulation_id
    return state


def _save_state(state: dict) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def _get_damping(project) -> Any:
    acoustics = next((p for p in project.get_physics() if p.definition == "acousticWaves"), None)
    if acoustics is None:
        raise RuntimeError("AcousticWaves physics missing from project")
    damping = next(
        (interaction for interaction in acoustics.get_interactions()
         if interaction.definition == "acousticWavesAcousticDamping"),
        None,
    )
    if damping is None:
        raise RuntimeError("Acoustic damping interaction missing from project")
    return damping


def _set_damping(damping, region, enabled: bool) -> None:
    if damping.enabled != enabled:
        damping.enabled = enabled
    if enabled and damping.target_region_id() != region.id:
        damping.set_target_region_id(region.id)
    damping.save()


def _create_simulation(project, mesh_id: str, name: str):
    simulation = allsolve.Simulation.create(
        name=f"250 Hz {name}",
        description=f"Cafeteria acoustic pressure with {name} treatment state",
        max_run_time_minutes=10,
        solver_mode=allsolve.SolverMode.DIRECT,
        mesh_id=mesh_id,
        physics_set=project.get_default_physics_set(),
        analysis_type=allsolve.AnalysisType.HARMONIC,
        fundamental_frequency=str(int(FREQUENCY_HZ)),
        project_id=project.id,
    )
    outputs = []
    for listener_id, point in LISTENERS.items():
        for component, harmonic in (("in_phase", 2), ("quadrature", 3)):
            outputs.append(allsolve.Output.ValueOutput(
                name=f"p_{listener_id}_{component}",
                expression=(
                    f"interpolate(reg.all_surfaces, getharmonic({harmonic}, p), "
                    f"[{point['x_m']},{point['y_m']},0])"
                ),
            ))
    simulation.add_outputs(outputs)
    simulation.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_3_10GB_FAST_START, node_count=1))
    simulation.save()
    return simulation


def _run_or_get(
    project, state: dict, name: str, *, fresh_run: bool = False
) -> tuple[str, dict[str, float]]:
    ids = state.setdefault("simulations", {})
    run_record = None
    if fresh_run:
        # Each UI Run creates new candidate jobs. The verified baseline and
        # earlier candidate jobs remain unchanged for provenance.
        simulation = _create_simulation(
            project, state["mesh_id"],
            f"{name} {datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        )
        run_record = {
            "candidate_id": name,
            "simulation_id": str(simulation.id),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "created",
        }
        state.setdefault("run_history", []).append(run_record)
        _save_state(state)
    else:
        if not ids.get(name):
            raise RuntimeError(f"Verified {name} simulation ID is missing")
        simulation = allsolve.Simulation.get(ids[name], project_id=project.id)

    try:
        status = simulation.get_status()
        if status == allsolve.Job.NOT_STARTED:
            simulation.start()
        elif status in (allsolve.Job.ERROR, allsolve.Job.ABORTED):
            raise RuntimeError(f"Allsolve {name} solve is {status}")
        if status != allsolve.Job.SUCCESS:
            deadline = time.monotonic() + 900
            while simulation.is_running(refresh_delay_s=2):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Allsolve {name} solve exceeded 15 minutes")
        if simulation.get_status() != allsolve.Job.SUCCESS:
            raise RuntimeError(f"Allsolve {name} solve failed: {simulation.get_status()}")

        data = simulation.get_output_values(refresh=True)
        values = data.get("nostep", {})
        amplitudes: dict[str, float] = {}
        for listener_id in LISTENERS:
            parts = []
            for component in ("in_phase", "quadrature"):
                value = values.get(f"p_{listener_id}_{component}")
                if isinstance(value, list) and len(value) == 1:
                    value = value[0]
                if value is None:
                    raise RuntimeError(f"Missing Allsolve {name}/{listener_id}/{component} output")
                part = float(value)
                if not math.isfinite(part):
                    raise RuntimeError("Allsolve returned nonfinite pressure")
                parts.append(part)
            amplitude = math.hypot(*parts)
            if amplitude <= 0:
                raise RuntimeError("Allsolve returned zero pressure amplitude")
            amplitudes[listener_id] = amplitude
        if run_record is not None:
            run_record["status"] = "completed"
            run_record["amplitudes"] = amplitudes
            _save_state(state)
        return str(simulation.id), amplitudes
    except Exception as exc:
        if run_record is not None:
            run_record["status"] = "failed"
            run_record["error_type"] = type(exc).__name__
            _save_state(state)
        raise


def run_comparison(request: dict) -> dict:
    """Return only solver amplitudes and IDs for the fixed 250 Hz preset."""
    selected = _validate_request(request)
    client = _client()
    state = _load_state()
    verified_ids = state["simulations"]
    if any(candidate["id"] not in verified_ids for candidate in selected):
        raise ValueError("Selected treatment is not in the verified comparison")
    project = client.get_project(state["project_id"])
    if not state.get("mesh_id"):
        meshes = project.get_meshes()
        if not meshes:
            raise RuntimeError("Verified Allsolve mesh is missing")
        state["mesh_id"] = meshes[0].id
        _save_state(state)
    regions = {region.name: region for region in project.get_regions()}
    if not {"treatment_zone", "north_zone", "south_zone"}.issubset(regions):
        raise RuntimeError("Project treatment regions are incomplete")
    damping = _get_damping(project)

    _set_damping(damping, regions["treatment_zone"], enabled=False)
    baseline_id, baseline = _run_or_get(project, state, "baseline")
    result = {
        "frequency_hz": FREQUENCY_HZ,
        "baseline": baseline,
        "baseline_simulation_id": baseline_id,
        "candidates": [],
    }
    for candidate in selected:
        candidate_id = candidate["id"]
        _set_damping(damping, regions[TREATMENTS[candidate_id]["region"]], enabled=True)
        simulation_id, amplitudes = _run_or_get(
            project, state, candidate_id, fresh_run=True
        )
        result["candidates"].append({
            "id": candidate_id,
            "cost_eur": candidate["cost_eur"],
            "amplitudes": amplitudes,
            "simulation_id": simulation_id,
        })
    return result


if __name__ == "__main__":
    preset = {
        "room": ROOM,
        "source": SOURCE,
        "frequency_hz": FREQUENCY_HZ,
        "listeners": [{"id": key, **point} for key, point in LISTENERS.items()],
        "treatments": [
            {"id": key, "x_m": value["x_m"], "y_m": value["y_m"],
             "cost_eur": cost, "selected": True}
            for (key, value), cost in zip(TREATMENTS.items(), (220, 260, 180))
        ],
        "budget_eur": 300,
    }
    print(json.dumps(run_comparison(preset), indent=2))
