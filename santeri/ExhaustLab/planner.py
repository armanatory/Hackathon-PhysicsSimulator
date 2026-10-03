"""Bounded inverse-design screening for a cylindrical filter installation.

This is a homogeneous axial Darcy cartridge, not a resolved wall-flow DPF.
Capture is an entered supplier specification. Thermal history is a local,
single-node heat-retention screen, not soot oxidation or regeneration kinetics.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "runs" / "dpf_cloud_manifest.json"
GAS_R = 287.05  # dry-air approximation, J/(kg K)

ASSUMPTIONS = [
    "Pressure represents a homogeneous axial porous cartridge, not resolved wall-flow DPF channels. Effective permeability must be calibrated for the selected cartridge family.",
    "Filter capture is an entered specification; the optimizer does not predict filtration efficiency, soot accumulation, chemistry, or emissions compliance.",
    "Clean and entered loaded resistance states are screened independently at every duty point; loading is not evolved over time.",
    "Gas density uses absolute downstream pressure and an ideal dry-air approximation; viscosity uses Sutherland's law. Candidates exceeding a 10% pressure-to-absolute-pressure ratio or pipe Mach 0.3 are excluded.",
    "Pipe friction uses a local Churchill correlation and entered housing loss coefficient; the cloud cartridge solves do not validate turbulent housing or pipe flow.",
    "Thermal history is a local uniform filter-node balance with entered heat-transfer effectiveness, lateral heat loss and insulation. Radiation, end losses, spatial gradients and soot-reaction heat are omitted.",
    "Time above an entered temperature threshold is a heat-retention screen, not evidence that a filter regenerates or burns soot safely.",
    "Cost and minimum filter volume are entered engineering assumptions. Demo defaults are illustrative and are not measured supplier properties or quoted prices.",
    "Optimal means best feasible member of the finite candidate grid for the selected objective; alternative feasible tradeoffs are reported.",
]


def get_defaults() -> dict:
    """Return a new editable demonstration input, never measured engine data."""
    return {
        "schema_version": 1,
        "duty_cycle": [
            {"name": "Warm-up", "duration_s": 180, "mass_flow_kg_s": 0.027, "inlet_temp_c": 140},
            {"name": "Partial load", "duration_s": 600, "mass_flow_kg_s": 0.028, "inlet_temp_c": 280},
            {"name": "Rated load", "duration_s": 300, "mass_flow_kg_s": 0.030, "inlet_temp_c": 445},
            {"name": "Idle", "duration_s": 180, "mass_flow_kg_s": 0.027, "inlet_temp_c": 170},
        ],
        "constraints": {
            "max_backpressure_kpa": 10.2, "max_outer_diameter_mm": 250,
            "max_total_length_mm": 1000, "target_capture_pct": 95,
            "budget_eur": 800, "min_hot_time_fraction": 0,
            "max_filter_temp_c": 700,
        },
        "material": {
            "effective_permeability_m2": 2e-8, "spec_capture_pct": 97,
            "bulk_density_kg_m3": 500, "heat_capacity_j_kgk": 900,
            "loaded_resistance_multiplier": 3, "minimum_filter_volume_l": 2,
            "pipe_roughness_mm": 0.05, "housing_loss_coefficient": 1.5,
        },
        "environment": {"pressure_kpa": 101.325, "ambient_temp_c": 20},
        "thermal": {
            "external_h_w_m2k": 15, "insulation_k_w_mk": 0.045,
            "hot_threshold_c": 260, "initial_temp_c": 20,
            "gas_heat_capacity_j_kgk": 1100, "gas_to_filter_effectiveness": 0.8,
        },
        "cost": {
            "fixed_eur": 160, "filter_eur_per_litre": 80,
            "insulation_eur_per_litre": 20, "housing_eur_per_m2": 70,
            "pipe_eur_per_m": 70,
        },
        "search": {
            "diameters_mm": [120, 160, 200], "lengths_mm": [150, 200, 250],
            "pipe_lengths_mm": [100, 300, 600], "insulation_mm": [0, 10, 20],
            "pipe_diameter_mm": 80, "objective": "lowest_cost",
        },
    }


def get_default_sources() -> dict:
    """Separate published reference data from illustrative editable assumptions."""
    return {
        "application": "Small stationary diesel engine",
        "reference": "FG Wilson P22-1, 16 kW prime, 50 Hz, Perkins 404A-22G1",
        "url": "https://www.fgwilson.jo/images/document/19867560/P22-1L_SKID_EN-XUZENrzO_pyIozFA7Ecs6g.pdf",
        "published": {"rated_exhaust_temperature_c": 445, "rated_exhaust_volume_m3_min": 3.6,
                      "maximum_exhaust_backpressure_kpa": 10.2},
        "inferred_mass_flow": "0.030 kg/s, rounded from 3.6 m³/min treated as hot actual flow at 445°C and 101.325 kPa using ideal dry-air density; not a published mass-flow measurement.",
        "illustrative": "Other operating-point mass flows, temperatures and all durations, filter properties/capture rating, loading multiplier, minimum volume, heat-transfer coefficients, packaging and costs are editable demonstration assumptions.",
        "scope": "The pressure limit is for the entire exhaust system. Include other equipment losses before allocating this allowance to a new installation.",
    }


def _number(value, path, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{path} must be a finite number")
    if not low <= value <= high:
        raise ValueError(f"{path} must be between {low:g} and {high:g}")
    return float(value)


def normalize_inputs(payload: dict) -> dict:
    """Fill omitted fields, validate units/envelope and reject unknown fields."""
    if not isinstance(payload, dict):
        raise ValueError("Planner inputs must be an object")
    result = get_defaults()
    for key, value in payload.items():
        if key not in result:
            raise ValueError(f"Unknown input: {key}")
        if key not in ("schema_version", "duty_cycle"):
            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object")
            for field, item in value.items():
                if field not in result[key]:
                    raise ValueError(f"Unknown input: {key}.{field}")
                result[key][field] = copy.deepcopy(item)
        else:
            result[key] = copy.deepcopy(value)
    if result["schema_version"] != 1:
        raise ValueError("Unsupported input schema_version")
    ranges = {
        "constraints": {
            "max_backpressure_kpa": (0.01, 100), "max_outer_diameter_mm": (20, 1000),
            "max_total_length_mm": (20, 5000), "target_capture_pct": (0, 100),
            "budget_eur": (0, 1e7), "min_hot_time_fraction": (0, 1),
            "max_filter_temp_c": (20, 900),
        },
        "material": {
            "effective_permeability_m2": (1e-11, 1e-5), "spec_capture_pct": (0, 100),
            "bulk_density_kg_m3": (50, 3000), "heat_capacity_j_kgk": (100, 2000),
            "loaded_resistance_multiplier": (1, 20), "minimum_filter_volume_l": (0.01, 100),
            "pipe_roughness_mm": (0, 2), "housing_loss_coefficient": (0, 30),
        },
        "environment": {"pressure_kpa": (50, 200), "ambient_temp_c": (-40, 60)},
        "thermal": {
            "external_h_w_m2k": (1, 100), "insulation_k_w_mk": (0.01, 1),
            "hot_threshold_c": (20, 750), "initial_temp_c": (-40, 750),
            "gas_heat_capacity_j_kgk": (700, 1500), "gas_to_filter_effectiveness": (0.05, 1),
        },
    }
    for section, fields in ranges.items():
        for field, bounds in fields.items():
            result[section][field] = _number(result[section][field], f"{section}.{field}", *bounds)
    for field in result["cost"]:
        result["cost"][field] = _number(result["cost"][field], f"cost.{field}", 0, 1e6)
    cycle = result["duty_cycle"]
    if not isinstance(cycle, list) or not 1 <= len(cycle) <= 24:
        raise ValueError("duty_cycle requires between 1 and 24 operating points")
    for i, point in enumerate(cycle):
        if not isinstance(point, dict) or set(point) - {"name", "duration_s", "mass_flow_kg_s", "inlet_temp_c"}:
            raise ValueError(f"duty_cycle[{i}] contains unknown fields")
        if not isinstance(point.get("name"), str) or not point["name"].strip() or len(point["name"]) > 80:
            raise ValueError(f"duty_cycle[{i}].name needs 1–80 characters")
        for field, bounds in {"duration_s": (1, 86400), "mass_flow_kg_s": (0.0001, 0.2), "inlet_temp_c": (0, 750)}.items():
            point[field] = _number(point.get(field), f"duty_cycle[{i}].{field}", *bounds)
    search = result["search"]
    for field, bounds in {"diameters_mm": (40, 500), "lengths_mm": (40, 1000), "pipe_lengths_mm": (0, 3000), "insulation_mm": (0, 100)}.items():
        values = search[field]
        if not isinstance(values, list) or not 1 <= len(values) <= 12:
            raise ValueError(f"search.{field} needs 1–12 values")
        search[field] = sorted(set(_number(v, f"search.{field}", *bounds) for v in values))
    count = math.prod(len(search[key]) for key in ("diameters_mm", "lengths_mm", "pipe_lengths_mm", "insulation_mm"))
    if count > 2500:
        raise ValueError("Search contains more than 2500 candidates; reduce the grid")
    search["pipe_diameter_mm"] = _number(search["pipe_diameter_mm"], "search.pipe_diameter_mm", 20, 300)
    if search["objective"] not in ("lowest_cost", "smallest_volume", "lowest_backpressure"):
        raise ValueError("search.objective must be lowest_cost, smallest_volume or lowest_backpressure")
    return result


def air_viscosity(temperature_k: float) -> float:
    """Sutherland dry-air approximation in Pa s; never accepts Celsius."""
    if not math.isfinite(temperature_k) or temperature_k <= 0:
        raise ValueError("temperature_k must be positive")
    return 1.716e-5 * (temperature_k / 273.15) ** 1.5 * (273.15 + 110.4) / (temperature_k + 110.4)


def gas_properties(mass_flow_kg_s, temperature_c, pressure_kpa):
    temperature_k = temperature_c + 273.15
    rho = pressure_kpa * 1000 / (GAS_R * temperature_k)
    return {"density_kg_m3": rho, "volume_flow_m3_s": mass_flow_kg_s / rho,
            "viscosity_pa_s": air_viscosity(temperature_k), "temperature_k": temperature_k}


def darcy_pressure_drop(mu, length_m, flow_m3_s, area_m2, permeability_m2):
    return mu * length_m * flow_m3_s / (area_m2 * permeability_m2)


def lateral_conductance(diameter_m, length_m, insulation_m, h, k):
    """Series cylindrical insulation/convection resistance, W/K; end losses omitted."""
    if length_m == 0:
        return 0.0
    inner_radius = diameter_m / 2
    outer_radius = inner_radius + insulation_m
    resistance = math.log(outer_radius / inner_radius) / (2 * math.pi * k * length_m)
    resistance += 1 / (h * 2 * math.pi * outer_radius * length_m)
    return 1 / resistance


def thermal_step(start_c, source_c, ambient_c, heat_input_w_k, loss_w_k, capacity_j_k, duration_s, threshold_c):
    """Exact single-node step and threshold crossing for constant coefficients."""
    conductance = heat_input_w_k + loss_w_k
    equilibrium = (heat_input_w_k * source_c + loss_w_k * ambient_c) / conductance
    rate = conductance / capacity_j_k
    decay = math.exp(-rate * duration_s)
    end = equilibrium + (start_c - equilibrium) * decay
    mean = equilibrium + (start_c - equilibrium) * (-math.expm1(-rate * duration_s)) / (rate * duration_s)
    if min(start_c, end) >= threshold_c:
        hot_time = duration_s
    elif max(start_c, end) < threshold_c:
        hot_time = 0.0
    else:
        ratio = (threshold_c - equilibrium) / (start_c - equilibrium)
        if ratio <= 0:  # asymptotic threshold, including floating-point underflow
            hot_time = 0.0 if end > start_c else duration_s
        else:
            crossing = max(0.0, min(duration_s, -math.log(ratio) / rate))
            hot_time = duration_s - crossing if end > start_c else crossing
    return {"end_c": end, "mean_c": mean, "hot_time_s": hot_time, "equilibrium_c": equilibrium}


def _friction_factor(reynolds, relative_roughness):
    if reynolds < 2000:
        return 64 / reynolds
    a = (2.457 * math.log(1 / ((7 / reynolds) ** 0.9 + 0.27 * relative_roughness))) ** 16
    b = (37530 / reynolds) ** 16
    return 8 * ((8 / reynolds) ** 12 + (a + b) ** -1.5) ** (1 / 12)


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hash_map(hashes, problems):
    """Return checked paths; every source must remain inside this case root."""
    checked = {}
    if not isinstance(hashes, dict) or not hashes:
        problems.append("source hashes required")
        return checked
    for relative, expected in hashes.items():
        if not isinstance(relative, str):
            problems.append("source path must be a string")
            continue
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(ROOT):
            problems.append("source path leaves ExhaustLab")
        elif not source.is_file() or not isinstance(expected, str) or _file_hash(source) != expected:
            problems.append(f"source hash mismatch: {relative}")
        else:
            checked[source.name] = source
    return checked


def _aggregate_evidence(record, label, errors, check_sources=False):
    """Bind manifest summary to its hashed numerical/batch evidence."""
    if not isinstance(record, dict):
        errors.append(f"{label}: evidence metadata required")
        return None
    problems = []
    paths = _verify_hash_map({record.get("evidence_path"): record.get("evidence_sha256")}, problems)
    evidence = None
    if paths:
        try:
            evidence = json.loads(next(iter(paths.values())).read_text(encoding="utf-8"))
            if not isinstance(evidence, dict):
                raise ValueError("evidence must be an object")
            if check_sources:
                _verify_hash_map(evidence.get("source_hashes"), problems)
            for key in ("passed", "coarse_mesh_m", "fine_mesh_m", "pressure_relative_change",
                        "outlet_temperature_change_k", "max_active_jobs", "peak_active_jobs"):
                if key in record and record[key] != evidence.get(key):
                    problems.append(f"{key} differs from archived evidence")
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    errors.extend(f"{label}: {problem}" for problem in problems)
    return evidence if not problems else None


def load_cloud_dataset(path=None) -> dict:
    """Read immutable cloud outputs, hash-gate every usable case, expose safe metadata.

    Missing, failed or replaced sources remain visible but never authorize a cloud
    result. Paths in untrusted manifests are constrained to this case directory.
    """
    path = Path(path) if path else MANIFEST
    if not path.exists():
        return {"available": False, "trusted": False, "status": "not_run", "cases": [], "errors": ["Cloud manifest has not been produced"]}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"available": True, "trusted": False, "status": "invalid", "cases": [], "errors": [str(exc)]}
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        return {"available": True, "trusted": False, "status": "invalid", "cases": [], "errors": ["Cloud manifest requires a cases array"]}
    cases = []
    errors = []
    for raw in manifest.get("cases", []):
        if not isinstance(raw, dict):
            errors.append("Cloud case must be an object")
            continue
        case = copy.deepcopy(raw)
        label = str(case.get("case", "unknown"))
        problems = []
        validation = case.get("validation", {})
        if not isinstance(validation, dict):
            validation = {}
        if validation.get("passed") is not True:
            problems.append("field validation has not passed")
        hashes = case.get("source_hashes", {})
        if isinstance(hashes, list):
            try:
                hashes = {item["path"]: item["sha256"] for item in hashes}
            except (KeyError, TypeError):
                hashes = {}
        checked_paths = _verify_hash_map(hashes, problems)
        if not {"state.json", "samples.json", "validation.json"} <= checked_paths.keys():
            problems.append("hashed state, samples and validation sources required")
        else:
            try:
                state = json.loads(checked_paths["state.json"].read_text(encoding="utf-8"))
                archived_validation = json.loads(checked_paths["validation.json"].read_text(encoding="utf-8"))
                for key in ("case", "diameter_m", "length_m", "project_id", "simulation_job_id"):
                    if case.get(key) != state.get(key):
                        problems.append(f"{key} differs from archived state")
                if state.get("simulation_status") != "JobStatusType.SUCCESS":
                    problems.append("archived simulation did not succeed")
                if archived_validation.get("passed") is not True or any(value is not True for value in archived_validation.get("gates", {}).values()):
                    problems.append("archived validation did not pass")
                for key in ("pressure_factor", "thermal_factor"):
                    if case.get(key) != archived_validation.get(key):
                        problems.append(f"{key} differs from archived validation")
                if validation != archived_validation:
                    problems.append("manifest validation differs from archived validation")
            except (OSError, ValueError, AttributeError) as exc:
                problems.append(f"invalid archived case data: {exc}")
        try:
            _number(case.get("diameter_m"), "cloud.diameter_m", 0.04, 0.5)
            _number(case.get("length_m"), "cloud.length_m", 0.04, 1)
            _number(case.get("pressure_factor"), "cloud.pressure_factor", 0.95, 1.05)
            if not case.get("project_id") or not case.get("flow_job_id", case.get("simulation_job_id", case.get("job_id", case.get("pressure_job_id")))):
                problems.append("project and pressure job IDs required")
        except ValueError as exc:
            problems.append(str(exc))
        # A thermal result authorizes a steady plug-flow coefficient only.
        if case.get("thermal_factor") is not None:
            thermal_validation = validation.get("thermal_passed", validation.get("passed"))
            try:
                _number(case["thermal_factor"], "cloud.thermal_factor", 0.8, 1.2)
                if thermal_validation is not True:
                    problems.append("thermal validation has not passed")
            except ValueError as exc:
                problems.append(str(exc))
        case["trusted"] = not problems
        case["trust_errors"] = problems
        cases.append(case)
        errors.extend(f"{label}: {problem}" for problem in problems)
    if manifest.get("ready") is not True:
        errors.append("Cloud study is not declared ready")
    expected = manifest.get("expected_geometry_count")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1 or expected != len(cases):
        errors.append("Cloud geometry count differs from the declared complete study")
    geometries = {(case.get("diameter_m"), case.get("length_m")) for case in cases}
    if len(geometries) != len(cases):
        errors.append("Cloud geometry pairs must be unique")
    mesh = manifest.get("mesh_verification")
    mesh_evidence = _aggregate_evidence(mesh, "mesh verification", errors, check_sources=True)
    if not isinstance(mesh, dict) or mesh.get("passed") is not True or not mesh_evidence or mesh_evidence.get("passed") is not True:
        errors.append("Study mesh verification has not passed")
    concurrency = manifest.get("concurrency")
    batch_evidence = _aggregate_evidence(concurrency, "concurrency", errors)
    if isinstance(concurrency, dict):
        if concurrency.get("verified_geometry_count") != len(cases) or concurrency.get("requested_geometry_count") != expected:
            errors.append("Concurrency geometry counts differ from the study")
        if batch_evidence and set(batch_evidence.get("requested_cases", [])) != {case.get("case") for case in cases}:
            errors.append("Concurrency case list differs from the study")
    trusted = bool(cases) and not errors and all(case["trusted"] for case in cases)
    return {"available": True, "trusted": trusted, "status": "verified" if trusted else "unverified",
            "cases": cases, "errors": errors, "manifest_sha256": _file_hash(path),
            "ready": trusted, "expected_geometry_count": expected,
            "mesh_verification": mesh, "concurrency": concurrency, "solver": manifest.get("solver"),
            "manifest": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name}


def _cloud_case(dataset, diameter, length):
    matches = [case for case in dataset.get("cases", [])
               if case.get("trusted") is True
               and math.isclose(case.get("diameter_m", -1), diameter, rel_tol=0, abs_tol=1e-9)
               and math.isclose(case.get("length_m", -1), length, rel_tol=0, abs_tol=1e-9)]
    return matches[0] if matches else None


def _candidate(inputs, diameter_mm, length_mm, pipe_mm, insulation_mm, source=None):
    material, thermal, env, costs = (inputs[key] for key in ("material", "thermal", "environment", "cost"))
    diameter, length, pipe, insulation = (x / 1000 for x in (diameter_mm, length_mm, pipe_mm, insulation_mm))
    pipe_diameter = inputs["search"]["pipe_diameter_mm"] / 1000
    area = math.pi * diameter ** 2 / 4
    volume = area * length
    outer_d = diameter + 2 * insulation
    outer_pipe_d = pipe_diameter + 2 * insulation
    outer_area = math.pi * outer_d * length
    insulation_volume = math.pi / 4 * ((outer_d ** 2 - diameter ** 2) * length + (outer_pipe_d ** 2 - pipe_diameter ** 2) * pipe)
    price = costs["fixed_eur"] + costs["filter_eur_per_litre"] * volume * 1000
    price += costs["insulation_eur_per_litre"] * insulation_volume * 1000 + costs["housing_eur_per_m2"] * outer_area
    price += costs["pipe_eur_per_m"] * pipe
    pressure_factor = source["pressure_factor"] if source else 1.0
    ua_pipe = lateral_conductance(pipe_diameter, pipe, insulation, thermal["external_h_w_m2k"], thermal["insulation_k_w_mk"])
    ua_body = lateral_conductance(diameter, length, insulation, thermal["external_h_w_m2k"], thermal["insulation_k_w_mk"])
    # FE steady thermal factors are reported as evidence; the local transient
    # lumped-node coefficients remain explicitly entered and are not conflated.
    capacity = volume * material["bulk_density_kg_m3"] * material["heat_capacity_j_kgk"]
    temp = thermal["initial_temp_c"]
    peak = temp
    records = []
    heat_loss_j = 0
    pump_j = 0
    max_mach = 0
    for point in inputs["duty_cycle"]:
        mass = point["mass_flow_kg_s"]
        heat_capacity_rate = mass * thermal["gas_heat_capacity_j_kgk"]
        inlet = env["ambient_temp_c"] + (point["inlet_temp_c"] - env["ambient_temp_c"]) * math.exp(-ua_pipe / heat_capacity_rate)
        gas = gas_properties(mass, inlet, env["pressure_kpa"])
        q, rho, mu = (gas[key] for key in ("volume_flow_m3_s", "density_kg_m3", "viscosity_pa_s"))
        filter_dp = darcy_pressure_drop(mu, length, q, area, material["effective_permeability_m2"]) * pressure_factor
        pipe_area = math.pi * pipe_diameter ** 2 / 4
        velocity = q / pipe_area
        reynolds = rho * velocity * pipe_diameter / mu
        friction = _friction_factor(reynolds, material["pipe_roughness_mm"] / 1000 / pipe_diameter)
        pipe_dp = friction * pipe / pipe_diameter * rho * velocity ** 2 / 2
        housing_dp = material["housing_loss_coefficient"] * rho * velocity ** 2 / 2
        clean_dp = filter_dp + pipe_dp + housing_dp
        loaded_dp = filter_dp * material["loaded_resistance_multiplier"] + pipe_dp + housing_dp
        result = thermal_step(temp, inlet, env["ambient_temp_c"], heat_capacity_rate * thermal["gas_to_filter_effectiveness"],
                              ua_body, capacity, point["duration_s"], thermal["hot_threshold_c"])
        heat_loss_j += max(0, heat_capacity_rate * (point["inlet_temp_c"] - inlet) + ua_body * (result["mean_c"] - env["ambient_temp_c"])) * point["duration_s"]
        pump_j += loaded_dp * q * point["duration_s"]
        peak = max(peak, temp, result["end_c"])
        mach = velocity / math.sqrt(1.4 * GAS_R * gas["temperature_k"])
        max_mach = max(max_mach, mach)
        records.append({"name": point["name"], "duration_s": point["duration_s"], "mass_flow_kg_s": mass,
                        "gas_density_kg_m3": rho, "volume_flow_m3_s": q, "superficial_velocity_m_s": q / area,
                        "pipe_velocity_m_s": velocity, "pipe_reynolds": reynolds, "pipe_mach": mach,
                        "filter_inlet_temp_c": inlet, "start_filter_temp_c": temp, "end_filter_temp_c": result["end_c"],
                        "mean_filter_temp_c": result["mean_c"], "clean_backpressure_kpa": clean_dp / 1000,
                        "loaded_backpressure_kpa": loaded_dp / 1000, "hot_time_s": result["hot_time_s"]})
        temp = result["end_c"]
    cycle_time = sum(p["duration_s"] for p in records)
    hot_time = sum(p["hot_time_s"] for p in records)
    candidate = {
        "id": f"D{diameter_mm:g}-L{length_mm:g}-P{pipe_mm:g}-I{insulation_mm:g}",
        "diameter_mm": diameter_mm, "filter_length_mm": length_mm, "pipe_length_mm": pipe_mm,
        "insulation_mm": insulation_mm, "outer_diameter_mm": max(outer_d, outer_pipe_d) * 1000,
        "total_length_mm": length_mm + pipe_mm, "filter_volume_l": volume * 1000,
        "package_volume_l": math.pi / 4 * (outer_d ** 2 * length + outer_pipe_d ** 2 * pipe) * 1000,
        "cost_eur": price, "specified_capture_pct": material["spec_capture_pct"],
        "worst_loaded_backpressure_kpa": max(p["loaded_backpressure_kpa"] for p in records),
        "worst_clean_backpressure_kpa": max(p["clean_backpressure_kpa"] for p in records),
        "hot_time_fraction": hot_time / cycle_time, "hot_time_s": hot_time, "cycle_duration_s": cycle_time,
        "peak_filter_temp_c": peak, "end_filter_temp_c": temp, "cycle_heat_loss_kwh": heat_loss_j / 3.6e6,
        "ideal_pumping_energy_wh": pump_j / 3600, "max_pipe_mach": max_mach, "duty_results": records,
        "source": {"mode": "allsolve_pressure_verified" if source else "analytical",
                   "case": source.get("case") if source else None,
                   "project_id": source.get("project_id") if source else None,
                   "project_url": source.get("project_url") if source else None,
                   "simulation_job_id": source.get("simulation_job_id", source.get("flow_job_id")) if source else None,
                   "pressure_factor": pressure_factor,
                   "thermal_model": "local_lumped_heat_retention",
                   "steady_cloud_thermal_factor": source.get("thermal_factor") if source else None},
    }
    limits = inputs["constraints"]
    checks = [
        ("backpressure", candidate["worst_loaded_backpressure_kpa"], limits["max_backpressure_kpa"], "max"),
        ("outer_diameter", candidate["outer_diameter_mm"], limits["max_outer_diameter_mm"], "max"),
        ("total_length", candidate["total_length_mm"], limits["max_total_length_mm"], "max"),
        ("capture_specification", material["spec_capture_pct"], limits["target_capture_pct"], "min"),
        ("budget", price, limits["budget_eur"], "max"),
        ("hot_time_screen", candidate["hot_time_fraction"], limits["min_hot_time_fraction"], "min"),
        ("peak_filter_temperature", peak, limits["max_filter_temp_c"], "max"),
        ("minimum_filter_volume", volume * 1000, material["minimum_filter_volume_l"], "min"),
        ("low_compressibility_envelope", candidate["worst_loaded_backpressure_kpa"] / env["pressure_kpa"], 0.1, "max"),
        ("pipe_mach_envelope", max_mach, 0.3, "max"),
    ]
    violations = [{"constraint": name, "actual": actual, "limit": bound, "direction": direction}
                  for name, actual, bound, direction in checks
                  if (actual > bound + 1e-9 if direction == "max" else actual < bound - 1e-9)]
    candidate["violations"] = violations
    candidate["feasible"] = not violations
    return candidate


def _rank(candidate, objective):
    metrics = {"lowest_cost": "cost_eur", "smallest_volume": "package_volume_l", "lowest_backpressure": "worst_loaded_backpressure_kpa"}
    return (candidate[metrics[objective]], candidate["cost_eur"], candidate["package_volume_l"], candidate["id"])


def _pareto(candidates):
    metrics = ("cost_eur", "package_volume_l", "worst_loaded_backpressure_kpa")
    survivors = []
    for candidate in candidates:
        def dominates(other):
            pairs = [(other[key], candidate[key]) for key in metrics]
            return all(a <= b + 1e-9 for a, b in pairs) and any(a < b - 1e-9 for a, b in pairs)
        if not any(dominates(other) for other in candidates if other is not candidate):
            survivors.append(candidate)
    return sorted(survivors, key=lambda c: (c["cost_eur"], c["worst_loaded_backpressure_kpa"]))


def plan_design(payload: dict | None = None, cloud_dataset: dict | None = None) -> dict:
    """Optimize an explicit finite grid; do not extrapolate trusted cloud geometry."""
    inputs = normalize_inputs({} if payload is None else payload)
    dataset = cloud_dataset if cloud_dataset is not None else load_cloud_dataset()
    cloud_mode = dataset.get("trusted") is True
    search = inputs["search"]
    candidates = []
    missing_geometries = set()
    for d, l, p, i in itertools.product(search["diameters_mm"], search["lengths_mm"], search["pipe_lengths_mm"], search["insulation_mm"]):
        source = _cloud_case(dataset, d / 1000, l / 1000) if cloud_mode else None
        candidate = _candidate(inputs, d, l, p, i, source)
        if cloud_mode and source is None:
            missing_geometries.add((d, l))
            candidate["violations"].append({"constraint": "cloud_geometry_not_verified", "actual": [d, l], "limit": "exact cloud geometry required", "direction": "required"})
            candidate["feasible"] = False
        candidates.append(candidate)
    feasible = sorted((c for c in candidates if c["feasible"]), key=lambda c: _rank(c, search["objective"]))
    failure_counts = Counter(v["constraint"] for c in candidates for v in c["violations"])
    recommended = feasible[0] if feasible else None
    near_feasible = sorted((c for c in candidates if not c["feasible"]), key=lambda c: (len(c["violations"]), _rank(c, search["objective"])))[:5]
    return {
        "schema_version": 1, "mode": "allsolve_verified_screening" if cloud_mode else "analytic_screening",
        "status": "feasible" if feasible else "infeasible", "recommended": recommended,
        "pareto": _pareto(feasible), "candidates": candidates, "near_feasible": near_feasible,
        "summary": {"evaluated": len(candidates), "feasible": len(feasible), "rejected": len(candidates) - len(feasible),
                    "objective": search["objective"], "optimality": "finite candidate grid only",
                    "missing_cloud_geometries": [list(pair) for pair in sorted(missing_geometries)]},
        "constraint_failures": [{"constraint": name, "count": count} for name, count in failure_counts.most_common()],
        "provenance": {"cloud_status": dataset.get("status", "unavailable"), "cloud_errors": dataset.get("errors", []),
                       "manifest_sha256": dataset.get("manifest_sha256"), "source": "Allsolve Darcy pressure factors + local screening" if cloud_mode else "Local analytical screening; cloud unavailable or unverified",
                       "calibration": "Editable demonstration inputs; no measured engine or filter dataset supplied",
                       "pressure_parameter_scaling": "Linear Darcy scaling in viscosity, flow and inverse effective permeability; exact cloud geometry only",
                       "thermal": "Local lumped transient model; cloud steady temperature is separate validation evidence"},
        "assumptions": list(ASSUMPTIONS), "inputs": inputs,
    }


if __name__ == "__main__":
    result = plan_design()
    print(json.dumps({key: result[key] for key in ("mode", "status", "summary", "recommended")}, indent=2))
