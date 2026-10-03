"""Deterministic search bookkeeping and fixed gates for real Allsolve outputs.

No solver, surrogate, RCWA calculation, network call, or job launch occurs here.
The runner supplies completed SDK results and retains their cloud provenance.
"""
from __future__ import annotations

import math
import random
from numbers import Real


TOLERANCES = {
    "energy_absolute": 0.02,
    "incident_normalization_absolute": 0.02,
    "exit_backward_fraction_max": 0.001,
    "crosspolarized_fraction_max": 1e-4,
    "diffraction_cutoff_ratio_max": 0.9+1e-6,
    "material_admittance_absolute": 1e-8,
    "wavelength_frequency_absolute": 1e-8,
    "coherent_local_flux_fraction": 0.005,
    "internal_consistency_absolute": 1e-8,
}
GEOMETRY_PARAMETERS = ("period_nm", "fill_factor", "ridge_height_nm")
POWER_OUTPUTS = (
    "specified_incident_power_W", "entrance_forward_power_W", "entrance_backward_power_W",
    "exit_forward_power_W", "exit_backward_power_W", "entrance_crosspolarized_power_W",
    "exit_crosspolarized_power_W", "entrance_local_forward_power_W", "entrance_local_backward_power_W",
    "exit_local_forward_power_W", "exit_local_backward_power_W",
)
REQUIRED_OUTPUTS = POWER_OUTPUTS + (
    "candidate_id", "input_index", "wavelength_nm", "n_liquid", "period_nm", "fill_factor",
    "ridge_height_nm", "film_thickness_nm", "reflectance", "transmittance",
    "coherent_reflectance", "coherent_transmittance", "energy_residual",
    "incident_normalization_ratio", "exit_backward_fraction", "entrance_crosspolarized_fraction",
    "exit_crosspolarized_fraction", "exterior_diffraction_cutoff_ratio", "wavelength_frequency_ratio",
    "entrance_material_admittance_ratio", "exit_material_admittance_ratio",
    "entrance_net_flux_W", "exit_net_flux_W", "entrance_poynting_flux_W", "exit_poynting_flux_W",
    "entrance_local_directional_flux_W", "exit_local_directional_flux_W",
    "entrance_local_flux_identity_error_W", "exit_local_flux_identity_error_W",
    "entrance_coherent_local_flux_difference_W", "exit_coherent_local_flux_difference_W",
    "local_reflectance", "local_transmittance", "local_energy_residual",
)


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)


