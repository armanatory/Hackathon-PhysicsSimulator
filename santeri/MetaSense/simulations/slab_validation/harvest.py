"""Harvest public SDK outputs and apply fixed optical benchmark acceptance gates.

No jobs are launched and no field downloads are performed here. Raw scalar
outputs, a CSV export, run provenance, and the acceptance report are saved
separately. Analytic reference agreement alone never marks this report verified.
"""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path

import allsolve

try:  # runner.py is also supported as a directly executed script.
    from .fresnel import slab_reference
except ImportError:
    from fresnel import slab_reference


TOLERANCES = {
    "reflectance_transmittance_absolute": 0.01,
    "energy_absolute": 0.01,
    "incident_normalization_absolute": 0.02,
    "exit_backward_fraction_max": 0.001,
    "crosspolarized_fraction_max": 1e-4,
    "convergence_absolute": 0.005,
    "reported_scalar_consistency_absolute": 1e-8,
    "poynting_directional_consistency_fraction": 1e-6,
}
POWER_OUTPUTS = (
    "specified_incident_power_W", "entrance_forward_power_W",
    "entrance_backward_power_W", "exit_forward_power_W", "exit_backward_power_W",
    "entrance_crosspolarized_power_W", "exit_crosspolarized_power_W",
)
REQUIRED_OUTPUTS = POWER_OUTPUTS + (
    "slab_index", "reflectance", "transmittance", "energy_residual",
    "incident_normalization_ratio", "exit_backward_fraction",
    "entrance_net_flux_W", "exit_net_flux_W",
    "entrance_poynting_flux_W", "exit_poynting_flux_W",
    "entrance_Ex_cos", "entrance_Ex_sin", "entrance_Hy_cos", "entrance_Hy_sin",
    "exit_Ex_cos", "exit_Ex_sin", "exit_Hy_cos", "exit_Hy_sin",
)
REQUIRED_RUNS = ("coarse", "fine")
TERMINAL_FAILURES = (
    allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.FAILING,
    allsolve.Job.PARTIAL_SUCCESS,
)
ACTIVE_STATUSES = (allsolve.Job.RUNNING, allsolve.Job.STARTING,
                   allsolve.Job.PROCESSING_OUTPUT, allsolve.Job.ABORTING)


