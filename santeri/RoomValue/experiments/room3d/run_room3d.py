"""Resumable, measured-geometry 3D Allsolve harmonic experiment.

The measured RIRs are validation references, not synthesized FEM outputs.
No absorption coefficient or speaker directivity is inferred from them.
Run from this directory; completed cloud jobs are harvested, never restarted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import allsolve
import meshio
import numpy as np
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DATASET = HERE.parents[1] / "datasets" / "dechorate" / "manifest.json"
STATE = HERE / "state.json"
FREQUENCY = 125.0
SOURCE_RADIUS = 0.08
MESH_SIZES = {"coarse": 0.32, "fine": 0.24}
TREATMENT_DAMPING = 0.5
REFINEMENT_TOLERANCE_DB = 0.5


def refinement_errors(state, dataset, previous, current):
    return {name: {r["id"]: 20 * math.log10(
        state["runs"][f"{current}_{name}_125hz"]["pressures"][r["id"]]["amplitude_pa"] /
        state["runs"][f"{previous}_{name}_125hz"]["pressures"][r["id"]]["amplitude_pa"])
        for r in dataset["receivers"]} for name in ("baseline", "east_wall", "ceiling")}


def max_error(errors):
    return max(abs(value) for receivers in errors.values() for value in receivers.values())


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def client():
    env = dotenv_values(WORKSPACE / ".env")
    return allsolve.Client(
        api_key=os.environ.get("ALLSOLVE_ACCESS_KEY") or env.get("ALLSOLVE_ACCESS_KEY"),
        api_secret=os.environ.get("ALLSOLVE_SECRET_KEY") or env.get("ALLSOLVE_SECRET_KEY"),
        host=os.environ.get("ALLSOLVE_HOST") or env.get("ALLSOLVE_HOST") or "https://allsolve.quanscient.com/",
        dotenv_file=None,
    )


def vector(values):
    return dict(zip(("x", "y", "z"), values))


def model_signature(project_config, dataset):
    payload = {"config": project_config, "frequency_hz": FREQUENCY,
               "receivers": dataset["receivers"], "treatment_damping": TREATMENT_DAMPING,
               "field_order": 2, "source_expression": "sn(1)",
               "dataset_manifest_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def config(dataset):
    width, length, height = dataset["room"]["size_m"]
    source = dataset["source"]["position_m"]
    treatments = {
        "east_wall": {"position": [width - 0.2, 2.0, 0.65], "size": [0.2, 2.0, 1.0]},
        "ceiling": {"position": [2.0, 2.0, height - 0.2], "size": [2.0, 1.0, 0.2]},
    }
    for receiver in dataset["receivers"]:
        point = receiver["position_m"]
        if not all(0 < p < size for p, size in zip(point, (width, length, height))):
            raise ValueError(f"Receiver {receiver['id']} outside room")
        if math.dist(point, source) <= SOURCE_RADIUS:
            raise ValueError("Receiver inside source sphere")
    if not all(SOURCE_RADIUS < p < size - SOURCE_RADIUS for p, size in zip(source, (width, length, height))):
        raise ValueError("Source sphere outside room")
    geometries = [
        {"type": "box", "name": "room", "position": vector([0, 0, 0]),
         "size": vector([width, length, height]), "alignment": "corner"},
        {"type": "sphere", "name": "source_sphere", "position": vector(source), "radius": SOURCE_RADIUS},
    ]
    geometries += [
        {"type": "box", "name": name, "position": vector(spec["position"]),
         "size": vector(spec["size"]), "alignment": "corner"}
        for name, spec in treatments.items()
    ]
    geometries.append({"type": "fragmentAll", "name": "partition_room"})
    volumes = ["room", "source_sphere", *treatments]
    regions = [
        {"name": name, "type": "regionRule", "entityType": "volume",
         "attributePath": [{"key": "name", "value": name}]}
        for name in volumes
    ]
    regions += [
        {"name": "all_volumes", "type": "computed", "entityType": "volume",
         "operation": "union", "regions": volumes},
        {"name": "source_boundary", "type": "computed", "entityType": "surface",
         "operation": "boundary", "regions": ["source_sphere"]},
    ]
    meshes = []
    for name, max_size in MESH_SIZES.items():
        meshes.append({
            "name": f"room3d_{name}", "nodeType": "lambda", "scaleFactor": 1.0,
            "useMeshRefiner": False, "curvedMesh": False, "curvatureEnhancement": 6,
            "maxRunTimeMinutes": 10, "meshSizeMin": 0.025, "meshSizeMax": max_size,
            "refinements": [{"region": "source_boundary", "maxSize": 0.04},
                            *[{"region": name, "maxSize": 0.10 if max_size == 0.32 else 0.075}
                              for name in treatments]],
        })
    return {
        "name": "RoomValue dEchorate 3D 125 Hz",
        "description": "Measured room dimensions and coordinates; normalized source and uncalibrated volumetric treatment loss",
        "dimension": 3, "verbose": False, "labels": ["roomvalue", "3d-acoustics", "dechorate"],
        "geometries": geometries, "regions": regions,
        "materials": [{"name": "Assumed homogeneous air", "target": "all_volumes", "density": 1.2,
                       "speedOfSound": dataset["room"]["speed_of_sound_m_s"]}],
        "meshes": meshes,
    }, treatments


def ensure_run(job, label, timeout=900, required_cores=3):
    status = job.get_status()
    if status == allsolve.Job.SUCCESS:
        print(f"{label}: reusing SUCCESS", flush=True)
        return
    if status == allsolve.Job.NOT_STARTED or status is None:
        quota = allsolve.get_quota()
        free = quota.max_concurrent_cores - quota.total_running_cores
        print(f"{label}: organization free cores {free}", flush=True)
        if free < required_cores:
            raise RuntimeError("Insufficient shared cloud cores; rerun this script to resume later")
        job.start()
        print(f"{label}: started", flush=True)
    elif status in (allsolve.Job.ERROR, allsolve.Job.ABORTED, allsolve.Job.PARTIAL_SUCCESS):
        job.print_new_loglines()
        raise RuntimeError(f"{label} cannot be reused: {status}; inspect logs before making a replacement")
    deadline = time.monotonic() + timeout
    while job.is_running(refresh_delay_s=3):
        job.print_new_loglines()
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label}: local wait timed out; cloud job remains resumable")
    job.print_new_loglines()
    if job.get_status() != allsolve.Job.SUCCESS:
        raise RuntimeError(f"{label}: {job.get_status()}")
    print(f"{label}: SUCCESS", flush=True)


def validate_mesh(mesh, dataset, label):
    folder = HERE / "outputs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{label}_{mesh.id}.msh"
    if not path.exists():
        mesh.save_mesh_file(output_dir=str(folder), filename=path.name)
    data = meshio.read(path)
    expected = np.asarray(dataset["room"]["size_m"])
    bounds = np.column_stack((data.points.min(axis=0), data.points.max(axis=0)))
    if not np.allclose(bounds[:, 0], 0, atol=1e-6) or not np.allclose(bounds[:, 1], expected, atol=1e-6):
        raise RuntimeError(f"Wrong 3D mesh bounds: {bounds.tolist()}")
    tetrahedra = [b.data[:, :4] for b in data.cells if b.type in ("tetra", "tetra10")]
    if not tetrahedra:
        raise RuntimeError("Mesh contains no 3D tetrahedra")
    cells = np.concatenate(tetrahedra)
    points = data.points[cells]
    volumes = np.abs(np.linalg.det(points[:, 1:] - points[:, :1])) / 6
    if np.any(volumes <= 1e-15):
        raise RuntimeError("Degenerate tetrahedral elements")
    volume = float(volumes.sum())
    expected_volume = float(expected.prod())
    if not math.isclose(volume, expected_volume, rel_tol=1e-4):
        raise RuntimeError(f"Mesh volume {volume} differs from room {expected_volume}")
    edge_lengths = np.concatenate([np.linalg.norm(points[:, a] - points[:, b], axis=1)
                                  for a in range(4) for b in range(a + 1, 4)])
    metrics = mesh.get_metrics(refresh=True)
    max_edge = float(edge_lengths.max())
    return {
        "mesh_id": mesh.id, "status": "SUCCESS", "bounds_m": bounds.tolist(),
        "node_count": len(data.points), "tetrahedron_count": len(cells), "volume_m3": volume,
        "expected_volume_m3": expected_volume, "sdk_elements": metrics.elements,
        "max_edge_m": max_edge, "p95_edge_m": float(np.quantile(edge_lengths, 0.95)),
        "wavelength_m": dataset["room"]["speed_of_sound_m_s"] / FREQUENCY,
        "min_elements_per_wavelength": dataset["room"]["speed_of_sound_m_s"] / FREQUENCY / max_edge,
        "mesh_file": str(path.relative_to(HERE)),
    }


def physics_set(project, regions, name):
    for existing in project.get_physics_sets():
        if existing.name == name:
            waves = existing.get_physics()
            if len(waves) != 1 or waves[0].definition != "acousticWaves":
                raise RuntimeError(f"Physics set {name} is incomplete or changed")
            wave = waves[0]
            if wave.target_region_id != regions["all_volumes"].id or wave.get_field_interpolation_order() != "2":
                raise RuntimeError(f"Physics set {name} has changed domain/order")
            interactions = wave.get_interactions()
            expected_count = 2 if name in ("east_wall", "ceiling") else 1
            if len(interactions) != expected_count:
                raise RuntimeError(f"Physics set {name} has incomplete interactions")
            source = [i for i in interactions if i.definition == "acousticWavesConstraint"]
            source_value = "0" if name == "source_off" else "sn(1)"
            if len(source) != 1 or source[0].target_region_id() != regions["source_boundary"].id or source[0].enabled is False:
                raise RuntimeError(f"Physics set {name} source has changed")
            if source_value not in [p.value for p in source[0].parameters]:
                raise RuntimeError(f"Physics set {name} source expression has changed")
            if name in ("east_wall", "ceiling"):
                damping = [i for i in interactions if i.definition == "acousticWavesAcousticDamping"]
                if len(damping) != 1 or damping[0].target_region_id() != regions[name].id or damping[0].enabled is False:
                    raise RuntimeError(f"Physics set {name} damping has changed")
                if str(TREATMENT_DAMPING) not in [p.value for p in damping[0].parameters]:
                    raise RuntimeError(f"Physics set {name} damping value has changed")
            return existing
    result = project.create_physics_set(name=name, description="Fixed independent 3D comparison state")
    wave = result.add_physics(allsolve.Physics.AcousticWaves(target=regions["all_volumes"]))
    wave.set_field_interpolation_order(2)
    wave.save()
    wave.add_interactions([
        allsolve.Interaction.AcousticWavesConstraint(
            name="Normalized spherical pressure source", target=regions["source_boundary"],
            acoustic_waves_constraint="0" if name == "source_off" else "sn(1)",
        ),
    ])
    if name in ("east_wall", "ceiling"):
        wave.add_interactions([
            allsolve.Interaction.AcousticWavesAcousticDamping(
                name="Uncalibrated volumetric treatment proxy", target=regions[name],
                acoustic_waves_acoustic_damping_damping_value=TREATMENT_DAMPING,
            ),
        ])
    return result


def simulation(project, mesh, pset, dataset, name):
    existing_sims = project.get_simulations()
    for existing in existing_sims:
        if existing.name == name + "_64gb" and existing.get_status() == allsolve.Job.SUCCESS:
            return existing
    for existing in existing_sims:
        if existing.name == name:
            return existing
    result = project.create_simulation_harmonic(
        name=name, description="125 Hz 3D pressure; measured positions; idealized reflective walls",
        max_run_time_minutes=10, mesh=mesh, physics_set=pset,
        fundamental_frequency=str(FREQUENCY), solver_mode=allsolve.SolverMode.DIRECT,
    )
    outputs = []
    for receiver in dataset["receivers"]:
        coords = ",".join(str(x) for x in receiver["position_m"])
        for label, harmonic in (("real", 2), ("imag", 3)):
            outputs.append(allsolve.Output.ValueOutput(
                name=f"p_{receiver['id']}_{label}",
                expression=f"interpolate(reg.all_volumes,getharmonic({harmonic},p),[{coords}])",
            ))
    outputs.append(allsolve.Output.FieldOutput(
        name="Pressure in phase", expression="getharmonic(2,p)",
    ))
    result.add_outputs(outputs)
    result.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_3_10GB_FAST_START, node_count=1))
    if name.startswith(("fine_", "refined_")):
        result.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_4_64GB, node_count=1))
    result.save()
    return result


def pressure_values(sim, dataset):
    data = sim.get_output_values(refresh=True)["nostep"]
    result = {}
    for receiver in dataset["receivers"]:
        components = []
        for label in ("real", "imag"):
            value = data[f"p_{receiver['id']}_{label}"]
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            value = float(value)
            if not math.isfinite(value):
                raise RuntimeError("Nonfinite cloud pressure")
            components.append(value)
        result[receiver["id"]] = {"real_pa": components[0], "imag_pa": components[1],
                                   "amplitude_pa": math.hypot(*components)}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coarse-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    os.chdir(HERE)
    dataset = read_json(DATASET)
    project_config, treatments = config(dataset)
    write_json(HERE / "model_config.json", project_config)
    signature = model_signature(project_config, dataset)
    state = read_json(STATE) if STATE.exists() else {"model_sha256": signature}
    if state["model_sha256"] != signature:
        raise RuntimeError("Model configuration changed; retain existing results and use a new experiment directory")
    connection = client()
    if state.get("project_id"):
        project = connection.get_project(state["project_id"])
    else:
        project = connection.create_project(name=project_config["name"], description=project_config["description"], dimension=3)
        state.update(project_id=project.id, project_url=connection.get_url(project))
        write_json(STATE, state)
    print(f"Project: {state['project_url']}", flush=True)
    if not state.get("geometry_built"):
        allsolve.import_project(project_config, project_to_modify=project, run_meshes_and_simulations=False)
        state["geometry_built"] = True
        write_json(STATE, state)
    regions = {r.name: r for r in project.get_regions()}
    for name in ("all_volumes", "source_sphere", "source_boundary", "east_wall", "ceiling"):
        if name not in regions or not regions[name].entity_tags:
            raise RuntimeError(f"Missing or empty geometry region: {name}")
    sets = {name: physics_set(project, regions, name) for name in ("baseline", "east_wall", "ceiling", "source_off")}
    meshes = {mesh.name: mesh for mesh in project.get_meshes()}
    state["physics_sets"] = {name: pset.id for name, pset in sets.items()}
    state.setdefault("runs", {})
    levels = ["coarse"] if args.coarse_only else ["coarse", "fine"]
    for level in levels:
        if level == "refined" and "room3d_refined" not in meshes:
            meshes["room3d_refined"] = project.create_mesh(allsolve.MeshSettings(
                name="room3d_refined", node_type="lambda", scale_factor=1.0,
                use_mesh_refiner=False, curved_mesh=False, curvature_enhancement=6,
                max_run_time_minutes=10, mesh_size_min=0.025, mesh_size_max=0.18,
                refinements=[allsolve.MeshRefinement(region=regions["source_boundary"], max_size=0.04),
                             allsolve.MeshRefinement(region=regions["east_wall"], max_size=0.075),
                             allsolve.MeshRefinement(region=regions["ceiling"], max_size=0.075)],
            ))
        mesh = meshes[f"room3d_{level}"]
        if args.prepare_only:
            continue
        ensure_run(mesh, f"{level} mesh")
        state.setdefault("meshes", {})[level] = validate_mesh(mesh, dataset, level)
        write_json(STATE, state)
        for name in ("baseline", "east_wall", "ceiling", "source_off") if level == "coarse" else ("baseline", "east_wall", "ceiling"):
            run_name = f"{level}_{name}_125hz"
            sim = simulation(project, mesh, sets[name], dataset, run_name)
            if (level == "fine" and sim.get_status() == allsolve.Job.ERROR
                    and sim.node_type == allsolve.CPU.CORES_3_10GB_FAST_START
                    and not sim.name.endswith("_64gb")):
                state.setdefault("failed_runs", {})[sim.id] = {
                    "name": sim.name, "status": "ERROR", "status_reason": sim.get_status_reason(),
                    "last_log_stage": "Direct matrix solve on 3 core / 10 GB node",
                    "replacement": "Same physics and mesh, new job on 4 core / 64 GB node",
                    "failure_cause": "Not reported by API; memory exhaustion is a hypothesis",
                }
                sim = simulation(project, mesh, sets[name], dataset, run_name + "_64gb")
            state["runs"].setdefault(run_name, {}).update(simulation_id=sim.id, physics_set_id=sets[name].id)
            write_json(STATE, state)
            ensure_run(sim, run_name, required_cores=4 if level in ("fine", "refined") else 3)
            pressures = pressure_values(sim, dataset)
            state["runs"][run_name].update(status="SUCCESS", pressures=pressures)
            if name == "source_off" and any(p["amplitude_pa"] > 1e-10 for p in pressures.values()):
                raise RuntimeError("Source-off pressure is nonzero")
            if name != "source_off" and any(p["amplitude_pa"] <= 0 for p in pressures.values()):
                raise RuntimeError("Zero acoustic pressure for driven source")
            write_json(STATE, state)
            if name == "baseline":
                folder = HERE / "outputs" / f"{level}_field"
                folder.mkdir(parents=True, exist_ok=True)
                if not any(folder.iterdir()):
                    sim.save_output_field("Pressure in phase", output_dir=str(folder), refresh=True)
        if level == "fine":
            errors = refinement_errors(state, dataset, "coarse", "fine")
            if max_error(errors) > REFINEMENT_TOLERANCE_DB:
                print(f"Coarse/fine difference {max_error(errors):.3f} dB exceeds screening tolerance; adding 0.18 m mesh", flush=True)
                levels.append("refined")
    if args.prepare_only:
        print("Prepared 3D geometry and independent physics sets; no mesh or solve launched", flush=True)
        return
    results = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "dimension": 3,
        "project_id": project.id, "project_url": state["project_url"], "frequency_hz": FREQUENCY,
        "room": dataset["room"], "source": {**dataset["source"], "radius_m": SOURCE_RADIUS, "boundary_pressure_pa": 1},
        "receivers": dataset["receivers"], "treatments": treatments,
        "treatment_damping_value": TREATMENT_DAMPING,
        "dataset_manifest_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "model_sha256": signature, "meshes": state["meshes"], "runs": state["runs"],
        "failed_runs": state.get("failed_runs", {}),
        "assumptions": ["Idealized rigid reflecting floor, ceiling and walls; measured carpet/absorption not calibrated",
                        "Source is a 1 Pa spherical emitter proxy; measured src1 is a directional loudspeaker",
                        "Treatments are equal 0.4 m3 finite damped air regions, not measured commercial panels",
                        "125 Hz harmonic response only; no broadband, A-weighted or impulse-response claim"],
    }
    comparisons = {}
    for level in levels:
        baseline = state["runs"][f"{level}_baseline_125hz"]["pressures"]
        comparisons[level] = {}
        for name in ("east_wall", "ceiling"):
            candidate = state["runs"][f"{level}_{name}_125hz"]["pressures"]
            comparisons[level][name] = {
                receiver: 20 * math.log10(candidate[receiver]["amplitude_pa"] / baseline[receiver]["amplitude_pa"])
                for receiver in baseline
            }
    results["relative_pressure_change_db"] = comparisons
    if "fine" in levels:
        previous, current = ("fine", "refined") if "refined" in levels else ("coarse", "fine")
        errors = refinement_errors(state, dataset, previous, current)
        results["mesh_refinement_pressure_change_db"] = errors
        maximum = max_error(errors)
        results["mesh_refinement_check"] = {"compared_levels": [previous, current], "max_abs_change_db": maximum,
                                           "tolerance_db": REFINEMENT_TOLERANCE_DB,
                                           "passed": maximum <= REFINEMENT_TOLERANCE_DB}
        relative_errors = {name: {receiver: comparisons[current][name][receiver] - comparisons[previous][name][receiver]
                                 for receiver in comparisons[current][name]} for name in ("east_wall", "ceiling")}
        results["relative_comparison_refinement_change_db"] = relative_errors
        results["relative_comparison_refinement_check"] = {
            "max_abs_change_db": max_error(relative_errors), "tolerance_db": REFINEMENT_TOLERANCE_DB,
            "passed": max_error(relative_errors) <= REFINEMENT_TOLERANCE_DB,
        }
        results["mesh_refinement_history"] = [
            {"compared_levels": [a, b], "pressure_change_db": refinement_errors(state, dataset, a, b),
             "max_abs_change_db": max_error(refinement_errors(state, dataset, a, b))}
            for a, b in zip(levels, levels[1:])
        ]
    write_json(HERE / "VERIFIED_3D.json", results)
    print(json.dumps({"project_url": results["project_url"], "relative_pressure_change_db": comparisons,
                      "mesh_refinement_check": results.get("mesh_refinement_check")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