def _wavelengths(request, wavelengths=None):
    if wavelengths is None:
        count = request["wavelength_samples"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            raise ValueError("wavelength_samples must be an integer >=2")
        low = _number(request["wavelength_min_nm"], "wavelength_min_nm")
        high = _number(request["wavelength_max_nm"], "wavelength_max_nm")
        if not 0 < low < high:
            raise ValueError("Wavelength bounds must be positive and increasing")
        wavelengths = [low+(high-low)*i/(count-1) for i in range(count)]
    values = [_number(value, "wavelength_nm") for value in wavelengths]
    if not values or min(values) <= 0 or len(set(values)) != len(values):
        raise ValueError("Wavelengths must be positive, nonempty, and unique")
    return values


def generate_candidates(request):
    """Independent shuffled Latin-hypercube strata using a private seeded RNG."""
    count, seed = request["candidate_count"], request["seed"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 128:
        raise ValueError("candidate_count must be an integer in 1..128")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    film = _number(request["film_thickness_nm"], "film_thickness_nm")
    feature = _number(request["minimum_feature_nm"], "minimum_feature_nm")
    if film < 0 or feature <= 0:
        raise ValueError("Film thickness must be nonnegative and minimum feature positive")
    bounds = {}
    for name in GEOMETRY_PARAMETERS:
        supplied = request["geometry_bounds"][name]
        low, high = _number(supplied["min"], name+".min"), _number(supplied["max"], name+".max")
        if low > high:
            raise ValueError(f"{name} bounds must be ordered")
        bounds[name] = (low, high)
    pmin, _ = bounds["period_nm"]
    fmin, fmax = bounds["fill_factor"]
    if pmin <= 0 or not 0 < fmin <= fmax < 1:
        raise ValueError("Period must be positive and fill factors strictly between zero and one")
    if min(pmin*fmin, pmin*(1-fmax), bounds["ridge_height_nm"][0])+1e-9 < feature:
        raise ValueError("Search bounds violate the minimum ridge, gap, or height feature")
    rng = random.Random(seed)
    columns = {}
    for name in GEOMETRY_PARAMETERS:
        samples = [(stratum+rng.random())/count for stratum in range(count)]
        rng.shuffle(samples)
        low, high = bounds[name]
        columns[name] = [low+(high-low)*value for value in samples]
    total_solves = 2*len(_wavelengths(request))
    candidates = []
    for index in range(count):
        geometry = {name: columns[name][index] for name in GEOMETRY_PARAMETERS}
        geometry.update(film_thickness_nm=film,
                        width_nm=geometry["period_nm"]*geometry["fill_factor"],
                        gap_nm=geometry["period_nm"]*(1-geometry["fill_factor"]))
        candidates.append({"id": index, "geometry": geometry, "status": "queued", "score": None,
                           "wavelength_nm": None, "R_A": None, "R_B": None, "valid": False,
                           "verified": False, "completed_solves": 0, "total_solves": total_solves, "error": None})
    return candidates


def make_points(candidates, request, wavelengths=None):
    """Flat candidate, wavelength, input ordering; both inputs share every wavelength."""
    values = _wavelengths(request, wavelengths)
    liquids = request["liquids"]
    if not isinstance(liquids, list) or len(liquids) != 2:
        raise ValueError("Exactly two explicit liquid inputs are required")
    indices = [_number(liquid["n"], "n_liquid") for liquid in liquids]
    if min(indices) <= 0 or indices[0] == indices[1]:
        raise ValueError("Liquid indices must be positive and distinct")
    return [{"candidate_id": candidate["id"], "input_index": index, "wavelength_nm": wavelength,
             "n_liquid": indices[index],
             **{name: candidate["geometry"][name] for name in GEOMETRY_PARAMETERS},
             "film_thickness_nm": candidate["geometry"]["film_thickness_nm"]}
            for candidate in candidates for wavelength in values for index in (0, 1)]


def scalar_outputs(rawdata):
    """Decode SDK nostep, archived public_output_values, or flat numeric scalars.

    Nonfinite numeric values are retained for validate_outputs to reject. Boolean,
    text, complex, missing step tables, and multi-value entries are malformed.
    """
    if not isinstance(rawdata, dict):
        raise ValueError("Optical outputs must be a dictionary")
    values = rawdata.get("public_output_values", rawdata)
    if not isinstance(values, dict):
        raise ValueError("public_output_values must be a dictionary")
    values = values.get("nostep", values)
    if not isinstance(values, dict):
        raise ValueError("nostep must be a dictionary")
    result = {}
    for name, value in values.items():
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError(f"{name} must contain exactly one scalar")
            value = value[0]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a real numeric scalar")
        result[name] = float(value)
    return result


def validate_outputs(outputs):
    """Return errors under fixed physical and arithmetic gates; no tolerance fitting."""
    if not isinstance(outputs, dict):
        return ["Missing optical output dictionary"]
    errors = []
    for name in REQUIRED_OUTPUTS:
        try:
            _number(outputs.get(name), name)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        return errors
    o = outputs
    if o["candidate_id"] < 0 or o["candidate_id"] != int(o["candidate_id"]):
        errors.append("candidate_id must be a nonnegative integer")
    if o["input_index"] not in (0, 1):
        errors.append("input_index must be zero or one")
    if any(o[name] < 0 for name in POWER_OUTPUTS):
        errors.append("Directional powers must be nonnegative")
    if o["reflectance"] < -1e-8 or o["transmittance"] < -1e-8:
        errors.append("R/T must be >=-1e-8")
    pin, specified = o["entrance_forward_power_W"], o["specified_incident_power_W"]
    local_pin = o["entrance_local_forward_power_W"]
    if min(pin, specified, local_pin) <= 0:
        return errors+["Incident powers must be positive"]
    reflected, transmitted, exit_back = (o[name] for name in
        ("entrance_backward_power_W", "exit_forward_power_W", "exit_backward_power_W"))
    calculated = {
        "reflectance": reflected/pin, "transmittance": transmitted/pin,
        "coherent_reflectance": reflected/pin, "coherent_transmittance": transmitted/pin,
        "energy_residual": 1-(reflected+transmitted)/pin,
        "incident_normalization_ratio": pin/specified, "exit_backward_fraction": exit_back/pin,
        "entrance_crosspolarized_fraction": o["entrance_crosspolarized_power_W"]/pin,
        "exit_crosspolarized_fraction": o["exit_crosspolarized_power_W"]/pin,
        "local_reflectance": o["entrance_local_backward_power_W"]/local_pin,
        "local_transmittance": o["exit_local_forward_power_W"]/local_pin,
        "local_energy_residual": 1-(o["entrance_local_backward_power_W"]+o["exit_local_forward_power_W"])/local_pin,
    }
    tol = TOLERANCES["internal_consistency_absolute"]
    for name, expected in calculated.items():
        if not math.isfinite(expected) or abs(o[name]-expected) > tol:
            errors.append("Internal consistency failed: "+name)
    if abs(calculated["energy_residual"]) > TOLERANCES["energy_absolute"]:
        errors.append("Energy residual exceeds 0.02")
    if abs(calculated["incident_normalization_ratio"]-1) > TOLERANCES["incident_normalization_absolute"]:
        errors.append("Incident normalization differs from one by more than 0.02")
    if calculated["exit_backward_fraction"] > TOLERANCES["exit_backward_fraction_max"]:
        errors.append("Exit backward fraction exceeds 0.001")
    for plane in ("entrance", "exit"):
        if calculated[plane+"_crosspolarized_fraction"] > TOLERANCES["crosspolarized_fraction_max"]:
            errors.append(plane+" crosspolarized fraction exceeds 1e-4")
        if abs(o[plane+"_material_admittance_ratio"]-1) > TOLERANCES["material_admittance_absolute"]:
            errors.append(plane+" material admittance ratio differs from one")
        forward, backward = o[plane+"_forward_power_W"], o[plane+"_backward_power_W"]
        local_net = o[plane+"_local_forward_power_W"]-o[plane+"_local_backward_power_W"]
        poynting = o[plane+"_poynting_flux_W"]
        expected_flux = {
            plane+"_net_flux_W": forward-backward,
            plane+"_local_directional_flux_W": local_net,
            plane+"_local_flux_identity_error_W": local_net-poynting,
            plane+"_coherent_local_flux_difference_W": poynting-forward+backward,
        }
        for name, expected in expected_flux.items():
            if not math.isfinite(expected) or abs(o[name]-expected)/pin > tol:
                errors.append("Internal consistency failed: "+name)
        if abs(local_net-poynting)/pin > tol:
            errors.append(plane+" local Poynting identity failed")
        if abs(poynting-forward+backward)/pin > TOLERANCES["coherent_local_flux_fraction"]:
            errors.append(plane+" coherent/local net flux mismatch exceeds 0.005")
    if not 0 <= o["exterior_diffraction_cutoff_ratio"] <= TOLERANCES["diffraction_cutoff_ratio_max"]:
        errors.append("Exterior diffraction cutoff ratio exceeds 0.9 margin")
    if abs(o["wavelength_frequency_ratio"]-1) > TOLERANCES["wavelength_frequency_absolute"]:
        errors.append("Wavelength/frequency ratio differs from one")
    return errors


def update_candidates(candidates, request, results):
    """Mutate/return records; score only complete, valid Allsolve paired spectra.

    Pass coarse-search rows only. Duplicate points, explicit non-Allsolve tags,
    missing results, metadata mismatches, and failed gates prevent ranking.
    Finalist verification is owned by the runner and never inferred here.
    """
    expected = make_points(candidates, request)
    points_by_candidate = {candidate["id"]: {} for candidate in candidates}
    for point in expected:
        points_by_candidate[point["candidate_id"]][(point["input_index"], point["wavelength_nm"])] = point
    observed = {candidate["id"]: {} for candidate in candidates}
    errors = {candidate["id"]: [] for candidate in candidates}
    terminal_failure = {candidate["id"]: False for candidate in candidates}
    for row in results:
        candidate_id = row.get("candidate_id")
        if candidate_id not in observed:
            raise ValueError("Result belongs to an unknown candidate")
        key = (row.get("input_index"), row.get("wavelength_nm"))
        if key not in points_by_candidate[candidate_id]:
            errors[candidate_id].append("Result is outside the submitted input/wavelength grid")
            continue
        if key in observed[candidate_id]:
            errors[candidate_id].append("Duplicate result for an input/wavelength point")
            continue
        observed[candidate_id][key] = row
        if row.get("error"):
            errors[candidate_id].append(str(row["error"]))
            terminal_failure[candidate_id] = True
        if row.get("synthetic") is True or row.get("engine", "allsolve") != "allsolve":
            errors[candidate_id].append("Only real Allsolve results may be ranked")
        if row.get("valid") is not True:
            errors[candidate_id].append("Point was not marked valid by the Allsolve runner")
        outputs = row.get("outputs")
        output_errors = validate_outputs(outputs)
        errors[candidate_id].extend(output_errors)
        if not output_errors:
            point = points_by_candidate[candidate_id][key]
            for name in ("candidate_id", "input_index", "wavelength_nm", "n_liquid", *GEOMETRY_PARAMETERS, "film_thickness_nm"):
                absolute = 1e-6 if name.endswith("_nm") else 1e-8
                if not math.isclose(float(outputs[name]), float(point[name]), rel_tol=0, abs_tol=absolute):
                    errors[candidate_id].append("Output metadata mismatch: "+name)
    wavelengths = _wavelengths(request)
    for candidate in candidates:
        cid = candidate["id"]
        rows, expected_rows = observed[cid], points_by_candidate[cid]
        candidate["completed_solves"] = len(rows)
        candidate["total_solves"] = len(expected_rows)
        candidate.update(score=None, wavelength_nm=None, R_A=None, R_B=None, valid=False)
        messages = list(dict.fromkeys(errors[cid]))
        if messages:
            candidate["status"] = "failed" if terminal_failure[cid] else "invalid"
            candidate["error"] = "; ".join(messages)
            candidate["verified"] = False
        elif len(rows) != len(expected_rows):
            candidate["status"] = "running" if rows else "queued"
            candidate["error"] = None
            candidate["verified"] = False
        else:
            paired = [(abs(rows[(0, wavelength)]["outputs"]["reflectance"]-rows[(1, wavelength)]["outputs"]["reflectance"]),
                       wavelength, rows[(0, wavelength)]["outputs"]["reflectance"],
                       rows[(1, wavelength)]["outputs"]["reflectance"]) for wavelength in wavelengths]
            # First wavelength wins exact ties, making selection deterministic.
            score, wavelength, ra, rb = max(paired, key=lambda item: item[0])
            candidate.update(status="completed", score=score, wavelength_nm=wavelength,
                             R_A=ra, R_B=rb, valid=True, error=None)
    return candidates
