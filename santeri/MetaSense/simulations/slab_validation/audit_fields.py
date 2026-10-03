"""Offline audit of downloaded Allsolve tetrahedral field exports.

Uses h5py/numpy from the workspace-root environment; no cloud or SDK calls.
Compare only matching facets and their corresponding exported sample points.
Nodal jump RMS is a diagnostic, not a continuous trace norm or acceptance gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np


HERE = Path(__file__).resolve().parent
DEFAULT_SIMULATION = "ZZGQpwIZW3aZVkHAFE"
COORDINATE_TOLERANCE_M = 1e-15
COMPONENTS = ("Ex", "Ey", "Ez")
VACUUM_IMPEDANCE_OHM = 376.7303136671465


def _key(coordinates: np.ndarray) -> tuple[int, ...]:
    return tuple(np.rint(coordinates / COORDINATE_TOLERANCE_M).astype(np.int64))


def _read_pair(folder: Path):
    sources = []
    arrays = []
    for name in ("E cosine_nostep_0.hdf", "E sine_nostep_0.hdf"):
        path = folder / name
        with h5py.File(path, "r") as file:
            grid = file["VTKHDF"]
            arrays.append({key: grid[key][:] for key in
                           ("Points", "Connectivity", "Offsets", "Types")})
            arrays[-1]["E"] = grid["PointData/E"][:]
        sources.append({"path": str(path.resolve()), "size_bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    cosine, sine = arrays
    for key in ("Points", "Connectivity", "Offsets", "Types"):
        if not np.array_equal(cosine[key], sine[key]):
            raise ValueError(f"Cosine/sine export topology differs: {key}")
    counts = np.diff(cosine["Offsets"])
    if not np.all(counts == 10) or not np.all(cosine["Types"] == 71):
        raise ValueError("Expected VTK Lagrange tetrahedra (type 71) with ten samples")
    field = cosine["E"] - 1j * sine["E"]
    if field.shape != cosine["Points"].shape or not np.all(np.isfinite(field)):
        raise ValueError("Invalid or nonfinite vector field export")
    cells = cosine["Connectivity"].reshape(-1, 10)
    return cosine["Points"], cells, field, sources


def _facets(points, cells, field, axis: int, plane: float, *, canonical_shift=False):
    """Keep tetrahedra with an actual triangular facet on the requested plane."""
    sides = ({}, {})
    for cell in cells:
        vertex_coordinates = points[cell[:4]]
        vertices_on_plane = np.abs(vertex_coordinates[:, axis] - plane) <= COORDINATE_TOLERANCE_M
        if int(vertices_on_plane.sum()) != 3:
            continue  # A vertex/edge touching the plane is not an interface facet.
        coordinates = vertex_coordinates[vertices_on_plane].copy()
        if canonical_shift:
            coordinates[:, axis] = 0.0
        facet_key = tuple(sorted(_key(point) for point in coordinates))
        samples = cell[np.abs(points[cell, axis] - plane) <= COORDINATE_TOLERANCE_M]
        if len(samples) != 6:
            raise ValueError("Expected six quadratic samples on each triangular facet")
        values = {}
        for sample in samples:
            coordinate = points[sample].copy()
            if canonical_shift:
                coordinate[axis] = 0.0
            values[_key(coordinate)] = field[sample]
        side = int(vertex_coordinates.mean(axis=0)[axis] > plane)
        if facet_key in sides[side]:
            raise ValueError("Duplicate one-sided facet at identical coordinates")
        sides[side][facet_key] = values
    return sides


def _compare(left, right, normal_axis: int) -> dict:
    matched = sorted(set(left) & set(right))
    jumps = []
    for facet in matched:
        a, b = left[facet], right[facet]
        if set(a) != set(b):
            raise ValueError("Matched facet has nonmatching sample coordinates")
        jumps.extend(a[point] - b[point] for point in sorted(a))
    tangent = [axis for axis in range(3) if axis != normal_axis]
    result = {
        "left_facet_count": len(left), "right_facet_count": len(right),
        "matched_facet_count": len(matched), "matched_sample_pair_count": len(jumps),
        "unmatched_left_facet_count": len(left) - len(matched),
        "unmatched_right_facet_count": len(right) - len(matched),
        "normal_component": COMPONENTS[normal_axis],
        "tangential_components": [COMPONENTS[axis] for axis in tangent],
        "sample_weighting": "unweighted corresponding nodal samples, six per matched facet",
    }
    if not jumps:
        result.update(component_rms_jump_V_per_m=None, component_max_jump_V_per_m=None,
                      tangential_rms_jump_V_per_m=None, tangential_max_jump_V_per_m=None)
        return result
    magnitude = np.abs(np.asarray(jumps))
    rms = np.sqrt(np.mean(magnitude * magnitude, axis=0))
    maximum = np.max(magnitude, axis=0)
    result.update(
        component_rms_jump_V_per_m=dict(zip(COMPONENTS, map(float, rms))),
        component_max_jump_V_per_m=dict(zip(COMPONENTS, map(float, maximum))),
        tangential_rms_jump_V_per_m={COMPONENTS[axis]: float(rms[axis]) for axis in tangent},
        tangential_max_jump_V_per_m={COMPONENTS[axis]: float(maximum[axis]) for axis in tangent},
    )
    return result


def _mean_field_diagnostic(raw: dict, wavelength: float, total_length: float) -> dict:
    """Compare coherent x-mode power with already saved local split powers."""
    outputs = {key: values[0] for key, values in raw["public_output_values"]["nostep"].items()}
    specified = outputs["specified_incident_power_W"]
    # E0 is one in this benchmark; specified power gives A*Y0/2.
    amplitudes = {}
    powers = {}
    variance = {}
    for plane in ("entrance", "exit"):
        electric = complex(outputs[plane + "_Ex_cos"], -outputs[plane + "_Ex_sin"])
        magnetic = complex(outputs[plane + "_Hy_cos"], -outputs[plane + "_Hy_sin"])
        amplitudes[plane] = ((electric + VACUUM_IMPEDANCE_OHM * magnetic) / 2,
                             (electric - VACUUM_IMPEDANCE_OHM * magnetic) / 2)
        powers[plane] = tuple(specified * abs(value)**2 for value in amplitudes[plane])
        variance[plane] = {
            direction + "_excess_local_power_over_specified":
                (outputs[plane + "_" + direction + "_power_W"] - powers[plane][index]) / specified
            for index, direction in enumerate(("forward", "backward"))
        }
    incident = amplitudes["entrance"][0]
    reflection = amplitudes["entrance"][1] / incident
    transmission = amplitudes["exit"][0] / incident
    expected_phase = (-2 * math.pi * total_length / wavelength if outputs["slab_index"] == 1
                      else -math.pi / 2)  # Quarter-wave slab; air clearances total one wavelength.
    measured_phase = math.atan2(transmission.imag, transmission.real)
    phase_error = math.atan2(math.sin(measured_phase - expected_phase),
                             math.cos(measured_phase - expected_phase))
    return {
        "scope": "coherent surface-average x-polarized zeroth mode; no averaged Ey/Hx outputs available",
        "coherent_R_x": abs(reflection)**2, "coherent_T_x": abs(transmission)**2,
        "reported_local_R": outputs["reflectance"], "reported_local_T": outputs["transmittance"],
        "measured_transmission_phase_rad": measured_phase,
        "expected_transmission_phase_rad_wrapped": math.atan2(math.sin(expected_phase), math.cos(expected_phase)),
        "transmission_phase_error_rad": phase_error,
        "local_minus_coherent_power_diagnostic": variance,
        "limitation": "Excess local split power contains x-field spatial variance plus the y channel; it is not all propagating power",
    }


def audit(run_folder: Path, simulation_id: str, periodic_order: int,
          scalar_root: Path | None = None) -> dict:
    period, thickness, clearance, wavelength = 5e-7, 1e-6/6, 5e-7, 1e-6
    scalar_root = scalar_root if scalar_root is not None else run_folder
    expected_min = np.array((0.0, 0.0, -clearance))
    expected_max = np.array((period, period, thickness + clearance))
    result = {
        "label": "offline_periodic_slab_field_audit", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_id": "jgeSELslGe3PYqB2N9", "simulation_id": simulation_id,
        "periodic_multiplier_order": periodic_order, "run_folder": str(run_folder.resolve()),
        "scalar_root": str(scalar_root.resolve()),
        "coordinate_matching_tolerance_m": COORDINATE_TOLERANCE_M,
        "phasor_convention": "E_cos - i E_sin; exp(+i omega t)",
        "geometry_expected_SI": {"minimum_m": expected_min.tolist(), "maximum_m": expected_max.tolist(),
                                 "span_m": (expected_max-expected_min).tolist(),
                                 "slab_interface_z_m": [0.0, thickness]},
        "method": "Compare corresponding exported samples only on facets whose three vertices match; exclude cells touching a plane only at vertices or edges. Opposite faces are translated by one period before matching.",
        "limitations": ["Only geometrically matching periodic facets are compared; nonmatching facets remain unassessed.",
                        "Nodal RMS/max are diagnostic sampled jumps, not an exact continuous L2 norm.",
                        "Normal-component jumps are not tests of hcurl tangential continuity.",
                        "No acceptance threshold, validation flag, cloud call, or tolerance adjustment is introduced."],
        "sweeps": [],
    }
    for sweep in (0, 1):
        points, cells, field, sources = _read_pair(run_folder / "fields" / f"sweep_{sweep}")
        minimum, maximum = points.min(axis=0), points.max(axis=0)
        row = {
            "sweep_index": sweep, "field_files": sources, "cell_count": len(cells), "export_sample_count": len(points),
            "geometry_measured_SI": {"minimum_m": minimum.tolist(), "maximum_m": maximum.tolist(),
                                     "span_m": (maximum-minimum).tolist(),
                                     "maximum_bound_error_m": float(max(np.max(abs(minimum-expected_min)), np.max(abs(maximum-expected_max))))},
            "interfaces": {}, "periodic_faces": {},
        }
        for z, name in ((0.0, "left_slab_interface"), (thickness, "right_slab_interface")):
            left, right = _facets(points, cells, field, 2, z)
            row["interfaces"][name] = {"z_m": z, **_compare(left, right, 2)}
        for axis, name in ((0, "x"), (1, "y")):
            lower = _facets(points, cells, field, axis, 0.0, canonical_shift=True)[1]
            upper = _facets(points, cells, field, axis, period, canonical_shift=True)[0]
            row["periodic_faces"][name] = {"translation_m": period, **_compare(lower, upper, axis)}
        raw_path = scalar_root / f"raw_output_sweep_{sweep}.json"
        if raw_path.exists():
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if raw.get("simulation_id") != simulation_id:
                raise ValueError("Raw scalar provenance belongs to a different simulation")
            row["raw_scalar_file"] = str(raw_path.resolve())
            row["mean_field_diagnostic"] = _mean_field_diagnostic(raw, wavelength, 2*clearance+thickness)
        result["sweeps"].append(row)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-folder", type=Path, default=HERE / "results" / "coarse")
    parser.add_argument("--scalar-root", type=Path,
                        help="Optional raw-scalar folder when fields are stored separately; simulation ID must match")
    parser.add_argument("--simulation-id", default=DEFAULT_SIMULATION)
    parser.add_argument("--periodic-order", type=int, default=0)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "default_periodicity_audit.json")
    args = parser.parse_args()
    report = audit(args.run_folder, args.simulation_id, args.periodic_order, args.scalar_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "simulation_id": args.simulation_id,
                      "sweeps_audited": len(report["sweeps"])}, indent=2))


if __name__ == "__main__":
    main()
