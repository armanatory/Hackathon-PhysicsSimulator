"""Idempotent Allsolve 3D cold side-stream collector verification.

Preserves completed geometry, meshes, simulations and job IDs. Run from this
folder with the workspace .venv interpreter. Credentials remain in root .env.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from datetime import datetime, timezone

import allsolve

BASE = Path(__file__).resolve().parent
L, W, MU, RHO, Q, VOLTAGE = .06, .02, 1.81e-5, 1.2, .2e-3 / 60, 200.
GRID = (25, 17, 9)
FLOW_NAME = "flow_explicit_v6"


def reference(gap, terms=15):
    odd = range(1, 2 * terms, 2)
    correction = 96/math.pi**4 * sum(1/n**4 - 2*gap/(math.pi*W)*
        math.tanh(n*math.pi*W/(2*gap))/n**5 for n in odd)
    gradient = 12 * MU * Q / (W * gap**3 * correction)
    coefficient = 4 * gradient * gap**2 / (MU * math.pi**3)
    inlet = "+".join(
        f"(1-(exp({n*math.pi/gap:.16g}*(z-{W}))+exp(-{n*math.pi/gap:.16g}*z))/"
        f"{1+math.exp(-n*math.pi*W/gap):.16g})*sin({n*math.pi/gap:.16g}*y)/{n**3}"
        for n in range(1, 2 * terms, 2))
    return {"pressure_gradient_pa_m": gradient, "pressure_drop_pa": gradient * L,
            "mean_velocity_m_s": Q / (W * gap),
            "reynolds": RHO * Q / (W * gap) * (2 * W * gap / (W + gap)) / MU,
            "inlet_expression": f"{coefficient:.16g}*({inlet})", "series_terms": terms}


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def get_named(items, name):
    return next((item for item in items if item.name == name), None)


def sample_script(kind):
    # Runtime executes this against the finite element solution in the cloud.
    field = "qs.expression(fld.V)" if kind == "flow" else "-qs.grad(fld.v)"
    scalar = "qs.expression(fld.p)" if kind == "flow" else "qs.expression(fld.v)"
    return f'''import numpy as np
points = [[float(x), float(y), float(z)]
          for x in np.linspace(0, {L}, {GRID[0]})
          for y in np.linspace(0, float(expr.gap), {GRID[1]})
          for z in np.linspace(0, {W}, {GRID[2]})]
xyz = [v for point in points for v in point]
print("Sampling verified finite element fields", len(points), "points")
components = [qs.allinterpolate(reg.gas, comp({field}), xyz)
              for comp in (qs.compx, qs.compy, qs.compz)]
vectors = np.asarray(components).T.reshape(-1).tolist()
scalars = qs.allinterpolate(reg.gas, {scalar}, xyz)
if len(vectors) != 3*len(points) or len(scalars) != len(points):
    raise RuntimeError("Unexpected field sample shape")
for label, values in (("sample_xyz_m", xyz), ("sample_vector", vectors), ("sample_scalar", scalars)):
    if len(values) <= 10000:
        qs.setoutputvalue(label, values)
    else:
        for index, offset in enumerate(range(0, len(values), 10000)):
            qs.setoutputvalue(label + "_part_" + str(index).zfill(3), values[offset:offset+10000])
qs.setoutputvalue("gas_volume_m3", qs.expression(1).integrate(reg.gas, 4))
if "{kind}" == "flow":
    qs.setoutputvalue("fe_inlet_flux_m3_s", qs.compx(fld.V).integrate(reg.inlet, 4))
    qs.setoutputvalue("fe_outlet_flux_m3_s", qs.compx(fld.V).integrate(reg.outlet, 4))
    qs.setoutputvalue("fe_inlet_mean_pressure_pa", qs.expression(fld.p).integrate(reg.inlet, 4)/(float(expr.gap)*{W}))
    qs.setoutputvalue("fe_outlet_mean_pressure_pa", qs.expression(fld.p).integrate(reg.outlet, 4)/(float(expr.gap)*{W}))
'''


STEADY_FLOW = '''# Linear incompressible straight-channel benchmark; original failed solves preserved.
form = qs.formulation()
form += qs.integral(reg.gas, par.Mu()*qs.doubledotproduct(qs.grad(qs.dof(fld.V)), qs.grad(qs.tf(fld.V)))
    - qs.dof(fld.p)*qs.div(qs.tf(fld.V)) + qs.div(qs.dof(fld.V))*qs.tf(fld.p))
print("Explicit stationary incompressible weak form")
'''


def setup(client, case, gap, size):
    folder = BASE / "runs" / case
    folder.mkdir(parents=True, exist_ok=True)
    statefile = folder / "state.json"
    state = json.loads(statefile.read_text()) if statefile.exists() else {}
    if "project_id" in state:
        project = client.get_project(state["project_id"])
    else:
        project = client.create_project(name=f"ExhaustLab {case} 3D plate channel",
                    description="Cold low-flow precharged dilute aerosol pilot. Separate airflow and electrostatic field solves.",
                    dimension=3)
        state = {"case": case, "project_id": project.id, "project_url": client.get_url(project),
                 "gap_m": gap, "length_m": L, "span_m": W, "flow_m3_s": Q,
                 "voltage_v": VOLTAGE, "mu_pa_s": MU, "rho_kg_m3": RHO,
                 "mesh_size_max_m": size, "grid_shape": GRID,
                 "created_utc": datetime.now(timezone.utc).isoformat(), "reference": reference(gap)}
        write(statefile, state)
    client.set_current_project(project)
    if not state.get("geometry_built"):
        if not project.get_variables():
            project.create_variables([("gap", str(gap), "Plate gap, m")])
        builder = project.geometry_builder()
        # Geometry stage is only set up once, before any useful output exists.
        if not state.get("geometry_configured"):
            builder.add_box(name="gas", position=(0, 0, 0), size=(L, "gap", W),
                            alignment=allsolve.CadAlignment.CORNER)
            state["geometry_configured"] = True
            write(statefile, state)
        builder.build(print_logs=True, on_error=allsolve.OnError.STRICT)
        state["geometry_built"] = True
        write(statefile, state)
    regions = {r.name: r for r in project.get_regions()}
    if "gas" not in regions:
        regions["gas"] = project.create_region_rule(name="gas", entity_type=allsolve.Region.VOLUME,
                                                   attribute_path=[("name", "gas")])
    if "boundary" not in regions:
        regions["boundary"] = project.create_region_computed(name="boundary", entity_type=allsolve.Region.SURFACE,
                         operation=allsolve.RegionOperation.BOUNDARY, source_regions=[regions["gas"].id])
    eps = 1e-8
    for name, axis, value in [("inlet", 0, 0), ("outlet", 0, L), ("ground", 1, 0), ("high_voltage", 1, gap)]:
        if name not in regions:
            lo, hi = [-eps]*3, [L+eps, gap+eps, W+eps]
            lo[axis], hi[axis] = value-eps, value+eps
            regions[name] = project.create_region_rule(name=name, entity_type=allsolve.Region.SURFACE,
                                                       bounding_box=(tuple(lo), tuple(hi)))
    if "ends" not in regions:
        regions["ends"] = project.create_region_computed(name="ends", entity_type=allsolve.Region.SURFACE,
                         operation=allsolve.RegionOperation.UNION, source_regions=[regions["inlet"].id, regions["outlet"].id])
    if "walls" not in regions:
        regions["walls"] = project.create_region_computed(name="walls", entity_type=allsolve.Region.SURFACE,
                         operation=allsolve.RegionOperation.DIFFERENCE, source_regions=[regions["boundary"].id, regions["ends"].id])
    regions = {r.name: r for r in project.get_regions()}
    counts = {k: len(r.entity_tags) for k, r in regions.items()}
    print("Region counts", counts, flush=True)
    assert counts["gas"] == 1 and counts["walls"] == 4
    assert all(counts[k] == 1 for k in ["inlet", "outlet", "ground", "high_voltage"])
    state["region_entity_counts"] = counts
    if not project.get_materials():
        project.create_material(name="Entered cold gas", target_region=regions["gas"],
                                density=RHO, dynamic_viscosity=MU, electric_permittivity="epsilon0")
    flowset = get_named(project.get_physics_sets(), "Airflow") or project.create_physics_set(name="Airflow")
    electricset = get_named(project.get_physics_sets(), "Electrostatic") or project.create_physics_set(name="Electrostatic")
    flows = [p for p in project.get_physics() if p.physics_set_id == flowset.id]
    flow = flows[0] if flows else flowset.add_physics(allsolve.Physics.LaminarFlow(target=regions["gas"]))
    velocity_id, pressure_id = flow.fields.velocity.id, flow.fields.pressure.id
    if state.get("mesh_status", "").split(".")[-1] != "SUCCESS":
        flow.set_field_interpolation_order(2, field_id=velocity_id)
        flow.save()
        flow.set_field_interpolation_order(1, field_id=pressure_id)
        flow.save()
    # SDK save() drops field definitions and target from its local object.
    flow = next(p for p in project.get_physics() if p.id == flow.id)
    if state.get("inlet_version") != 2:
        for interaction in flow.get_interactions():
            if interaction.name == "Developed inlet":
                interaction.delete()
        flow.add_interactions([allsolve.Interaction.LaminarFlowVelocityConstraint(name="Developed inlet",
                laminar_flow_velocity_constraint=[[1, reference(gap)["inlet_expression"]], [1, 0], [1, 0]], target=regions["inlet"])])
        state["inlet_version"] = 2
        state["reference"] = reference(gap)
        write(statefile, state)
    if not any(i.name == "No slip" for i in flow.get_interactions()):
        flow.add_interactions([
            allsolve.Interaction.LaminarFlowVelocityConstraint(name="No slip",
                laminar_flow_velocity_constraint=[[1, 0], [1, 0], [1, 0]], target=regions["walls"]),
            allsolve.Interaction.LaminarFlowPressureConstraint(name="Outlet zero gauge",
                laminar_flow_pressure_constraint=0, target=regions["outlet"]),
        ])
    electrics = [p for p in project.get_physics() if p.physics_set_id == electricset.id]
    electric = electrics[0] if electrics else electricset.add_physics(allsolve.Physics.Electrostatics(target=regions["gas"]))
    if not electric.get_interactions():
        electric.add_interactions([
            allsolve.Interaction.ElectrostaticsConstraint(name="Grounded collector", electrostatics_constraint=0, target=regions["ground"]),
            allsolve.Interaction.ElectrostaticsConstraint(name="Opposite plate", electrostatics_constraint=VOLTAGE, target=regions["high_voltage"]),
        ])
    mesh = get_named(project.get_meshes(), "channel_mesh")
    if mesh is None:
        mesh = project.create_mesh(allsolve.MeshSettings(name="channel_mesh", mesh_size_min=size/2,
                    mesh_size_max=size, scale_factor=1., use_mesh_refiner=False,
                    node_type=allsolve.CPU.CORES_3_10GB_FAST_START.value, max_run_time_minutes=10))
    state["mesh_id"] = mesh.id
    simulations = {}
    for kind, physset, vector, scalar in [("flow", flowset, "V", "p"), ("electric", electricset, "E", "v")]:
        simname = FLOW_NAME if kind == "flow" else "electric_chunks_v2" if math.prod(GRID)>10000 else kind
        existing_sims = project.get_simulations()
        sim = next((s for s in existing_sims if s.id == state.get(f"{kind}_simulation_id")
                    and state.get(f"{kind}_status", "").split(".")[-1] == "SUCCESS"), None)
        sim = sim or get_named(existing_sims, simname)
        if sim is None:
            sim = project.create_simulation_static(name=simname, description=f"Real 3D {kind} and point samples",
                    max_run_time_minutes=10, mesh=mesh, physics_set=physset,
                    nonlinear_solver_tolerance="1e-8", nonlinear_solver_max_iterations="30")
            sim.add_outputs([allsolve.Output.FieldOutput(name=f"{kind}_vector", expression=vector, target=regions["gas"]),
                             allsolve.Output.FieldOutput(name=f"{kind}_scalar", expression=scalar, target=regions["gas"])])
            scripts = [allsolve.Script(name=f"sample_{kind}.py", section_name=allsolve.CustomSection.AFTER_ALL,
                                      content=sample_script(kind))]
            if kind == "flow":
                scripts.insert(0, allsolve.Script(name="stationary_flow.py", section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,
                                                 content=STEADY_FLOW))
            sim.set_scripts(scripts)
        simulations[kind] = sim
        if kind == "flow" and state.get("flow_simulation_id") not in (None, sim.id):
            history = folder / "invalid_original_flow"
            history.mkdir(exist_ok=True)
            for filename in ("state.json", "flow_samples.json", "validation.json"):
                if (folder / filename).exists() and not (history / filename).exists():
                    shutil.copy2(folder / filename, history / filename)
            state["original_flow_simulation_id"] = state["flow_simulation_id"]
            state.pop("flow_status", None)
            state.pop("flow_job_id", None)
        state[f"{kind}_simulation_id"] = sim.id
        generated = folder / f"generated_{kind}"
        generated.mkdir(exist_ok=True)
        sim.save_generated_scripts(str(generated))
    write(statefile, state)
    return folder, statefile, state, project, mesh, simulations


def main():
    global GRID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "run", "harvest"])
    parser.add_argument("--case", default="gap6")
    parser.add_argument("--gap-mm", type=float)
    parser.add_argument("--size-mm", type=float)
    parser.add_argument("--grid-refinement", type=int, choices=[1,2])
    args = parser.parse_args()
    folder = (BASE / "runs" / args.case).resolve()
    if folder.parent != (BASE / "runs").resolve():
        raise ValueError("Case must name a direct directory under ExhaustLab/runs")
    folder.mkdir(parents=True, exist_ok=True)
    statefile = folder / "state.json"
    prior = json.loads(statefile.read_text()) if statefile.exists() else {}
    gap = args.gap_mm/1000 if args.gap_mm is not None else prior.get("gap_m", .006)
    size = args.size_mm/1000 if args.size_mm is not None else prior.get("mesh_size_max_m", .0015)
    GRID = tuple((n-1)*args.grid_refinement+1 for n in GRID) if args.grid_refinement else tuple(prior.get("grid_shape", GRID))
    if prior and (not math.isclose(gap, prior["gap_m"]) or not math.isclose(size, prior["mesh_size_max_m"])
                  or GRID != tuple(prior["grid_shape"])):
        raise ValueError("Preserved case geometry/mesh/grid differs. Use a new case name for refinement.")
    client = allsolve.Client(dotenv_file=BASE.parent / ".env", cache_base_dir=str(folder))
    quota = allsolve.get_quota()
    print("Quota", quota, flush=True)
    if args.action == "harvest":
        if not prior:
            raise ValueError("No existing case to harvest")
        state = prior
        project = client.get_project(state["project_id"])
        mesh = next(m for m in project.get_meshes() if m.id == state["mesh_id"])
        sims = {kind: next(s for s in project.get_simulations() if s.id == state[f"{kind}_simulation_id"])
                for kind in ("flow", "electric")}
    else:
        folder, statefile, state, project, mesh, sims = setup(client, args.case, gap, size)
    if args.action == "run":
        if mesh.get_status() != allsolve.Job.SUCCESS:
            if mesh.is_running():
                while mesh.is_running(refresh_delay_s=1):
                    mesh.print_new_loglines()
                if mesh.get_status() != allsolve.Job.SUCCESS:
                    raise RuntimeError("Existing mesh job failed")
            else:
                mesh.run(print_logs=True, on_error=allsolve.OnError.STRICT)
        state["mesh_status"] = str(mesh.get_status())
        state["mesh_job_id"] = mesh._get_job().id
        write(statefile, state)
        for kind, sim in sims.items():
            if sim.get_status() != allsolve.Job.SUCCESS:
                if sim.get_status() == allsolve.Job.NOT_STARTED:
                    sim.run(print_logs=True, on_error=allsolve.OnError.STRICT)
                elif sim.is_running():
                    while sim.is_running(refresh_delay_s=1):
                        sim.print_new_loglines()
                    if sim.get_status() != allsolve.Job.SUCCESS:
                        raise RuntimeError(f"Existing {kind} job failed")
                else:
                    raise RuntimeError(f"Preserved failed {kind} job; fix setup and create a new named simulation")
            state[f"{kind}_status"] = str(sim.get_status())
            state[f"{kind}_job_id"] = sim._get_job().id
            write(statefile, state)
    if args.action in ["run", "harvest"]:
        for kind, sim in sims.items():
            if sim.get_status() != allsolve.Job.SUCCESS:
                print(f"{kind}: {sim.get_status()}; no results harvested", flush=True)
                continue
            data = sim.get_output_data()
            headers = data.get_value_headers()
            print(f"{kind} outputs: {headers}", flush=True)
            result = {name: data.get_values_at(0, 0, name) for name in headers}
            for label in ("sample_xyz_m", "sample_vector", "sample_scalar"):
                chunks = sorted(key for key in result if key.startswith(label + "_part_"))
                if chunks:
                    result[label] = [value for key in chunks for value in result.pop(key)]
            write(folder / f"{kind}_samples.json", result)
            state[f"{kind}_job_id"] = sim._get_job().id
            state[f"{kind}_status"] = str(sim.get_status())
        state["harvested_utc"] = datetime.now(timezone.utc).isoformat()
        write(statefile, state)
    print(state["project_url"], flush=True)


if __name__ == "__main__":
    main()
