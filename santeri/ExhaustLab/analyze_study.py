"""Validate harvested Allsolve grids and postprocess local particle trajectories.

No Allsolve SDK, credentials, network requests, or generated field substitutes
are used here. Run with the bundled NumPy Python runtime from the project root:
    python ExhaustLab/analyze_study.py --case gap6
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .particles import (
        ParticleModel, RectangularChannel, RegularGridFieldSampler,
        flux_weighted_inlet, integrate_trajectories, timestep_convergence,
    )
except ImportError:
    from particles import (
        ParticleModel, RectangularChannel, RegularGridFieldSampler,
        flux_weighted_inlet, integrate_trajectories, timestep_convergence,
    )


BASE = Path(__file__).resolve().parent
MODEL_LABEL = "Modeled room-temperature pilot; precharged dilute spherical particles; local postprocessing of Allsolve fields"


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return data


def require_field_validation(validation: dict[str, Any], state: dict[str, Any], source_hashes: dict[str, str]) -> None:
    """A successful cloud job alone is insufficient for physical postprocessing."""
    if validation.get("passed") is not True or validation.get("all_field_benchmark_checks_passed") is not True:
        raise ValueError("Field benchmark validation has not passed; particle capture processing is disabled.")
    source = validation.get("source", {})
    identifiers = ("project_id", "mesh_id", "mesh_job_id", "flow_simulation_id", "flow_job_id", "electric_simulation_id", "electric_job_id")
    if any(source.get(key) != state.get(key) for key in identifiers):
        raise ValueError("Field validation identifiers do not match the current completed source jobs.")
    if source.get("file_sha256") != source_hashes:
        raise ValueError("Field validation hashes do not match current state/field snapshots; rerun benchmark validation.")
    for group in ("flow", "electric"):
        section = validation.get(group, {})
        checks = section.get("checks", {})
        if section.get("status") != "pass" or not checks or any(check.get("pass") is not True for check in checks.values()):
            raise ValueError(f"{group} benchmark checks have not all passed.")


def _positive(state: dict[str, Any], name: str) -> float:
    value = float(state[name])
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive.")
    return value


def _flat_samples(data: dict[str, Any], count: int, label: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Custom output arrays are flat: xyz triples, vector triples, one scalar."""
    arrays = []
    for key, size in (("sample_xyz_m", 3 * count), ("sample_vector", 3 * count), ("sample_scalar", count)):
        array = np.asarray(data[key], dtype=float)
        if array.shape != (size,) or not np.isfinite(array).all():
            raise ValueError(f"{label}.{key} requires exactly {size} finite flat entries.")
        arrays.append(array)
    volume_array = np.asarray(data["gas_volume_m3"], dtype=float)
    if volume_array.shape != (1,) or not np.isfinite(volume_array).all() or volume_array[0] <= 0:
        raise ValueError(f"{label}.gas_volume_m3 must be a one-value positive finite output array.")
    return arrays[0].reshape(count, 3), arrays[1].reshape(count, 3), arrays[2], float(volume_array[0])


