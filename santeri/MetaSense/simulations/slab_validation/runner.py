"""Launch/harvest a real periodic optical slab benchmark; never rerun finished jobs.

Run with MetaSense's Python from any directory. Credentials remain in root .env.
Actions: setup, inspect, sync, repair, larger, periodic, advance, harvest, refine, fields, logs, archive-default.
Each preserves cloud results.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import allsolve
from allsolve.api import get_api, get_auth

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
STATE = HERE / "state.json"
WAVELENGTH = 1e-6
PERIOD = 5e-7
INDEX = 1.5
THICKNESS = WAVELENGTH / (4 * INDEX)
CLEARANCE = WAVELENGTH / 2


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def connect() -> allsolve.Client:
    return allsolve.Client(dotenv_file=str(HERE.parents[2] / ".env"), cache_base_dir=str(HERE))


def check_quota() -> None:
    quota = allsolve.get_quota()
    print(json.dumps({"available_organization_cores": quota.max_concurrent_cores - quota.total_running_cores,
                      "team_enforcement": quota.team_quota_enforcement_active}), flush=True)
    if quota.max_concurrent_cores - quota.total_running_cores < 3:
        raise RuntimeError("No capacity for the three-core benchmark; retry advance later")


def setup(client: allsolve.Client) -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    existing = client.get_current_project()
    if existing is not None:
        raise RuntimeError("Current project already exists without state; inspect it rather than rebuilding")
    check_quota()
    project = client.create_project(name="MetaSense optical slab validation",
        description="Normal incidence periodic lossless slab benchmark at 1000 nm. Assumed n=1.5; not a sensor or measured material.")
    client.set_current_project(project)
    state = {"project_id": project.id, "project_url": client.get_url(project), "created_at": datetime.now(timezone.utc).isoformat(),
             "sdk_version": version("allsolve"), "stage": "building", "runs": []}
    write_json(STATE, state)
    project.create_variables([
        ("wavelength", WAVELENGTH, "Vacuum wavelength, m"), ("period", PERIOD, "Lateral period, m"),
        ("thickness", THICKNESS, "Slab thickness, m"), ("clearance", CLEARANCE, "Air on either side, m"),
        ("n_slab", INDEX, "Assumed real lossless index; n=1 control"), ("frequency", "299792458/wavelength", "Hz"),
        ("E0", 1, "Incident peak x-polarized field, V/m")])
    gb = project.geometry_builder()
    for name, z, height in [("air_left", "-clearance", "clearance"), ("slab", 0, "thickness"),
                            ("air_right", "thickness", "clearance")]:
        gb.add_box(name=name, position=(0, 0, z), size=("period", "period", height), alignment=allsolve.CadAlignment.CORNER)
    gb.build(print_logs=True, on_error=allsolve.OnError.STRICT)
    eps = 1e-12
    p, d, c = PERIOD, THICKNESS, CLEARANCE
    regions = {}
    for name, lo, hi in [("air_left", -c, 0), ("slab", 0, d), ("air_right", d, d+c), ("domain", -c, d+c)]:
        regions[name] = project.create_region_rule(name=name, entity_type=allsolve.Region.VOLUME,
            bounding_box=((-eps, -eps, lo-eps), (p+eps, p+eps, hi+eps)))
    boxes = {"entrance": ((-eps,-eps,-c-eps),(p+eps,p+eps,-c+eps)),
             "exit": ((-eps,-eps,d+c-eps),(p+eps,p+eps,d+c+eps)),
             "xmin": ((-eps,-eps,-c-eps),(eps,p+eps,d+c+eps)),
             "xmax": ((p-eps,-eps,-c-eps),(p+eps,p+eps,d+c+eps)),
             "ymin": ((-eps,-eps,-c-eps),(p+eps,eps,d+c+eps)),
             "ymax": ((-eps,p-eps,-c-eps),(p+eps,p+eps,d+c+eps))}
    for name, bbox in boxes.items():
        regions[name] = project.create_region_rule(name=name, entity_type=allsolve.Region.SURFACE, bounding_box=bbox)
    air = project.create_region_computed(name="air", entity_type=allsolve.Region.VOLUME,
        operation=allsolve.RegionOperation.UNION, source_regions=[regions["air_left"],regions["air_right"]])
    for name, target, epsilon in [("Vacuum benchmark exterior",air,"epsilon0"), ("Assumed lossless slab",regions["slab"],"n_slab*n_slab*epsilon0")]:
        project.create_material(name=name, target_region=target, electric_permittivity=epsilon,
            magnetic_permeability="mu0", electric_conductivity="0")
    physics_set = project.get_default_physics_set()
    em = physics_set.add_physics(allsolve.Physics.ElectromagneticWaves(target=regions["domain"]))
    em.set_field_interpolation_order(2)
    em.save()
    interactions = [allsolve.Interaction.ElectromagneticWavesAbsorbingBoundary(name="Open entrance", target=regions["entrance"]),
                    allsolve.Interaction.ElectromagneticWavesAbsorbingBoundary(name="Open exit", target=regions["exit"])]
    for axis, direction in [("x",(1,0,0)),("y",(0,1,0))]:
        interactions.append(allsolve.Interaction.ElectromagneticWavesPeriodicity(name=f"Zero phase {axis} periodicity",
            electromagnetic_waves_periodicity_anti_periodicity=False, target_1=regions[axis+"min"], target_2=regions[axis+"max"],
            electromagnetic_waves_periodicity_translation_direction=direction,
            electromagnetic_waves_periodicity_translation_distance="period"))
    em.add_interactions(interactions)
    sweep = project.create_variable_overrides(name="Vacuum control and dielectric slab", overrides=[("n_slab",[1,INDEX])],
        sweep_type=allsolve.SweepType.CARTESIAN_PRODUCT)
    state.update(stage="configured", physics_set_id=physics_set.id, sweep_id=sweep.id,
        inputs={"wavelength_m":WAVELENGTH,"period_m":PERIOD,"slab_thickness_m":THICKNESS,"clearance_m":CLEARANCE,
                "indices":[1,INDEX],"exterior_index":1,"E0_V_per_m":1,"field_order":2,
                "polarization":"x","propagation":"+z","periodic_multiplier_order":2,
                "phase_convention":"exp(+i omega t); harmonic 2=sin, 3=cos",
                "boundary":"zero phase lateral periodicity; normal incidence first order absorbing ends"})
    write_json(STATE,state)
    return state


def add_run(project: allsolve.Project, state: dict, name: str, resolution: int) -> None:
    if any(r["name"]==name for r in state["runs"]):
        return
    slab = next(r for r in project.get_regions() if r.name=="slab")
    mesh = project.create_mesh(allsolve.MeshSettings(name=f"{name} mesh", max_run_time_minutes=10,
        node_type=allsolve.CPU.CORES_3_10GB_FAST_START.value, scale_factor=1,
        mesh_size_max=WAVELENGTH/resolution, mesh_size_min=WAVELENGTH/(INDEX*resolution*2),
        use_mesh_refiner=False, refinements=[allsolve.MeshRefinement(region=slab,max_size=WAVELENGTH/(INDEX*resolution))]))
    sim = project.create_simulation_harmonic(name=name,description="Periodic normal incidence dielectric slab R/T and empty control",
        max_run_time_minutes=10,mesh=mesh,physics_set=state["physics_set_id"],variable_overrides=state["sweep_id"],
        fundamental_frequency="frequency",solver_tolerance="1e-9")
    node=allsolve.CPU.CORES_4_64GB if resolution>12 else allsolve.CPU.CORES_3_10GB_FAST_START
    sim.set_runtime(allsolve.Runtime(node_type=node))
    sim.disabled_script_sections=[allsolve.DisableableSection.FORMULATIONS,allsolve.DisableableSection.SOLVE]
    sim.save()
    script=(HERE/"source_readout.py").read_text(encoding="utf-8")
    sim.set_scripts([allsolve.Script(name="source_readout.py",section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,content=script)])
    sim.add_outputs([allsolve.Output.FieldOutput(name="E sine", expression="harm(2,E)"),
                     allsolve.Output.FieldOutput(name="E cosine", expression="harm(3,E)")])
    run={"name":name,"mesh_id":mesh.id,"simulation_id":sim.id,"resolution_per_vacuum_wavelength":resolution,
         "mesh_size_max_m":WAVELENGTH/resolution,"slab_mesh_size_max_m":WAVELENGTH/(INDEX*resolution),
         "source_sha256":hashlib.sha256(script.encode()).hexdigest(),"mesh_status":None,"simulation_status":None,"node_type":node.value}
    state["runs"].append(run)
    write_json(STATE,state)
    dump_generated(sim,name)
    check_quota()
    mesh.start()
    print(f"Started {name} mesh {mesh.id}",flush=True)


def dump_generated(sim: allsolve.Simulation,name: str) -> None:
    folder=RESULTS/name/"generated"
    folder.mkdir(parents=True,exist_ok=True)
    sim.save_generated_scripts(str(folder))
    with get_api() as api:
        generated=api.get_generated_scripts(authorization=get_auth(),project_id=sim.project_id,simulation_id=sim.id)
    (folder/"main.py").write_text(generated.simulation.code,encoding="utf-8")


def advance(project: allsolve.Project,state: dict) -> None:
    for run in state["runs"]:
        mesh=next(m for m in project.get_meshes() if m.id==run["mesh_id"])
        sim=next(s for s in project.get_simulations() if s.id==run["simulation_id"])
        run["mesh_status"]=mesh.get_status()
        run["simulation_status"]=sim.get_status()
        run["mesh_job_id"]=mesh._get_job().id if mesh._get_job() else None
        run["simulation_job_id"]=sim._get_job().id if sim._get_job() else None
        if run["mesh_status"]==allsolve.Job.SUCCESS and run["simulation_status"] is None:
            check_quota()
            sim.start()
            print(f"Started simulation {sim.id}",flush=True)
            run["simulation_status"]=sim.get_status()
        print(json.dumps(run),flush=True)
    write_json(STATE,state)


def repair(project: allsolve.Project,state: dict,larger: bool=False) -> None:
    """Create a revised simulation on the successful mesh; retain the failed attempt."""
    script=(HERE/"source_readout.py").read_text(encoding="utf-8")
    digest=hashlib.sha256(script.encode()).hexdigest()
    for run in state["runs"]:
        old=next(s for s in project.get_simulations() if s.id==run["simulation_id"])
        if old.get_status()!=allsolve.Job.ERROR:
            continue
        if digest==run["source_sha256"] and not larger:
            raise RuntimeError("Refuse an unchanged retry; diagnose the failure first")
        snapshot=dict(run)
        snapshot["simulation_status"]=old.get_status()
        snapshot["simulation_job_id"]=old._get_job().id
        state.setdefault("failed_attempts",[]).append(snapshot)
        revision=1+sum(a["name"]==run["name"] for a in state["failed_attempts"])
        sim=project.create_simulation_harmonic(name=f'{run["name"]} revision {revision}',
            description="Revised plane-wave source; failed attempts preserved",
            max_run_time_minutes=10,mesh=run["mesh_id"],physics_set=state["physics_set_id"],
            variable_overrides=state["sweep_id"],fundamental_frequency="frequency",solver_tolerance="1e-9")
        node=allsolve.CPU.CORES_4_64GB if larger else allsolve.CPU.CORES_3_10GB_FAST_START
        sim.set_runtime(allsolve.Runtime(node_type=node))
        sim.disabled_script_sections=[allsolve.DisableableSection.FORMULATIONS,allsolve.DisableableSection.SOLVE]
        sim.save()
        sim.set_scripts([allsolve.Script(name="source_readout.py",section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,content=script)])
        sim.add_outputs([allsolve.Output.FieldOutput(name="E sine",expression="harm(2,E)"),
                         allsolve.Output.FieldOutput(name="E cosine",expression="harm(3,E)")])
        run.update(simulation_id=sim.id,simulation_job_id=None,simulation_status=None,source_sha256=digest,node_type=node.value)
        write_json(STATE,state)
        dump_generated(sim,f'{run["name"]}_revision_{revision}')


def download_fields(project: allsolve.Project,state: dict) -> None:
    for run in state["runs"]:
        sim=next(s for s in project.get_simulations() if s.id==run["simulation_id"])
        if sim.get_status()!=allsolve.Job.SUCCESS:
            continue
        paths=[]
        data=sim.get_output_data(refresh=True)
        for index in range(data.get_sweep_count()):
            folder=RESULTS/run["name"]/sim.id/"fields"/f"sweep_{index}"
            folder.mkdir(parents=True,exist_ok=True)
            for name in ["E sine","E cosine"]:
                sim.save_output_field(name=name,output_dir=str(folder),sweep_index=index,refresh=False)
            paths.extend(str(p.relative_to(HERE)).replace("\\","/") for p in folder.iterdir() if p.is_file())
        run["field_output_files"]=paths
    write_json(STATE,state)


def periodic_revision(project: allsolve.Project,state: dict) -> None:
    """Retain the default-mortar study and reuse both meshes with explicit order 2."""
    if state["inputs"].get("periodic_multiplier_order")==2:
        return
    if any(next(s for s in project.get_simulations() if s.id==r["simulation_id"]).get_status()!=allsolve.Job.SUCCESS for r in state["runs"]):
        raise RuntimeError("Preserve/finish current runs before creating a periodicity study")
    state["default_periodicity_runs"]=list(state["runs"])
    state["inputs"]["periodic_multiplier_order"]=2
    state["runs"]=[dict(r) for r in state["runs"]]
    script=(HERE/"source_readout.py").read_text(encoding="utf-8")
    for run in state["runs"]:
        sim=project.create_simulation_harmonic(name=run["name"]+" periodic order 2",
            description="Explicit second-order periodic mortar trace; same successful mesh and source",
            max_run_time_minutes=10,mesh=run["mesh_id"],physics_set=state["physics_set_id"],
            variable_overrides=state["sweep_id"],fundamental_frequency="frequency",solver_tolerance="1e-9")
        node=allsolve.CPU.CORES_4_64GB if run["name"]=="fine" else allsolve.CPU.CORES_3_10GB_FAST_START
        sim.set_runtime(allsolve.Runtime(node_type=node))
        sim.disabled_script_sections=[allsolve.DisableableSection.FORMULATIONS,allsolve.DisableableSection.SOLVE]
        sim.save()
        sim.set_scripts([allsolve.Script(name="source_readout.py",section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,content=script)])
        run.update(simulation_id=sim.id,simulation_job_id=None,simulation_status=None,
            source_sha256=hashlib.sha256(script.encode()).hexdigest(),node_type=node.value)
        run.pop("field_output_files",None)
        dump_generated(sim,run["name"]+"_periodic2")
    write_json(STATE,state)
    advance(project,state)


def save_logs(project: allsolve.Project,state: dict) -> None:
    for run in state["runs"]:
        sim=next(s for s in project.get_simulations() if s.id==run["simulation_id"])
        print(run["name"],sim.get_status(),flush=True)
        if sim._get_job() is None:
            continue
        data=sim.get_output_data(refresh=True)
        for row in data._get_simulations_sorted():
            job=allsolve.Job(project.id,row.job_id)
            events=job._get_logs(limit=1000)
            folder=RESULTS/run["name"]/sim.id
            folder.mkdir(parents=True,exist_ok=True)
            write_json(folder/f"child_{row.job_index}_logs.json",{"job_id":row.job_id,"events":[x.model_dump(mode="json") for x in events]})
            print("\n".join(x.message for x in events[-12:]),flush=True)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["setup","inspect","sync","repair","larger","periodic","advance","harvest","refine","fields","logs","archive-default"])
    args=parser.parse_args()
    RESULTS.mkdir(parents=True,exist_ok=True)
    client=connect()
    state=setup(client) if args.action=="setup" else json.loads(STATE.read_text(encoding="utf-8"))
    project=client.get_project(state["project_id"])
    if args.action=="setup":
        add_run(project,state,"coarse",12)
    elif args.action=="refine":
        add_run(project,state,"fine",18)
    elif args.action in ["repair","larger"]:
        repair(project,state,larger=args.action=="larger")
        advance(project,state)
    elif args.action=="fields":
        download_fields(project,state)
    elif args.action=="periodic":
        periodic_revision(project,state)
    elif args.action=="logs":
        save_logs(project,state)
    elif args.action=="archive-default":
        if not state.get("default_periodicity_runs"):
            raise RuntimeError("No completed default-periodicity study to archive")
        from harvest import harvest
        baseline=copy.deepcopy(state)
        baseline["runs"]=baseline.pop("default_periodicity_runs")
        baseline["inputs"]["periodic_multiplier_order"]=0
        harvest(project,baseline,RESULTS/"default_periodicity")
    elif args.action=="sync":
        script=(HERE/"source_readout.py").read_text(encoding="utf-8")
        for run in state["runs"]:
            sim=next(s for s in project.get_simulations() if s.id==run["simulation_id"])
            if sim.get_status() is not None:
                raise RuntimeError("Never modify a started simulation; create a separate revision")
            sim.set_scripts([allsolve.Script(name="source_readout.py",section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,content=script)])
            run["source_sha256"]=hashlib.sha256(script.encode()).hexdigest()
        write_json(STATE,state)
    elif args.action in ["advance","harvest"]:
        advance(project,state)
        if args.action=="harvest":
            from harvest import harvest
            harvest(project,state,RESULTS)
    else:
        for sim in project.get_simulations():
            dump_generated(sim,sim.name)
        print(json.dumps(state,indent=2),flush=True)


if __name__=="__main__":
    main()
