"""One small, real Allsolve acoustic solve for an illustrative cafeteria slice.

This experiment drives a 10 cm radius circular source at 250 Hz. It reports
pressure at two receiver positions. The 'treatment' is a *proxy* for an
absorptive region; it is not a calibrated commercial product model.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import allsolve
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name("harmonic_state.json")


def project_config() -> dict:
    return {
        "name": "RoomValue cafeteria 2D 250 Hz probe",
        "description": "Illustrative narrowband room pressure, circular source, local damping proxy",
        "dimension": 2,
        "verbose": False,
        "labels": ["room-acoustics", "hackathon", "narrowband"],
        "geometries": [
            {"type": "rectangle", "name": "room", "position": {"x": 0, "y": 0}, "size": {"x": 6, "y": 4}, "alignment": "corner"},
            {"type": "disk", "name": "source_disk", "position": {"x": 1, "y": 2}, "radius": 0.10},
            {"type": "rectangle", "name": "treatment_zone", "position": {"x": 5.75, "y": 1}, "size": {"x": 0.20, "y": 2}, "alignment": "corner"},
            {"type": "rectangle", "name": "north_zone", "position": {"x": 2, "y": 3.75}, "size": {"x": 2, "y": 0.20}, "alignment": "corner"},
            {"type": "rectangle", "name": "south_zone", "position": {"x": 2, "y": 0.05}, "size": {"x": 2, "y": 0.20}, "alignment": "corner"},
            {"type": "fragmentAll", "name": "partition_room"},
        ],
        "regions": [
            {"name": "room", "type": "regionRule", "entityType": "surface", "attributePath": [{"key": "name", "value": "room"}]},
            {"name": "source_disk", "type": "regionRule", "entityType": "surface", "attributePath": [{"key": "name", "value": "source_disk"}]},
            {"name": "treatment_zone", "type": "regionRule", "entityType": "surface", "attributePath": [{"key": "name", "value": "treatment_zone"}]},
            {"name": "north_zone", "type": "regionRule", "entityType": "surface", "attributePath": [{"key": "name", "value": "north_zone"}]},
            {"name": "south_zone", "type": "regionRule", "entityType": "surface", "attributePath": [{"key": "name", "value": "south_zone"}]},
            {"name": "all_surfaces", "type": "computed", "entityType": "surface", "operation": "union", "regions": ["room", "source_disk", "treatment_zone", "north_zone", "south_zone"]},
            {"name": "air", "type": "computed", "entityType": "surface", "operation": "difference", "regions": ["all_surfaces", "source_disk"]},
            {"name": "source_boundary", "type": "computed", "entityType": "curve", "operation": "boundary", "regions": ["source_disk"]},
        ],
        "materials": [
            {"name": "Illustrative air", "target": "all_surfaces", "density": 1.2, "speedOfSound": 343.0},
        ],
        "meshes": [
            {
                "name": "room_mesh_250hz",
                "nodeType": "lambda",
                "scaleFactor": 1.0,
                "useMeshRefiner": False,
                "curvedMesh": False,
                "curvatureEnhancement": 6,
                "maxRunTimeMinutes": 10,
                "meshSizeMin": 0.03,
                "meshSizeMax": 0.20,
                "refinements": [
                    {"region": "source_boundary", "maxSize": 0.035},
                    {"region": "treatment_zone", "maxSize": 0.10},
                    {"region": "north_zone", "maxSize": 0.10},
                    {"region": "south_zone", "maxSize": 0.10},
                ],
            }
        ],
    }


def save_state(**updates: object) -> dict:
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    state.update(updates)
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def wait_job(job, label: str, seconds: int = 600) -> None:
    deadline = time.monotonic() + seconds
    while job.is_running(refresh_delay_s=2):
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label} exceeded {seconds} s; cloud job left running")
    status = job.get_status()
    print(f"{label}: {status}", flush=True)
    if status != allsolve.Job.SUCCESS:
        raise RuntimeError(f"{label} failed: {status}")


def main() -> None:
    env = dotenv_values(ROOT / ".env")
    key, secret = env.get("ALLSOLVE_ACCESS_KEY"), env.get("ALLSOLVE_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("Allsolve credentials missing from workspace .env")
    client = allsolve.Client(
        api_key=key,
        api_secret=secret,
        host=env.get("ALLSOLVE_HOST") or "https://allsolve.quanscient.com/",
        dotenv_file=None,
    )
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if state.get("project_id"):
        project = client.get_project(state["project_id"])
        print(f"Resuming project: {client.get_url(project)}", flush=True)
    else:
        project = allsolve.import_project(project_config())
        state = save_state(project_id=project.id, project_url=client.get_url(project))
        print(f"Created project: {client.get_url(project)}", flush=True)

    meshes = project.get_meshes()
    if not meshes:
        raise RuntimeError("Project has no mesh")
    mesh = meshes[0]
    wait_job(mesh, "mesh", 600)
    state = save_state(mesh_id=mesh.id)

    regions = {r.name: r for r in project.get_regions()}
    required = {"air", "all_surfaces", "source_boundary", "treatment_zone"}
    if not required.issubset(regions):
        raise RuntimeError(f"Missing regions: {sorted(required - regions.keys())}")

    phys_set = project.get_default_physics_set()
    acoustics = next((p for p in project.get_physics() if p.definition == "acousticWaves"), None)
    if acoustics is None:
        acoustics = phys_set.add_physics(allsolve.Physics.AcousticWaves(target=regions["all_surfaces"]))
        acoustics.add_interactions([
            allsolve.Interaction.AcousticWavesConstraint(
                name="1 Pa sine source", acoustic_waves_constraint="sn(1)", target=regions["source_boundary"]
            ),
            allsolve.Interaction.AcousticWavesAcousticDamping(
                name="Illustrative treatment loss", acoustic_waves_acoustic_damping_damping_value=0.5,
                target=regions["treatment_zone"]
            ),
        ])
        print("Added acoustic physics and source/treatment interactions", flush=True)
    elif acoustics.target_region_id != regions["all_surfaces"].id:
        # This target contains the driven circular region's boundary as well
        # as the room and treatment zone. The earlier air-minus-disk target
        # made the solver reject the source curve as outside the physics.
        acoustics.target_region_id = regions["all_surfaces"].id
        acoustics.save()
        print("Expanded acoustic target to include circular source", flush=True)

    simulations = project.get_simulations()
    if simulations:
        simulation = simulations[0]
    else:
        simulation = allsolve.Simulation.create(
            name="250 Hz normalized source",
            description="Pressure at two cafeteria listener positions",
            max_run_time_minutes=10,
            solver_mode=allsolve.SolverMode.DIRECT,
            mesh_id=mesh.id,
            physics_set=phys_set,
            analysis_type=allsolve.AnalysisType.HARMONIC,
            fundamental_frequency="250",
            project_id=project.id,
        )
        outputs = []
        for label, x, y in [("near", 2.5, 2.0), ("far", 5.0, 2.0)]:
            for component, harmonic in [("in_phase", 2), ("quadrature", 3)]:
                outputs.append(allsolve.Output.ValueOutput(
                    name=f"p_{label}_{component}",
                    expression=f"interpolate(reg.all_surfaces, getharmonic({harmonic}, p), [{x},{y},0])",
                ))
        simulation.add_outputs(outputs)
        simulation.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_3_10GB_FAST_START, node_count=1))
        simulation.save()
        save_state(simulation_id=simulation.id)
        print("Created 250 Hz harmonic simulation", flush=True)

    status = simulation.get_status()
    if status == allsolve.Job.SUCCESS:
        print("Using completed simulation", flush=True)
    else:
        # The SDK's is_running() returns True for NOT_STARTED, so check that
        # state explicitly before entering the polling loop.
        if status == allsolve.Job.NOT_STARTED:
            simulation.start()
            print("Started real Allsolve harmonic solve", flush=True)
        elif status in (allsolve.Job.ERROR, allsolve.Job.ABORTED):
            raise RuntimeError(f"Existing simulation cannot be resumed: {status}")
        wait_job(simulation, "harmonic simulation", 900)

    values = simulation.get_output_values(refresh=True)
    print("Solver output time/frequency keys:", list(values.keys()), flush=True)
    save_state(status="completed", output_values=values)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