def extract_case(
    state: dict[str, Any], flow: dict[str, Any], electric: dict[str, Any]
) -> tuple[RectangularChannel, RegularGridFieldSampler, np.ndarray, np.ndarray, dict[str, Any]]:
    """Reject incomplete/ambiguous artifacts before any particle calculation."""
    for kind in ("mesh", "flow", "electric"):
        status = str(state.get(f"{kind}_status", ""))
        if status.split(".")[-1] != "SUCCESS":
            raise ValueError(f"{kind} is not a completed successful job: {status or 'missing status'}.")
        for suffix in ("job_id", "id" if kind == "mesh" else "simulation_id"):
            key = f"{kind}_{suffix}"
            if not isinstance(state.get(key), str) or not state[key]:
                raise ValueError(f"Source provenance is missing {key}.")
    for key in ("project_id", "project_url", "case"):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ValueError(f"Source provenance is missing {key}.")
    if state.get("geometry_built") is not True:
        raise ValueError("Source geometry has not been recorded as built.")
    grid_shape = state.get("grid_shape")
    if not isinstance(grid_shape, list) or len(grid_shape) != 3 or any(type(n) is not int or n < 2 for n in grid_shape):
        raise ValueError("grid_shape must give three integer axis lengths of at least two.")
    shape = tuple(grid_shape)
    count = math.prod(shape)
    channel = RectangularChannel(
        length_m=_positive(state, "length_m"), gap_m=_positive(state, "gap_m"), span_m=_positive(state, "span_m")
    )
    _positive(state, "mu_pa_s")
    _positive(state, "rho_kg_m3")
    _positive(state, "flow_m3_s")
    _positive(state, "voltage_v")
    flow_points, velocity, pressure, flow_volume = _flat_samples(flow, count, "flow")
    electric_points, efield, potential, electric_volume = _flat_samples(electric, count, "electric")
    if not np.array_equal(flow_points, electric_points):
        raise ValueError("Flow and electrostatic coordinates do not match exactly; no resampling or inferred registration is permitted.")
    coordinates = flow_points.reshape(shape + (3,))
    axes = (coordinates[:, 0, 0, 0], coordinates[0, :, 0, 1], coordinates[0, 0, :, 2])
    expected_tensor = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    if not np.array_equal(coordinates, expected_tensor):
        raise ValueError("Field export must be x-major, y-middle, z-fastest tensor-grid order.")
    for axis, dimension in zip(axes, channel.extent_m):
        if not (np.diff(axis) > 0).all() or axis[0] != 0 or not np.isclose(axis[-1], dimension, rtol=1e-12, atol=0):
            raise ValueError("Grid axes must be increasing and include exact inlet/wall/outlet endpoint coordinates.")
    expected_volume = float(np.prod(channel.extent_m))
    for kind, volume in (("flow", flow_volume), ("electric", electric_volume)):
        if not np.isclose(volume, expected_volume, rtol=1e-5, atol=0):
            raise ValueError(f"{kind} gas-volume output disagrees with the declared rectangular geometry.")
    provenance = {
        key: state[key] for key in (
            "case", "project_id", "project_url", "mesh_id", "mesh_job_id",
            "flow_simulation_id", "flow_job_id", "electric_simulation_id", "electric_job_id",
            "mesh_status", "flow_status", "electric_status", "grid_shape",
        )
    }
    provenance["field_origin"] = "Allsolve finite-element cloud interpolation outputs"
    provenance["vector_fields"] = {"flow": "velocity [ux,uy,uz], m/s", "electric": "-grad(potential) [Ex,Ey,Ez], V/m"}
    provenance["scalar_fields"] = {"flow": "gauge pressure, Pa", "electric": "potential, V"}
    sampler = RegularGridFieldSampler(*axes, velocity.reshape(shape + (3,)), efield.reshape(shape + (3,)), provenance=provenance)
    return channel, sampler, pressure.reshape(shape), potential.reshape(shape), provenance


def _face_integral(values: np.ndarray, y_m: np.ndarray, z_m: np.ndarray) -> float:
    return float(np.trapezoid(np.trapezoid(values, z_m, axis=1), y_m, axis=0))


def field_diagnostics(state, channel, sampler, pressure, potential) -> dict[str, Any]:
    _, y_m, z_m = sampler.axes_m
    area = channel.gap_m * channel.span_m
    face_flux = np.array([_face_integral(face, y_m, z_m) for face in sampler.velocity_m_s[..., 0]])
    inlet_pressure = _face_integral(pressure[0], y_m, z_m) / area
    outlet_pressure = _face_integral(pressure[-1], y_m, z_m) / area
    drop = inlet_pressure - outlet_pressure
    ideal_e = np.array([0.0, -state["voltage_v"] / channel.gap_m, 0.0])
    ideal_potential = np.broadcast_to(state["voltage_v"] * y_m[None, :, None] / channel.gap_m, potential.shape)
    sampled_e = sampler.electric_v_m
    reference_drop = state.get("reference", {}).get("pressure_drop_pa")
    return {
        "inlet_pressure_area_average_pa": inlet_pressure,
        "outlet_pressure_area_average_pa": outlet_pressure,
        "pressure_drop_pa": drop,
        "pressure_drop_definition": "inlet minus outlet area-averaged static gauge pressure from exported scalar field",
        "hydraulic_power_at_entered_flow_w": drop * state["flow_m3_s"],
        "hydraulic_power_note": "Q times pressure drop only; excludes blower inefficiency and electrical supply consumption",
        "entered_flow_m3_s": state["flow_m3_s"],
        "export_grid_inlet_flux_m3_s": float(face_flux[0]),
        "export_grid_outlet_flux_m3_s": float(face_flux[-1]),
        "flux_relative_range": float(np.ptp(face_flux) / state["flow_m3_s"]),
        "export_grid_inlet_flow_relative_error": float(face_flux[0] / state["flow_m3_s"] - 1),
        "analytic_reference_pressure_drop_pa": reference_drop,
        "pressure_drop_relative_reference_error": drop / reference_drop - 1 if reference_drop and reference_drop > 0 else None,
        "electric_vector_relative_max_error_uniform_reference": float(np.max(np.linalg.norm(sampled_e - ideal_e, axis=-1)) / np.linalg.norm(ideal_e)),
        "potential_relative_max_error_linear_reference": float(np.max(np.abs(potential - ideal_potential)) / state["voltage_v"]),
        "nominal_sampled_max_slip_reynolds": float(np.max(ParticleModel(gas_viscosity_pa_s=state["mu_pa_s"]).slip_reynolds_number(sampled_e, state["rho_kg_m3"]))),
        "field_validation_note": "Reference errors compare real exported fields with analytic checks; they are diagnostics, not substitute field results or automatic solver validation",
    }


