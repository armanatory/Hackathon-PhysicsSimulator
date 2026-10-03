"""Validate Allsolve rectangular-channel point exports, using NumPy only.

Run: python validate_fields.py runs/gap6
This reads local artifacts and creates validation.json; it never contacts Allsolve.
The regular-grid fluxes are sampled estimates, not FE surface integrals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def simpson_weights(axis):
    axis = np.asarray(axis, dtype=float)
    if len(axis) < 3 or len(axis) % 2 != 1:
        raise ValueError("Composite Simpson quadrature requires an odd number of points >=3")
    steps = np.diff(axis)
    if not np.allclose(steps, steps[0], rtol=1e-8, atol=1e-12) or steps[0] <= 0:
        raise ValueError("Sample axis must be strictly increasing and uniformly spaced")
    weights = np.ones(len(axis))
    weights[1:-1:2] = 4
    weights[2:-1:2] = 2
    return weights * steps[0] / 3


def get_array(samples, name):
    if name not in samples or samples[name] is None:
        raise ValueError(f"Missing output: {name}")
    result = np.asarray(samples[name], dtype=float).reshape(-1)
    if not np.all(np.isfinite(result)):
        raise ValueError(f"Nonfinite values in {name}")
    return result


def unpack_samples(state, samples):
    shape = tuple(int(n) for n in state["grid_shape"])
    count = int(np.prod(shape))
    xyz = get_array(samples, "sample_xyz_m")
    vector = get_array(samples, "sample_vector")
    scalar = get_array(samples, "sample_scalar")
    volume = get_array(samples, "gas_volume_m3")
    if xyz.size != count * 3 or vector.size != count * 3 or scalar.size != count:
        raise ValueError("Point/vector/scalar array lengths disagree with state.grid_shape")
    if volume.size != 1:
        raise ValueError("gas_volume_m3 must contain one scalar")
    xyz = xyz.reshape(*shape, 3)
    axes = [xyz[:, 0, 0, 0], xyz[0, :, 0, 1], xyz[0, 0, :, 2]]
    expected = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    if not np.allclose(xyz, expected, rtol=1e-8, atol=1e-11):
        raise ValueError("Coordinates do not follow the expected x/y/z tensor-grid ordering")
    dimensions = [state["length_m"], state["gap_m"], state["span_m"]]
    for axis, dimension in zip(axes, dimensions):
        if not np.isclose(axis[0], 0, atol=1e-11) or not np.isclose(axis[-1], dimension, atol=1e-11):
            raise ValueError("Sample domain does not match case dimensions")
    weights = [simpson_weights(axis) for axis in axes]
    return axes, weights, vector.reshape(*shape, 3), scalar.reshape(shape), float(volume[0])


def channel_reference(state, y, z, terms=None):
    """Finite Fourier solution, normalized by its exact cross-section integral."""
    h, width = float(state["gap_m"]), float(state["span_m"])
    mu, flow = float(state["mu_pa_s"]), float(state["flow_m3_s"])
    terms = terms or int(state.get("reference", {}).get("series_terms", 15))
    odd = np.arange(1, 2 * terms, 2, dtype=float)
    correction = 96 / np.pi**4 * np.sum(
        1 / odd**4 - 2 * h / (np.pi * width) * np.tanh(odd * np.pi * width / (2 * h)) / odd**5)
    gradient = 12 * mu * flow / (width * h**3 * correction)
    yy, zz = np.meshgrid(y, z, indexing="ij")
    velocity = np.zeros_like(yy)
    for n in odd:
        k = n * np.pi / h
        ratio = (np.exp(k * (zz - width)) + np.exp(-k * zz)) / (1 + np.exp(-k * width))
        velocity += (1 - ratio) * np.sin(k * yy) / n**3
    velocity *= 4 * gradient * h**2 / (mu * np.pi**3)
    return velocity, float(gradient)


def gate(value, limit, *, minimum=False):
    value, limit = float(value), float(limit)
    return {"value": value, "limit": limit, "comparison": ">=" if minimum else "<=",
            "pass": bool(np.isfinite(value) and (value >= limit if minimum else value <= limit))}


def validate_flow(state, samples):
    axes, weights, velocity, pressure, volume = unpack_samples(state, samples)
    x, y, z = axes
    wx, wy, wz = weights
    length, gap, width = [float(state[k]) for k in ("length_m", "gap_m", "span_m")]
    target_flow, mean_velocity = float(state["flow_m3_s"]), float(state["flow_m3_s"]) / (gap * width)
    area_weights = wy[:, None] * wz[None, :]
    integrate_section = lambda values: np.einsum("ijk,jk->i", values, area_weights)
    q_sections = integrate_section(velocity[..., 0])
    mean_pressure = integrate_section(pressure) / (gap * width)
    interior = (x >= .2 * length - 1e-12) & (x <= .8 * length + 1e-12)
    if np.count_nonzero(interior) < 3:
        raise ValueError("Not enough axial sections in the pressure-fit range")
    slope, intercept = np.polyfit(x[interior], mean_pressure[interior], 1)
    gradient = -float(slope)
    fitted = slope * x[interior] + intercept
    residual_rms = float(np.sqrt(np.mean((mean_pressure[interior] - fitted)**2)))
    total_variation = float(np.sum((mean_pressure[interior] - np.mean(mean_pressure[interior]))**2))
    fit_r_squared = float(1 - np.sum((mean_pressure[interior] - fitted)**2) / total_variation) if total_variation > 0 else 0.
    reference_velocity, reference_gradient = channel_reference(state, y, z)
    reference_sample_flow = float(np.sum(reference_velocity * area_weights))
    quadrature_ratio = reference_sample_flow / target_flow
    if quadrature_ratio <= 0:
        raise ValueError("Nonpositive analytical sample flux")
    pressure_drop = gradient * length
    surface_drop = float(mean_pressure[0] - mean_pressure[-1])
    reference_drop = reference_gradient * length
    reference_norm_squared = float(np.sum(reference_velocity**2 * area_weights))
    error_squared = np.mean(np.sum((velocity[interior, ..., 0] - reference_velocity)**2 * area_weights, axis=(1, 2)))
    profile_l2 = float(np.sqrt(error_squared / reference_norm_squared))
    transverse_squared = np.mean(np.sum(np.sum(velocity[interior, ..., 1:]**2, axis=-1) * area_weights, axis=(1, 2)))
    transverse_rms_relative = float(np.sqrt(transverse_squared / (gap * width)) / mean_velocity)
    wall_mask = np.zeros(velocity.shape[:-1], dtype=bool)
    wall_mask[:, [0, -1], :] = True
    wall_mask[:, :, [0, -1]] = True
    wall_speed_relative = float(np.max(np.linalg.norm(velocity[wall_mask], axis=-1)) / mean_velocity)
    mismatch = float(abs(q_sections[-1] - q_sections[0]) / max(abs(q_sections[0]), target_flow * 1e-12))
    section_spread = float(np.ptp(q_sections) / max(abs(np.median(q_sections)), target_flow * 1e-12))
    # This divides by analytical sampling bias; it is a diagnostic, not an FE integral.
    corrected_inlet_error = float(abs(q_sections[0] / reference_sample_flow - 1))
    nominal_volume = length * gap * width
    checks = {
        "gas_volume_relative_error": gate(abs(volume / nominal_volume - 1), 1e-6),
        "sampled_inlet_outlet_flux_relative_mismatch": gate(mismatch, .01),
        "sampled_all_sections_flux_relative_range": gate(section_spread, .02),
        "sampled_inlet_error_after_analytic_quadrature_normalization": gate(corrected_inlet_error, .01),
        "developed_pressure_drop_relative_error": gate(abs(pressure_drop / reference_drop - 1), .05),
        "developed_velocity_profile_relative_l2_error": gate(profile_l2, .05),
        "transverse_velocity_rms_over_mean_velocity": gate(transverse_rms_relative, .02),
        "maximum_wall_speed_over_mean_velocity": gate(wall_speed_relative, 1e-5),
        "pressure_fit_r_squared": gate(fit_r_squared, .995, minimum=True),
    }
    fe_names = ["fe_inlet_flux_m3_s", "fe_outlet_flux_m3_s",
                "fe_inlet_mean_pressure_pa", "fe_outlet_mean_pressure_pa"]
    missing_fe = [name for name in fe_names if name not in samples]
    if missing_fe:
        direct_fe = {"status": "not_present", "missing_outputs": missing_fe}
    else:
        fe_values = {}
        for name in fe_names:
            value = get_array(samples, name)
            if value.size != 1:
                raise ValueError(f"{name} must contain one scalar")
            fe_values[name] = float(value[0])
        fe_in, fe_out = [fe_values[name] for name in fe_names[:2]]
        fe_pressure_drop = fe_values[fe_names[2]] - fe_values[fe_names[3]]
        fe_mismatch = abs(fe_out - fe_in) / max(abs(fe_in), target_flow * 1e-12)
        checks.update({
            "direct_fe_inlet_outlet_flux_relative_mismatch": gate(fe_mismatch, .01),
            "direct_fe_inlet_flux_relative_error": gate(abs(fe_in / target_flow - 1), .01),
            "direct_fe_outlet_flux_relative_error": gate(abs(fe_out / target_flow - 1), .01),
            "direct_fe_surface_pressure_drop_relative_error": gate(abs(fe_pressure_drop / reference_drop - 1), .05),
        })
        direct_fe = {"status": "present", **fe_values,
                     "surface_mean_pressure_drop_pa": fe_pressure_drop,
                     "surface_hydraulic_power_w": fe_pressure_drop * fe_out}
    return {
        "status": "pass" if all(check["pass"] for check in checks.values()) else "fail",
        "checks": checks,
        "direct_fe": direct_fe,
        "expected_mean_velocity_m_s": mean_velocity,
        "expected_flow_m3_s": target_flow,
        "reference_pressure_gradient_pa_m": reference_gradient,
        "reference_pressure_drop_pa": reference_drop,
        "developed_pressure_gradient_pa_m": gradient,
        "developed_pressure_drop_pa": pressure_drop,
        "surface_mean_pressure_drop_pa": surface_drop,
        "surface_mean_pressure_drop_relative_error": float(abs(surface_drop / reference_drop - 1)),
        "developed_resistance_pa_s_m3": pressure_drop / target_flow,
        "reference_resistance_pa_s_m3": reference_drop / target_flow,
        "developed_hydraulic_power_w": pressure_drop * target_flow,
        "surface_hydraulic_power_w": surface_drop * target_flow,
        "pressure_fit_x_range_m": [float(x[interior][0]), float(x[interior][-1])],
        "pressure_fit_residual_rms_pa": residual_rms,
        "sampled_inlet_flux_m3_s": float(q_sections[0]),
        "sampled_outlet_flux_m3_s": float(q_sections[-1]),
        "analytic_profile_sampled_flux_m3_s": reference_sample_flow,
        "analytic_profile_quadrature_relative_bias": quadrature_ratio - 1,
        "analytic_bias_corrected_median_flux_m3_s_diagnostic": float(np.median(q_sections) / quadrature_ratio),
        "minimum_axial_velocity_m_s": float(np.min(velocity[..., 0])),
        "maximum_axial_velocity_m_s": float(np.max(velocity[..., 0])),
        "sampled_sections": {"x_m": x.tolist(), "mean_pressure_pa": mean_pressure.tolist(),
                             "volume_flux_m3_s": q_sections.tolist()},
    }


def validate_electric(state, samples):
    axes, weights, electric_field, potential, volume = unpack_samples(state, samples)
    length, gap, width = [float(state[k]) for k in ("length_m", "gap_m", "span_m")]
    voltage = float(state["voltage_v"])
    if voltage == 0:
        raise ValueError("Uniform-field benchmark requires nonzero plate voltage")
    wx, wy, wz = weights
    volume_weights = wx[:, None, None] * wy[None, :, None] * wz[None, None, :]
    nominal_volume = length * gap * width
    expected_field = np.array([0., -voltage / gap, 0.])
    expected_potential = voltage * axes[1][None, :, None] / gap
    field_error_squared = np.sum((electric_field - expected_field)**2, axis=-1)
    field_l2 = float(np.sqrt(np.sum(field_error_squared * volume_weights) / nominal_volume) / abs(voltage / gap))
    potential_error = potential - expected_potential
    potential_l2 = float(np.sqrt(np.sum(potential_error**2 * volume_weights) / nominal_volume) / abs(voltage))
    mean_field = np.sum(electric_field * volume_weights[..., None], axis=(0, 1, 2)) / nominal_volume
    boundary_error = float(max(np.max(np.abs(potential[:, 0, :])), np.max(np.abs(potential[:, -1, :] - voltage))) / abs(voltage))
    checks = {
        "gas_volume_relative_error": gate(abs(volume / nominal_volume - 1), 1e-6),
        "uniform_field_relative_l2_error": gate(field_l2, .01),
        "linear_potential_rms_error_over_voltage": gate(potential_l2, .01),
        "plate_potential_maximum_error_over_voltage": gate(boundary_error, 1e-5),
    }
    return {
        "status": "pass" if all(check["pass"] for check in checks.values()) else "fail",
        "checks": checks,
        "expected_electric_field_v_m": expected_field.tolist(),
        "volume_mean_electric_field_v_m": mean_field.tolist(),
        "potential_min_v": float(np.min(potential)), "potential_max_v": float(np.max(potential)),
        "maximum_field_relative_error": float(np.sqrt(np.max(field_error_squared)) / abs(voltage / gap)),
    }


def validate_case(folder):
    folder = Path(folder).resolve()
    state_bytes = (folder / "state.json").read_bytes()
    state = json.loads(state_bytes.decode("utf-8"))
    result = {
        "case": state.get("case", folder.name),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": {k: state.get(k) for k in ("project_id", "project_url", "mesh_id", "mesh_job_id",
                   "flow_simulation_id", "flow_job_id", "electric_simulation_id", "electric_job_id")},
        "grid_shape": state["grid_shape"],
        "quadrature": "Composite Simpson in y/z; mean pressure fit over x=20–80% of duct length",
        "mesh_convergence": {"status": "not_evaluated", "note": "A passing single mesh checks this benchmark only; compare an independently refined mesh before claiming mesh convergence."},
        "limitations": [
            "Grid-derived flux and surface pressure use sampled points; the optional direct_fe group uses finite-element boundary integration.",
            "Analytical quadrature-bias normalization is reported as a diagnostic and assumes the developed profile.",
            "Developed pressure drop extrapolates the fitted internal gradient over full length; actual inlet/outlet mean difference is also reported.",
            "This is a fixed-property cold pilot benchmark, with no soot charging, hot exhaust chemistry, or emission certification.",
        ],
    }
    result["source"]["file_sha256"] = {"state.json": hashlib.sha256(state_bytes).hexdigest()}
    for name, validator in [("flow", validate_flow), ("electric", validate_electric)]:
        path = folder / f"{name}_samples.json"
        if not path.exists():
            result[name] = {"status": "pending", "reason": f"Missing {path.name}"}
            continue
        try:
            sample_bytes = path.read_bytes()
            result["source"]["file_sha256"][path.name] = hashlib.sha256(sample_bytes).hexdigest()
            result[name] = validator(state, json.loads(sample_bytes.decode("utf-8")))
        except (ValueError, KeyError, TypeError) as error:
            result[name] = {"status": "invalid_export", "reason": str(error)}
    result["all_field_benchmark_checks_passed"] = all(result[name]["status"] == "pass" for name in ("flow", "electric"))
    result["passed"] = result["all_field_benchmark_checks_passed"]
    return result


def compare_meshes(coarse_folder, fine_folder):
    """Compare two completed benchmark cases, with nested tensor sampling grids."""
    coarse_folder, fine_folder = Path(coarse_folder).resolve(), Path(fine_folder).resolve()
    coarse, fine = validate_case(coarse_folder), validate_case(fine_folder)
    coarse_state = json.loads((coarse_folder / "state.json").read_text(encoding="utf-8"))
    fine_state = json.loads((fine_folder / "state.json").read_text(encoding="utf-8"))
    parameters = ["length_m", "gap_m", "span_m", "flow_m3_s", "mu_pa_s", "rho_kg_m3", "voltage_v"]
    if not all(np.isclose(float(coarse_state[k]), float(fine_state[k]), rtol=1e-12, atol=1e-15) for k in parameters):
        raise ValueError("Mesh convergence requires identical physical parameters")
    if not float(fine_state["mesh_size_max_m"]) < float(coarse_state["mesh_size_max_m"]):
        raise ValueError("Fine case must have a strictly smaller mesh-size setting")
    if coarse_state.get("mesh_id") == fine_state.get("mesh_id"):
        raise ValueError("Two independent mesh IDs are required")
    if not coarse["passed"] or not fine["passed"]:
        return {"status": "not_ready", "passed": False, "reason": "Both field benchmarks must pass first",
                "coarse_source": coarse["source"], "fine_source": fine["source"],
                "coarse_benchmark_status": {k: coarse[k]["status"] for k in ("flow", "electric")},
                "fine_benchmark_status": {k: fine[k]["status"] for k in ("flow", "electric")}}
    cs = json.loads((coarse_folder / "flow_samples.json").read_text(encoding="utf-8"))
    fs = json.loads((fine_folder / "flow_samples.json").read_text(encoding="utf-8"))
    c_axes, c_weights, c_velocity, _, _ = unpack_samples(coarse_state, cs)
    f_axes, _, f_velocity, _, _ = unpack_samples(fine_state, fs)
    indices = []
    for c_axis, f_axis in zip(c_axes, f_axes):
        index = np.searchsorted(f_axis, c_axis)
        index = np.clip(index, 0, len(f_axis) - 1)
        if not np.allclose(f_axis[index], c_axis, rtol=1e-8, atol=1e-11):
            raise ValueError("Velocity comparison requires coarse coordinates nested in the fine grid")
        indices.append(index)
    fine_on_coarse = f_velocity[np.ix_(*indices)]
    length = float(coarse_state["length_m"])
    interior = (c_axes[0] >= .2 * length - 1e-12) & (c_axes[0] <= .8 * length + 1e-12)
    area_weights = c_weights[1][:, None] * c_weights[2][None, :]
    delta_squared = np.sum((c_velocity[interior] - fine_on_coarse[interior])**2, axis=-1)
    reference_squared = np.sum(fine_on_coarse[interior]**2, axis=-1)
    relative_velocity_change = float(np.sqrt(np.sum(delta_squared * area_weights) / np.sum(reference_squared * area_weights)))
    c_dp, f_dp = [data["flow"]["developed_pressure_drop_pa"] for data in (coarse, fine)]
    c_surface, f_surface = [data["flow"]["surface_mean_pressure_drop_pa"] for data in (coarse, fine)]
    pressure_change = abs(c_dp - f_dp) / abs(f_dp)
    surface_change = abs(c_surface - f_surface) / abs(f_surface)
    checks = {
        "developed_pressure_drop_relative_change": gate(pressure_change, .03),
        "velocity_field_relative_l2_change_at_common_samples": gate(relative_velocity_change, .03),
        "surface_mean_pressure_drop_relative_change": gate(surface_change, .05),
    }
    direct_both = all(data["flow"]["direct_fe"]["status"] == "present" for data in (coarse, fine))
    if direct_both:
        c_q, f_q = [data["flow"]["direct_fe"]["fe_outlet_flux_m3_s"] for data in (coarse, fine)]
        checks["direct_fe_outlet_flux_relative_change"] = gate(abs(c_q - f_q) / abs(f_q), .01)
    passed = all(check["pass"] for check in checks.values())
    return {
        "status": "pass" if passed else "fail", "passed": passed,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "coarse_source": coarse["source"], "fine_source": fine["source"],
        "coarse_mesh_size_max_m": coarse_state["mesh_size_max_m"],
        "fine_mesh_size_max_m": fine_state["mesh_size_max_m"],
        "coarse_grid_shape": coarse_state["grid_shape"], "fine_grid_shape": fine_state["grid_shape"],
        "checks": checks,
        "coarse_developed_pressure_drop_pa": c_dp, "fine_developed_pressure_drop_pa": f_dp,
        "coarse_analytic_profile_relative_l2_error": coarse["flow"]["checks"]["developed_velocity_profile_relative_l2_error"]["value"],
        "fine_analytic_profile_relative_l2_error": fine["flow"]["checks"]["developed_velocity_profile_relative_l2_error"]["value"],
        "interpretation": "Agreement between two meshes for this straight-channel benchmark; this is not a general discretization error bound or validation of other exhaust physics.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_folder", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-coarse", type=Path,
                        help="Compare this fine case to a coarse case and write a separate convergence report")
    args = parser.parse_args()
    result = validate_case(args.case_folder)
    output = args.output or args.case_folder / "validation.json"
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"case": result["case"], "flow": result["flow"]["status"],
                      "electric": result["electric"]["status"], "output": str(output.resolve())}))
    if args.compare_coarse:
        comparison = compare_meshes(args.compare_coarse, args.case_folder)
        convergence_path = args.case_folder.resolve().parent / "convergence_fields.json"
        convergence_path.write_text(json.dumps(comparison, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"convergence": comparison["status"], "output": str(convergence_path)}))


if __name__ == "__main__":
    main()
