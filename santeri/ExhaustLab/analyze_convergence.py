"""Separate exported-grid and mesh refinement checks using validated real fields."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    from .analyze_study import BASE, extract_case, field_diagnostics, require_field_validation
    from .particles import ParticleModel, RegularGridFieldSampler, flux_weighted_inlet, integrate_trajectories
except ImportError:
    from analyze_study import BASE, extract_case, field_diagnostics, require_field_validation
    from particles import ParticleModel, RegularGridFieldSampler, flux_weighted_inlet, integrate_trajectories


SOURCE_NAMES = ("state.json", "flow_samples.json", "electric_samples.json", "validation.json")


def load_validated(folder: Path):
    raw = {name: (folder / name).read_bytes() for name in SOURCE_NAMES}
    parsed = {name: json.loads(value.decode("utf-8")) for name, value in raw.items()}
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    state = parsed["state.json"]
    require_field_validation(parsed["validation.json"], state, {name: hashes[name] for name in SOURCE_NAMES[:3]})
    extracted = extract_case(state, parsed["flow_samples.json"], parsed["electric_samples.json"])
    return state, extracted, hashes


def downsample_sampler(sampler: RegularGridFieldSampler) -> RegularGridFieldSampler:
    """Every second original node; retain exact endpoints without new field data."""
    if any(len(axis) < 5 or (len(axis) - 1) % 2 for axis in sampler.axes_m):
        raise ValueError("Each axis must have an odd number of at least five nodes for endpoint-preserving stride-two downsampling.")
    return RegularGridFieldSampler(
        *(axis[::2] for axis in sampler.axes_m),
        sampler.velocity_m_s[::2, ::2, ::2], sampler.electric_v_m[::2, ::2, ::2],
        provenance={**sampler.provenance, "export_grid_operation": "every second node of the same actual field snapshot"},
    )


def nominal(sampler, channel, state):
    inlet = flux_weighted_inlet(sampler, channel, n_y=96, n_z=64)
    model = ParticleModel(gas_viscosity_pa_s=state["mu_pa_s"])
    return integrate_trajectories(sampler, channel, model, inlet, max_step_s=0.005, max_time_s=30).summary()


def changes(coarse, fine):
    return {
        "capture_fraction_absolute_change": abs(fine["captured_fraction"] - coarse["captured_fraction"]),
        "outlet_fraction_absolute_change": abs(fine["outlet_fraction"] - coarse["outlet_fraction"]),
        "unresolved_fraction_absolute_change": abs(fine["unresolved_fraction"] - coarse["unresolved_fraction"]),
        "inlet_flux_relative_change": fine["inlet_flux_m3_s"] / coarse["inlet_flux_m3_s"] - 1,
    }


def process_convergence(fine_folder: Path, coarse_folder: Path | None = None):
    fine_state, (channel, fine_sampler, fine_pressure, fine_potential, fine_provenance), fine_hashes = load_validated(fine_folder)
    sampled_coarse = downsample_sampler(fine_sampler)
    print(f"{fine_state['case']}: comparing full and stride-two exports on the same finite-element solve", flush=True)
    full_result = nominal(fine_sampler, channel, fine_state)
    downsampled_result = nominal(sampled_coarse, channel, fine_state)
    export_change = changes(downsampled_result, full_result)
    report = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fine_case": fine_state["case"],
        "trajectory_inputs": {"diameter_um": 1, "charge_e": 30, "voltage_v": fine_state["voltage_v"],
            "n_y": 96, "n_z": 64, "max_step_s": 0.005, "max_time_s": 30},
        "entered_capture_absolute_tolerance": 0.01,
        "source_snapshots": {fine_state["case"]: {"identifiers": fine_provenance, "file_sha256": fine_hashes}},
        "same_mesh_export_grid": {
            "definition": "Compare original real field samples with every-second-node samples from that same finite-element solve; interpolate both independently, with identical particle integration inputs.",
            "coarse_grid_shape": [len(axis) for axis in sampled_coarse.axes_m],
            "fine_grid_shape": [len(axis) for axis in fine_sampler.axes_m],
            "coarse": downsampled_result,
            "fine": full_result,
            **export_change,
            "capture_within_entered_tolerance": export_change["capture_fraction_absolute_change"] <= 0.01,
        },
        "mesh_comparison": None,
        "limits": [
            "Observed agreement concerns only these tested refinements and entered particle/charge inputs.",
            "All outcomes remain conditional on spherical overdamped particles and ideal absorbing walls.",
            "No validated pressure or velocity field is replaced by an analytic reference.",
            "Unresolved trajectory weight remains in every denominator.",
        ],
    }
    coarse_hashes = None
    if coarse_folder is not None:
        coarse_state, (coarse_channel, coarse_sampler, coarse_pressure, coarse_potential, coarse_provenance), coarse_hashes = load_validated(coarse_folder)
        fields = ("gap_m", "length_m", "span_m", "flow_m3_s", "voltage_v", "mu_pa_s", "rho_kg_m3")
        if any(coarse_state[key] != fine_state[key] for key in fields):
            raise ValueError("Mesh comparison must use exactly the same geometry and physical input parameters.")
        if coarse_state["mesh_id"] == fine_state["mesh_id"]:
            raise ValueError("Mesh comparison requires two distinct meshes.")
        if any(not np.array_equal(a, b) for a, b in zip(coarse_sampler.axes_m, sampled_coarse.axes_m)):
            raise ValueError("Coarse-mesh export axes must equal the downsampled fine-mesh axes to isolate the mesh comparison.")
        print(f"Comparing {coarse_state['case']} with {fine_state['case']} on identical export axes", flush=True)
        coarse_result = nominal(coarse_sampler, coarse_channel, coarse_state)
        mesh_change = changes(coarse_result, downsampled_result)
        coarse_diagnostic = field_diagnostics(coarse_state, coarse_channel, coarse_sampler, coarse_pressure, coarse_potential)
        fine_diagnostic = field_diagnostics(fine_state, channel, sampled_coarse,
            fine_pressure[::2, ::2, ::2], fine_potential[::2, ::2, ::2])
        coarse_drop, fine_drop = coarse_diagnostic["pressure_drop_pa"], fine_diagnostic["pressure_drop_pa"]
        report["source_snapshots"][coarse_state["case"]] = {"identifiers": coarse_provenance, "file_sha256": coarse_hashes}
        report["mesh_comparison"] = {
            "definition": "Coarse and refined finite-element mesh snapshots compared after matching export axes; identical particle integration inputs.",
            "coarse_case": coarse_state["case"], "fine_case": fine_state["case"],
            "coarse_mesh_size_max_m": coarse_state.get("mesh_size_max_m"),
            "fine_mesh_size_max_m": fine_state.get("mesh_size_max_m"),
            "common_export_grid_shape": [len(axis) for axis in sampled_coarse.axes_m],
            "coarse": coarse_result, "fine": downsampled_result,
            **mesh_change,
            "coarse_pressure_drop_pa": coarse_drop, "fine_pressure_drop_pa": fine_drop,
            "pressure_drop_relative_change": abs(fine_drop - coarse_drop) / abs(fine_drop) if fine_drop else None,
            "capture_within_entered_tolerance": mesh_change["capture_fraction_absolute_change"] <= 0.01,
        }
    for folder, hashes in ((fine_folder, fine_hashes), (coarse_folder, coarse_hashes)):
        if folder is not None and any(hashlib.sha256((folder / name).read_bytes()).hexdigest() != hashes[name] for name in SOURCE_NAMES):
            raise ValueError("Source snapshots changed during convergence processing; no report written.")
    output = fine_folder / "convergence_report.json"
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Export-grid capture change={export_change['capture_fraction_absolute_change']:.4%}; wrote {output}", flush=True)
    return report


def case_folder(name: str) -> Path:
    folder = (BASE / "runs" / name).resolve()
    if folder.parent != (BASE / "runs").resolve():
        raise ValueError("Case names must identify direct directories under ExhaustLab/runs.")
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fine-case", default="gap6fine")
    parser.add_argument("--coarse-case", help="Optional separate coarse finite-element mesh case, normally gap6")
    args = parser.parse_args()
    process_convergence(case_folder(args.fine_case), case_folder(args.coarse_case) if args.coarse_case else None)


if __name__ == "__main__":
    main()