def _json_safe(value):
    """Retain invalid nonfinite raw evidence without writing invalid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_safe(data), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _scalar(values: dict, name: str) -> float:
    if not isinstance(values, dict) or not isinstance(values.get("nostep"), dict):
        raise ValueError("Expected one harmonic output table under 'nostep'")
    entry = values["nostep"].get(name)
    if not isinstance(entry, (list, tuple)) or len(entry) != 1:
        raise ValueError(f"{name} must contain exactly one scalar value")
    value = entry[0]
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite real scalar")
    return float(value)


def _reference_json(reference) -> dict:
    return {
        "label": reference.label,
        "wavelength_m": reference.wavelength_m,
        "thickness_m": reference.thickness_m,
        "n_slab": reference.n_slab,
        "n_left": reference.n_left,
        "n_right": reference.n_right,
        "r": {"real": reference.r.real, "imag": reference.r.imag},
        "t": {"real": reference.t.real, "imag": reference.t.imag},
        "R": reference.R, "T": reference.T,
        "energy_residual": 1.0 - reference.R - reference.T,
        "phasor_convention": reference.phasor_convention,
        "amplitude_planes": "incident/reflected at left slab face; transmitted at right slab face",
    }


def _make_references(inputs: dict) -> dict:
    indices = inputs["indices"]
    if not isinstance(indices, list) or len(indices) != 2:
        raise ValueError("inputs.indices must contain control and slab indices")
    exterior = inputs["exterior_index"]
    control, slab = indices
    control_reference = slab_reference(inputs["wavelength_m"], inputs["slab_thickness_m"],
                                       control, exterior, exterior)
    slab_result = slab_reference(inputs["wavelength_m"], inputs["slab_thickness_m"], slab, exterior, exterior)
    if not math.isclose(control_reference.n_slab, control_reference.n_left, rel_tol=0, abs_tol=1e-12):
        raise ValueError("the control index must match the homogeneous exterior")
    if math.isclose(control_reference.n_slab, slab_result.n_slab, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("the control and slab indices must be distinct")
    return {"vacuum_control": _reference_json(control_reference),
            "dielectric_slab": _reference_json(slab_result)}


def _evaluate_case(raw: dict, sweep_index: int, reference: dict) -> dict:
    result = {"n_slab": reference["n_slab"], "sweep_index": sweep_index,
              "numerical": {}, "checks": {}, "passed": False, "errors": []}
    outputs = {}
    for name in REQUIRED_OUTPUTS:
        try:
            outputs[name] = _scalar(raw, name)
        except ValueError as error:
            result["errors"].append(str(error))
    result["reported_outputs"] = outputs
    checks = result["checks"]
    checks["all_required_outputs_finite"] = not result["errors"]
    if result["errors"]:
        return result
    checks["nonnegative_powers"] = all(outputs[name] >= 0 for name in POWER_OUTPUTS)
    pin = outputs["entrance_forward_power_W"]
    specified = outputs["specified_incident_power_W"]
    checks["positive_incident_power"] = pin > 0 and specified > 0
    if not checks["nonnegative_powers"] or not checks["positive_incident_power"]:
        result["errors"].append("Directional powers must be nonnegative and incident powers positive")
        return result

    reflected = outputs["entrance_backward_power_W"]
    transmitted = outputs["exit_forward_power_W"]
    exit_back = outputs["exit_backward_power_W"]
    R, T = reflected / pin, transmitted / pin
    numerical = result["numerical"]
    numerical.update(
        R=R, T=T, energy_residual=1.0 - R - T,
        incident_normalization_ratio=pin / specified,
        exit_backward_fraction=exit_back / pin,
        entrance_crosspolarized_fraction=outputs["entrance_crosspolarized_power_W"] / pin,
        exit_crosspolarized_fraction=outputs["exit_crosspolarized_power_W"] / pin,
        incident_power_W=pin, specified_incident_power_W=specified,
        reflected_power_W=reflected, transmitted_power_W=transmitted,
        exit_backward_power_W=exit_back,
        entrance_net_flux_W=outputs["entrance_net_flux_W"],
        exit_net_flux_W=outputs["exit_net_flux_W"],
        entrance_poynting_flux_W=outputs["entrance_poynting_flux_W"],
        exit_poynting_flux_W=outputs["exit_poynting_flux_W"],
        reflectance_error=abs(R - reference["R"]),
        transmittance_error=abs(T - reference["T"]),
    )
    checks["normalized_outputs_finite"] = all(math.isfinite(value) for value in numerical.values())
    if not checks["normalized_outputs_finite"]:
        result["errors"].append("Normalized powers must remain finite")
        return result
    checks["reflectance_reference"] = numerical["reflectance_error"] <= TOLERANCES["reflectance_transmittance_absolute"]
    checks["transmittance_reference"] = numerical["transmittance_error"] <= TOLERANCES["reflectance_transmittance_absolute"]
    checks["energy_balance"] = abs(numerical["energy_residual"]) <= TOLERANCES["energy_absolute"]
    checks["incident_normalization"] = abs(numerical["incident_normalization_ratio"] - 1) <= TOLERANCES["incident_normalization_absolute"]
    checks["exit_incoming_wave"] = numerical["exit_backward_fraction"] <= TOLERANCES["exit_backward_fraction_max"]
    checks["entrance_polarization"] = numerical["entrance_crosspolarized_fraction"] <= TOLERANCES["crosspolarized_fraction_max"]
    checks["exit_polarization"] = numerical["exit_crosspolarized_fraction"] <= TOLERANCES["crosspolarized_fraction_max"]
    calculated = {
        "reflectance": R, "transmittance": T,
        "energy_residual": numerical["energy_residual"],
        "incident_normalization_ratio": numerical["incident_normalization_ratio"],
        "exit_backward_fraction": numerical["exit_backward_fraction"],
    }
    checks["reported_scalar_consistency"] = all(
        abs(outputs[name] - value) <= TOLERANCES["reported_scalar_consistency_absolute"]
        for name, value in calculated.items()
    )
    for plane, forward, backward in (("entrance", pin, reflected), ("exit", transmitted, exit_back)):
        checks[plane + "_flux_consistency"] = all(
            abs(outputs[plane + suffix] - (forward - backward)) / pin
            <= TOLERANCES["poynting_directional_consistency_fraction"]
            for suffix in ("_net_flux_W", "_poynting_flux_W")
        )
    result["passed"] = all(checks.values())
    result["errors"].extend(f"Acceptance check failed: {name}" for name, passed in checks.items() if not passed)
    return result


def _harvest_run(simulation, metadata: dict, references: dict, folder: Path) -> dict:
    result = {"name": metadata.get("name"), "metadata": copy.deepcopy(metadata),
              "status": "queued", "simulation_status": None, "cases": {},
              "passed": False, "errors": [], "output_files": []}
    if simulation is None:
        result.update(status="failed", errors=["Simulation not found in project"])
        return result
    try:
        status = simulation.get_status()
    except Exception as error:
        result.update(status="failed", errors=[f"Cannot retrieve simulation status ({type(error).__name__})"])
        return result
    result["simulation_status"] = status
    if status != allsolve.Job.SUCCESS:
        if status in TERMINAL_FAILURES:
            result.update(status="failed", errors=[f"Simulation job did not succeed: {status}"])
        elif status in ACTIVE_STATUSES:
            result["status"] = "running"
        return result
    result["status"] = "completed"
    folder.mkdir(parents=True, exist_ok=True)
    for sweep_index in range(2):
        try:
            raw = simulation.get_output_values(sweep_index, refresh=True)
        except Exception as error:
            result["errors"].append(f"Cannot retrieve sweep {sweep_index} outputs ({type(error).__name__})")
            continue
        raw_path = folder / f"raw_output_sweep_{sweep_index}.json"
        _write_json(raw_path, {"simulation_id": metadata.get("simulation_id"),
                               "sweep_index": sweep_index, "public_output_values": raw})
        result["output_files"].append(str(raw_path))
        try:
            index = _scalar(raw, "slab_index")
        except ValueError as error:
            result["errors"].append(f"Sweep {sweep_index}: {error}")
            continue
        matching = [name for name, reference in references.items()
                    if math.isclose(index, reference["n_slab"], rel_tol=1e-9, abs_tol=1e-12)]
        if len(matching) != 1:
            result["errors"].append(f"Sweep {sweep_index} returned unexpected slab_index {index}")
            continue
        case_name = matching[0]
        if case_name in result["cases"]:
            result["errors"].append(f"Duplicate slab_index for {case_name}; a benchmark case is missing")
            continue
        result["cases"][case_name] = _evaluate_case(raw, sweep_index, references[case_name])
    try:
        csv = simulation.get_output_data(refresh=False).to_csv()
        if not isinstance(csv, str) or not csv.strip():
            raise ValueError("Empty CSV")
        csv_path = folder / "public_outputs.csv"
        csv_path.write_text(csv, encoding="utf-8")
        result["output_files"].append(str(csv_path))
    except Exception as error:
        result["errors"].append(f"Cannot export public output CSV ({type(error).__name__})")
    for name in references:
        if name not in result["cases"]:
            result["errors"].append(f"Missing benchmark case: {name}")
    if result["errors"]:
        result["status"] = "failed"
    result["passed"] = (not result["errors"] and len(result["cases"]) == len(references)
                        and all(case["passed"] for case in result["cases"].values()))
    return result


def _convergence(runs: list, references: dict) -> dict:
    result = {"same_source": False, "passed": False, "errors": []}
    selected = {}
    for name in REQUIRED_RUNS:
        matching = [run for run in runs if run["name"] == name]
        if len(matching) != 1:
            result["errors"].append(f"Convergence requires exactly one {name} run")
        else:
            selected[name] = matching[0]
    if len(selected) != 2:
        return result
    coarse, fine = selected["coarse"], selected["fine"]
    coarse_hash = coarse["metadata"].get("source_sha256")
    fine_hash = fine["metadata"].get("source_sha256")
    result["same_source"] = (isinstance(coarse_hash, str) and bool(coarse_hash)
                             and coarse_hash == fine_hash)
    if not result["same_source"]:
        result["errors"].append("Coarse and fine source SHA values must be present and identical")
    if coarse["status"] != "completed" or fine["status"] != "completed":
        result["errors"].append("Both coarse and fine runs must complete before convergence is evaluated")
        return result
    for case_name in references:
        a = coarse["cases"].get(case_name, {}).get("numerical", {})
        b = fine["cases"].get(case_name, {}).get("numerical", {})
        if not all(key in case for case in (a, b) for key in ("R", "T")):
            result["errors"].append(f"Missing finite R/T for convergence case {case_name}")
            continue
        delta_R, delta_T = abs(a["R"] - b["R"]), abs(a["T"] - b["T"])
        checks = {"reflectance": math.isfinite(delta_R) and delta_R <= TOLERANCES["convergence_absolute"],
                  "transmittance": math.isfinite(delta_T) and delta_T <= TOLERANCES["convergence_absolute"]}
        result[case_name] = {"delta_R": delta_R, "delta_T": delta_T,
                             "checks": checks, "passed": all(checks.values())}
        if not all(checks.values()):
            result["errors"].append(f"Mesh convergence failed: {case_name}")
    result["passed"] = (not result["errors"] and all(
        result.get(name, {}).get("passed", False) for name in references))
    return result


def harvest(project, state: dict, results_directory: Path | str) -> dict:
    """Retrieve successful SDK scalar outputs and write an auditable report.

    Incomplete jobs leave status queued/running, terminal job/retrieval failures leave
    status failed, and complete numerical failures leave status completed with
    validated=false. Accepting the benchmark requires both complete meshes,
    every case gate, matching source SHA values, and mesh convergence.
    """
    folder = Path(results_directory)
    report = {
        "label": "allsolve_slab_validation", "purpose": "optical_slab_benchmark",
        "synthetic": False, "status": "queued", "validated": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": copy.deepcopy(state.get("inputs", {})),
        "state_provenance": copy.deepcopy(state),
        "tolerances": dict(TOLERANCES), "analytical_reference": {},
        "runs": [], "convergence": {"passed": False}, "errors": [],
        "energy_residual_convention": "1 - R - T",
        "nonfinite_raw_encoding": "Nonfinite raw numbers are preserved as {'nonfinite': 'nan'|'inf'|'-inf'}",
    }
    try:
        references = _make_references(report["inputs"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        report.update(status="failed", errors=[f"Invalid benchmark inputs: {error}"])
        _write_json(folder / "report.json", report)
        return _json_safe(report)
    report["analytical_reference"] = references
    try:
        simulations = {simulation.id: simulation for simulation in project.get_simulations()}
    except Exception as error:
        report.update(status="failed", errors=[f"Cannot list simulations ({type(error).__name__})"])
        _write_json(folder / "report.json", report)
        return _json_safe(report)
    for index, metadata in enumerate(state.get("runs", [])):
        name = metadata.get("name", "")
        safe_name = name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+", name) else f"run-{index}"
        run = _harvest_run(simulations.get(metadata.get("simulation_id")), metadata,
                           references, folder / safe_name)
        report["runs"].append(run)
    report["convergence"] = _convergence(report["runs"], references)
    required = [run for run in report["runs"] if run["name"] in REQUIRED_RUNS]
    missing = [name for name in REQUIRED_RUNS if not any(run["name"] == name for run in required)]
    report["errors"].extend(f"Missing required run: {name}" for name in missing)
    report["errors"].extend(f"{run['name']}: {error}" for run in required for error in run["errors"])
    if any(run["status"] == "failed" for run in required):
        report["status"] = "failed"
    elif any(run["status"] == "running" for run in required):
        report["status"] = "running"
    elif missing or any(run["status"] == "queued" for run in required):
        report["status"] = "queued"
    else:
        report["status"] = "completed"
    report["validated"] = (
        report["status"] == "completed" and len(required) == 2
        and all(run["passed"] for run in required) and report["convergence"]["passed"]
    )
    report["errors"].extend(report["convergence"].get("errors", []))
    for run in required:
        for case_name, case in run["cases"].items():
            report["errors"].extend(f"{run['name']}/{case_name}: {error}" for error in case["errors"])
    _write_json(folder / "report.json", report)
    return _json_safe(report)