def process_case(folder: Path) -> dict[str, Any]:
    names = ("state.json", "flow_samples.json", "electric_samples.json")
    raw_sources = {name: (folder / name).read_bytes() for name in names}
    source_hashes = {name: hashlib.sha256(content).hexdigest() for name, content in raw_sources.items()}
    snapshots = {name: json.loads(content.decode("utf-8")) for name, content in raw_sources.items()}
    state = snapshots["state.json"]
    validation_path = folder / "validation.json"
    raw_validation = validation_path.read_bytes()
    validation = json.loads(raw_validation.decode("utf-8"))
    require_field_validation(validation, state, source_hashes)
    channel, sampler, pressure, potential, provenance = extract_case(
        state, snapshots["flow_samples.json"], snapshots["electric_samples.json"]
    )
    print(f"{state['case']}: valid real source grids; integrating nominal and convergence trajectories", flush=True)
    particle = ParticleModel(gas_viscosity_pa_s=state["mu_pa_s"])
    inlet = flux_weighted_inlet(sampler, channel, n_y=48, n_z=32)
    indices = tuple(int(i) for i in np.linspace(0, len(inlet.points_m) - 1, 24, dtype=int))
    nominal = integrate_trajectories(sampler, channel, particle, inlet,
        max_step_s=0.01, max_time_s=30, track_indices=indices, path_stride=10)
    time_convergence = timestep_convergence(sampler, channel, particle, inlet,
        max_step_s=0.02, max_time_s=30, levels=3)
    inlet_levels = []
    for n_y, n_z in ((24, 16), (48, 32), (96, 64)):
        level_inlet = flux_weighted_inlet(sampler, channel, n_y=n_y, n_z=n_z)
        result = nominal if (n_y, n_z) == (48, 32) else integrate_trajectories(
            sampler, channel, particle, level_inlet, max_step_s=0.01, max_time_s=30)
        inlet_levels.append({"n_y": n_y, "n_z": n_z, **result.summary()})
    inlet_changes = [
        {
            "coarse_grid": [a["n_y"], a["n_z"]], "fine_grid": [b["n_y"], b["n_z"]],
            "capture_fraction_absolute_change": abs(b["captured_fraction"] - a["captured_fraction"]),
            "outlet_fraction_absolute_change": abs(b["outlet_fraction"] - a["outlet_fraction"]),
        }
        for a, b in zip(inlet_levels, inlet_levels[1:])
    ]
    print(f"{state['case']}: convergence integrated; evaluating input sensitivities", flush=True)
    sensitivities = []
    for diameter_um in (0.5, 1.0, 2.0):
        print(f"{state['case']}: diameter {diameter_um:g} um sensitivity", flush=True)
        for charge_e in (0, 15, 30, 60):
            model = ParticleModel(diameter_m=diameter_um * 1e-6, charge_e=charge_e, gas_viscosity_pa_s=state["mu_pa_s"])
            result = nominal if (diameter_um, charge_e) == (1.0, 30) else integrate_trajectories(
                sampler, channel, model, inlet, max_step_s=0.01, max_time_s=30)
            sensitivities.append({
                "diameter_um": diameter_um, "charge_e": charge_e,
                "cunningham_factor": model.cunningham_factor,
                "electrical_mobility_m2_v_s": model.electrical_mobility_m2_v_s,
                **result.summary(),
            })
    final_dt_change = time_convergence["successive_changes"][-1]["capture_fraction_absolute_change"]
    final_inlet_change = inlet_changes[-1]["capture_fraction_absolute_change"]
    diagnostics = field_diagnostics(state, channel, sampler, pressure, potential)
    artifact = {
        "schema_version": 1,
        "label": MODEL_LABEL,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "case": state["case"],
        "source_provenance": {
            **provenance,
            "file_sha256": source_hashes,
            "validation_file_sha256": hashlib.sha256(raw_validation).hexdigest(),
        },
        "field_validation": validation,
        "inputs": {"length_m": channel.length_m, "gap_m": channel.gap_m, "span_m": channel.span_m,
            "voltage_v": state["voltage_v"], "flow_m3_s": state["flow_m3_s"],
            "gas_viscosity_pa_s": particle.gas_viscosity_pa_s, "gas_density_kg_m3": state["rho_kg_m3"],
            "diameter_um": 1.0, "charge_e": 30.0, "mean_free_path_m": particle.mean_free_path_m,
            "n_y": 48, "n_z": 32, "max_step_s": 0.01, "max_time_s": 30.0},
        "field_diagnostics": diagnostics,
        "nominal": nominal.summary(),
        "traces": [{"seed_index": index, "inlet_weight": float(nominal.normalized_weights[index]),
            "state": str(nominal.states[index]), "reason": str(nominal.reasons[index]),
            "columns": ["time_s", "x_m", "y_m", "z_m"], "points": path.tolist()}
            for index, path in nominal.paths.items()],
        "timestep_convergence": time_convergence,
        "inlet_convergence": {"levels": inlet_levels, "successive_changes": inlet_changes},
        "convergence_assessment": {
            "entered_absolute_capture_tolerance": 0.01,
            "final_timestep_capture_change": final_dt_change,
            "final_inlet_capture_change": final_inlet_change,
            "capture_discretization_within_entered_tolerance": final_dt_change <= 0.01 and final_inlet_change <= 0.01,
            "unresolved_fraction": nominal.summary()["unresolved_fraction"],
            "mesh_and_export_grid_converged": False,
            "note": "The one-percentage-point check covers timestep and inlet quadrature only. Mesh/export-grid refinement and physical model validation remain required; unresolved weight remains in the denominator.",
        },
        "sensitivities": sensitivities,
        "assumptions": [
            "Precharged dilute spherical particles; fixed charge and diameter per trajectory.",
            "Overdamped Cunningham-corrected Stokes motion, dx/dt=u+q Cc E/(3 pi mu d).",
            "Uniform aerosol concentration; carrier-gas flux weighting at deterministic inlet cell centers.",
            "All lateral walls perfectly absorb when the point center hits; no finite-radius offset or resuspension.",
            "No Brownian diffusion, gravity, thermophoresis, charging/corona, space charge, or particle interactions.",
            "Captured/outlet/unresolved fractions use all inlet weight; traces are illustrative sampled seeds.",
            "Room-temperature pilot results do not predict certified combustion-source emission reduction, CO2/NOx capture, or electrical power.",
        ],
    }
    if any(hashlib.sha256((folder / name).read_bytes()).hexdigest() != source_hashes[name] for name in names):
        raise ValueError("Source files changed during integration; no particle artifact written. Revalidate current snapshots.")
    if validation_path.read_bytes() != raw_validation:
        raise ValueError("Benchmark validation changed during integration; no particle artifact written.")
    output = folder / "particles.json"
    output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (folder / "particle_sensitivities.csv").open("w", encoding="utf-8", newline="") as handle:
        columns = ["diameter_um", "charge_e", "captured_fraction", "outlet_fraction", "unresolved_fraction", "capture_upper_bound"]
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sensitivities)
    print(f"{state['case']}: capture={nominal.summary()['captured_fraction']:.4%}; outlet={nominal.summary()['outlet_fraction']:.4%}; unresolved={nominal.summary()['unresolved_fraction']:.4%}; pressure drop={diagnostics['pressure_drop_pa']:.6g} Pa", flush=True)
    print(f"Wrote {output}", flush=True)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs="+", default=["gap6"], help="One or more harvested case directory names")
    args = parser.parse_args()
    for case in args.case:
        folder = (BASE / "runs" / case).resolve()
        if folder.parent != (BASE / "runs").resolve():
            raise ValueError("Case names must identify direct directories under ExhaustLab/runs.")
        process_case(folder)


if __name__ == "__main__":
    main()
