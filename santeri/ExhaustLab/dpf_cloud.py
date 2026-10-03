"""Bounded real Allsolve cylinder Darcy/thermal benchmark for ExhaustLab.

Homogeneous axial cartridge surrogate, not pore-resolved wall-flow filtration.
One rank per simulation. `batch` dispatches at most three independent cloud jobs.
Credentials are read only by the SDK from the workspace .env.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import allsolve

BASE = Path(__file__).resolve().parent
RUNS = BASE / "runs"
NAME = "darcy_thermal_v2"
DEFAULT = dict(permeability_m2=2e-8, mu_pa_s=3.35e-5, mass_flow_kg_s=.025,
               inlet_temperature_k=723.15, ambient_temperature_k=293.15,
               cp_j_kg_k=1100., heat_transfer_w_m2_k=20., conductivity_w_m_k=.5)


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def named(items, name):
    return next((item for item in items if item.name == name), None)


def reference(state):
    d, length = state["diameter_m"], state["length_m"]
    area = math.pi*d*d/4
    density = 101325/(287.05*state["inlet_temperature_k"])
    flow = state["mass_flow_kg_s"]/density
    a = state["mass_flow_kg_s"]*state["cp_j_kg_k"]/area
    sink = 4*state["heat_transfer_w_m2_k"]/d
    # Axial first-order upwind diffusion stabilizes the high-Peclet FEM.
    axial_k = state["conductivity_w_m_k"] + a*state["mesh_size_max_m"]/2
    discriminant = math.sqrt(a*a+4*axial_k*sink)
    rp = (a+discriminant)/(2*axial_k)
    rm = -2*sink/(a+discriminant)
    # Stable closed-form solution for T(0)=Tin and T'(L)=0.
    ratio = rm/rp
    denom = 1-ratio*math.exp((rm-rp)*length)
    excess_out = (state["inlet_temperature_k"]-state["ambient_temperature_k"])*math.exp(rm*length)*(1-ratio)/denom
    plug_excess_out = (state["inlet_temperature_k"]-state["ambient_temperature_k"])*math.exp(-sink*length/a)
    return dict(area_m2=area, volume_m3=area*length, density_kg_m3=density,
        flow_m3_s=flow, mean_velocity_m_s=flow/area,
        analytic_pressure_drop_pa=state["mu_pa_s"]*length*flow/(area*state["permeability_m2"]),
        advection_w_m2_k=a, sink_w_m3_k=sink, axial_effective_conductivity_w_m_k=axial_k,
        stabilization_conductivity_w_m_k=axial_k-state["conductivity_w_m_k"],
        exact_stabilized_outlet_temperature_k=state["ambient_temperature_k"]+excess_out,
        plug_outlet_temperature_k=state["ambient_temperature_k"]+plug_excess_out,
        thermal_ntu=sink*length/a)


def weak_form(state):
    ref = reference(state)
    mobility = state["permeability_m2"]/state["mu_pa_s"]
    return f'''# Explicit homogeneous Darcy pressure and plug thermal surrogate.
# fld.v is the scalar pressure unknown (Pa), not electric potential.
form = qs.formulation()
form += qs.integral(reg.cartridge, {mobility!r}*qs.grad(qs.dof(fld.v))*qs.grad(qs.tf(fld.v)))
form += qs.integral(reg.inlet, -{ref['mean_velocity_m_s']!r}*qs.tf(fld.v))
form += qs.integral(reg.cartridge,
    {state['conductivity_w_m_k']!r}*qs.grad(qs.dof(fld.T))*qs.grad(qs.tf(fld.T))
    + {ref['stabilization_conductivity_w_m_k']!r}*qs.compx(qs.grad(qs.dof(fld.T)))*qs.compx(qs.grad(qs.tf(fld.T)))
    + {ref['advection_w_m2_k']!r}*qs.compx(qs.grad(qs.dof(fld.T)))*qs.tf(fld.T)
    + {ref['sink_w_m3_k']!r}*(qs.dof(fld.T)-{state['ambient_temperature_k']!r})*qs.tf(fld.T))
print("Homogeneous Darcy pressure + stabilized plug thermal benchmark")
'''


def sampling(state):
    ref = reference(state)
    mobility = state["permeability_m2"]/state["mu_pa_s"]
    length = state["length_m"]
    radius = state["diameter_m"]/2
    return f'''import numpy as np
area = qs.expression(1).integrate(reg.inlet, 6)
outarea = qs.expression(1).integrate(reg.outlet, 6)
volume = qs.expression(1).integrate(reg.cartridge, 6)
pin = qs.expression(fld.v).integrate(reg.inlet, 6)/area
pout = qs.expression(fld.v).integrate(reg.outlet, 6)/outarea
u = -{mobility!r}*qs.grad(fld.v)
qin = qs.on(reg.cartridge,qs.compx(u)).integrate(reg.inlet, 6)
qout = qs.on(reg.cartridge,qs.compx(u)).integrate(reg.outlet, 6)
tin = qs.expression(fld.T).integrate(reg.inlet, 6)/area
tout = qs.expression(fld.T).integrate(reg.outlet, 6)/outarea
loss = ({ref['sink_w_m3_k']!r}*(qs.expression(fld.T)-{state['ambient_temperature_k']!r})).integrate(reg.cartridge, 6)
diffin = qs.on(reg.cartridge,-{ref['axial_effective_conductivity_w_m_k']!r}*qs.compx(qs.grad(fld.T))).integrate(reg.inlet, 6)
diffout = qs.on(reg.cartridge,-{ref['axial_effective_conductivity_w_m_k']!r}*qs.compx(qs.grad(fld.T))).integrate(reg.outlet, 6)
for label, value in dict(inlet_area_m2=area,outlet_area_m2=outarea,volume_m3=volume,
    inlet_pressure_pa=pin,outlet_pressure_pa=pout,pressure_drop_pa=pin-pout,
    inlet_flux_m3_s=qin,outlet_flux_m3_s=qout,inlet_temperature_k=tin,outlet_temperature_k=tout,
    heat_loss_w=loss,inlet_axial_diffusion_w=diffin,outlet_axial_diffusion_w=diffout).items():
    qs.setoutputvalue(label,float(value))
points = [[float(x),float(r*np.cos(theta)),float(r*np.sin(theta))]
    for x in np.linspace(0,{length!r},31)
    for r in (0.,{radius*.45!r},{radius*.9!r})
    for theta in np.linspace(0,2*np.pi,8,endpoint=False)]
xyz = [v for point in points for v in point]
qs.setoutputvalue('sample_xyz_m',xyz)
qs.setoutputvalue('sample_pressure_pa',qs.allinterpolate(reg.cartridge,qs.expression(fld.v),xyz))
qs.setoutputvalue('sample_temperature_k',qs.allinterpolate(reg.cartridge,qs.expression(fld.T),xyz))
qs.setoutputvalue('sample_axial_velocity_m_s',qs.allinterpolate(reg.cartridge,qs.compx(u),xyz))
'''


def setup(client, case, diameter, length, size):
    folder = RUNS/case
    folder.mkdir(parents=True, exist_ok=True)
    statefile = folder/"state.json"
    state = json.loads(statefile.read_text()) if statefile.exists() else {}
    if state:
        for key, value in [("diameter_m",diameter),("length_m",length),("mesh_size_max_m",size)]:
            if not math.isclose(state[key],value):
                raise ValueError("Use a new case name to change preserved geometry/mesh")
        project = client.get_project(state["project_id"])
    else:
        project = client.create_project(name=f"ExhaustLab {case} porous cylinder benchmark",
            description="Homogeneous effective cartridge Darcy resistance and steady plug thermal field; entered demonstration coefficients; no pore filtration or regeneration.",dimension=3)
        state = dict(case=case,project_id=project.id,project_url=client.get_url(project),
            diameter_m=diameter,length_m=length,mesh_size_max_m=size,created_utc=now(),
            solver_ranks=1,model="homogeneous_darcy_and_stabilized_plug_thermal",**DEFAULT)
        state["reference"] = reference(state)
        write(statefile,state)
    client.set_current_project(project)
    if not state.get("geometry_built"):
        builder = project.geometry_builder()
        if not state.get("geometry_configured"):
            builder.add_cylinder(name="cartridge",position=(0,0,0),axis=(length,0,0),
                radius=diameter/2,alignment=allsolve.CadAlignment.BASE)
            state["geometry_configured"] = True
            write(statefile,state)
        builder.build(print_logs=False,on_error=allsolve.OnError.STRICT)
        state["geometry_built"] = True
        write(statefile,state)
    regions = {r.name:r for r in project.get_regions()}
    if "cartridge" not in regions:
        regions["cartridge"] = project.create_region_rule(name="cartridge",entity_type=allsolve.Region.VOLUME,attribute_path=[("name","cartridge")])
    if "boundary" not in regions:
        regions["boundary"] = project.create_region_computed(name="boundary",entity_type=allsolve.Region.SURFACE,operation=allsolve.RegionOperation.BOUNDARY,source_regions=[regions["cartridge"].id])
    eps=1e-7
    for name,x in [("inlet",0),("outlet",length)]:
        if name not in regions:
            regions[name] = project.create_region_rule(name=name,entity_type=allsolve.Region.SURFACE,
                bounding_box=((x-eps,-diameter,-diameter),(x+eps,diameter,diameter)))
    if "ends" not in regions:
        regions["ends"] = project.create_region_computed(name="ends",entity_type=allsolve.Region.SURFACE,operation=allsolve.RegionOperation.UNION,source_regions=[regions["inlet"].id,regions["outlet"].id])
    if "wall" not in regions:
        regions["wall"] = project.create_region_computed(name="wall",entity_type=allsolve.Region.SURFACE,operation=allsolve.RegionOperation.DIFFERENCE,source_regions=[regions["boundary"].id,regions["ends"].id])
    regions = {r.name:r for r in project.get_regions()}
    counts = {name:len(r.entity_tags) for name,r in regions.items()}
    print(case,"regions",counts,flush=True)
    assert counts["cartridge"]==1 and counts["inlet"]==1 and counts["outlet"]==1 and counts["wall"]==1
    state["region_entity_counts"] = counts
    if not project.get_materials():
        project.create_material(name="Entered equivalent properties",target_region=regions["cartridge"],
            electric_permittivity=1,density=reference(state)["density_kg_m3"],
            heat_capacity=state["cp_j_kg_k"],thermal_conductivity=state["conductivity_w_m_k"])
    physset=named(project.get_physics_sets(),"Darcy and thermal") or project.create_physics_set(name="Darcy and thermal")
    physics=[p for p in project.get_physics() if p.physics_set_id==physset.id]
    pressure=next((p for p in physics if p.definition_id=="electrostatics"),None)
    if pressure is None:
        pressure=physset.add_physics(allsolve.Physics.Electrostatics(target=regions["cartridge"]))
        pressure.add_interactions([allsolve.Interaction.ElectrostaticsConstraint(name="Outlet pressure zero Pa",electrostatics_constraint=0,target=regions["outlet"])])
    thermal=next((p for p in physics if p.definition_id=="heatTransfer"),None)
    if thermal is None:
        thermal=physset.add_physics(allsolve.Physics.HeatTransfer(target=regions["cartridge"]))
        thermal.add_interactions([allsolve.Interaction.HeatTransferTemperatureConstraint(name="Entered inlet temperature",temperature_constraint=state["inlet_temperature_k"],target=regions["inlet"])])
    mesh=named(project.get_meshes(),"cylinder_mesh")
    if mesh is None:
        mesh=project.create_mesh(allsolve.MeshSettings(name="cylinder_mesh",mesh_size_min=size*.6,
            mesh_size_max=size,scale_factor=1,use_mesh_refiner=False,
            node_type=allsolve.CPU.CORES_3_10GB_FAST_START.value,max_run_time_minutes=10))
    sim=named(project.get_simulations(),NAME)
    if sim is None:
        sim=project.create_simulation_static(name=NAME,description="Genuine cylinder pressure and steady averaged temperature field; custom Darcy and thermal weak forms",max_run_time_minutes=10,mesh=mesh,physics_set=physset,nonlinear_solver_tolerance="1e-9",nonlinear_solver_max_iterations="20")
        sim.add_outputs([allsolve.Output.FieldOutput(name="Pressure Pa",expression="v",target=regions["cartridge"]),allsolve.Output.FieldOutput(name="Temperature K",expression="T",target=regions["cartridge"])])
        sim.set_scripts([allsolve.Script(name="darcy_thermal.py",section_name=allsolve.CustomSection.AFTER_FORMULATIONS_CREATED,content=weak_form(state)),allsolve.Script(name="sample_dpf.py",section_name=allsolve.CustomSection.AFTER_ALL,content=sampling(state))])
    if state.get("simulation_id") not in (None,sim.id):
        history=folder/"original_surface_exports"
        history.mkdir(exist_ok=True)
        for filename in ["state.json","samples.json","validation.json","sample_dpf.py"]:
            if (folder/filename).exists() and not (history/filename).exists():
                shutil.copy2(folder/filename,history/filename)
        state["original_simulation_id"]=state["simulation_id"]
    state.update(mesh_id=mesh.id,simulation_id=sim.id)
    generated=folder/"generated"
    generated.mkdir(exist_ok=True)
    sim.save_generated_scripts(str(generated))
    (folder/"darcy_thermal.py").write_text(weak_form(state),encoding="utf-8")
    (folder/"sample_dpf.py").write_text(sampling(state),encoding="utf-8")
    write(statefile,state)
    return folder,state,mesh,sim


def validate(folder,state,result):
    ref=state["reference"]
    dp=float(result["pressure_drop_pa"])
    qin,qout=map(float,(result["inlet_flux_m3_s"],result["outlet_flux_m3_s"]))
    tout=float(result["outlet_temperature_k"])
    pressure_error=abs(dp/ref["analytic_pressure_drop_pa"]-1)
    # The imposed Neumann value is velocity on the finite-element inlet face.
    # Compare conservation against that mesh's face area, and separately gate
    # geometric area error relative to the analytic curved cylinder.
    prescribed_fe_flow=float(result["inlet_area_m2"])*ref["mean_velocity_m_s"]
    flux_error=max(abs(qin/prescribed_fe_flow-1),abs(qout/prescribed_fe_flow-1),abs(qin-qout)/prescribed_fe_flow)
    geometric_area_error=abs(float(result["inlet_area_m2"])/ref["area_m2"]-1)
    analytic_flow_error=max(abs(qin/ref["flow_m3_s"]-1),abs(qout/ref["flow_m3_s"]-1))
    volume_error=abs(float(result["volume_m3"])/ref["volume_m3"]-1)
    thermal_error=abs(tout-ref["exact_stabilized_outlet_temperature_k"])
    plug_relative_excess_error=abs(tout-ref["plug_outlet_temperature_k"])/(ref["plug_outlet_temperature_k"]-state["ambient_temperature_k"])
    actualexcess=(tout-state["ambient_temperature_k"])/(state["inlet_temperature_k"]-state["ambient_temperature_k"])
    thermal_factor=-math.log(actualexcess)/ref["thermal_ntu"] if 0<actualexcess<1 else None
    xyz=result["sample_xyz_m"]
    expected=[ref["analytic_pressure_drop_pa"]*(1-xyz[3*i]/state["length_m"]) for i in range(len(result["sample_pressure_pa"]))]
    pressure_profile_error=math.sqrt(sum((actual-target)**2 for actual,target in zip(result["sample_pressure_pa"],expected))/sum(target**2 for target in expected))
    velocity_profile_error=math.sqrt(sum((u/ref["mean_velocity_m_s"]-1)**2 for u in result["sample_axial_velocity_m_s"])/len(result["sample_axial_velocity_m_s"]))
    gates=dict(pressure_relative_error=pressure_error<.005,flux_relative_error=flux_error<.005,
        inlet_geometric_area_relative_error=geometric_area_error<.005,
        pressure_profile_relative_l2=pressure_profile_error<.005,velocity_profile_relative_l2=velocity_profile_error<.005,
        cylinder_volume_relative_error=volume_error<.005,thermal_exact_error_k=thermal_error<.5,
        temperature_bounds=state["ambient_temperature_k"]<tout<state["inlet_temperature_k"],
        thermal_physical_plug_relative_excess_error=plug_relative_excess_error<.005)
    validation=dict(passed=all(gates.values()),gates=gates,pressure_relative_error=pressure_error,
        flux_relative_error=flux_error,inlet_geometric_area_relative_error=geometric_area_error,
        analytic_curved_cylinder_flow_relative_error=analytic_flow_error,prescribed_fe_flow_m3_s=prescribed_fe_flow,
        pressure_profile_relative_l2=pressure_profile_error,velocity_profile_relative_l2=velocity_profile_error,
        cylinder_volume_relative_error=volume_error,thermal_exact_error_k=thermal_error,
        pressure_factor=dp/ref["analytic_pressure_drop_pa"],thermal_factor=thermal_factor,
        plug_outlet_error_k=abs(tout-ref["plug_outlet_temperature_k"]),
        plug_relative_excess_error=plug_relative_excess_error,
        source_hashes={f:digest(folder/f) for f in ["state.json","samples.json","darcy_thermal.py","sample_dpf.py"]},checked_utc=now())
    write(folder/"validation.json",validation)
    print(state["case"],"validation",{k:v for k,v in validation.items() if k not in ("source_hashes",)},flush=True)
    return validation


def harvest(folder,state,mesh,sim):
    state.update(mesh_status=str(mesh.get_status()),mesh_job_id=mesh._get_job().id,
        simulation_status=str(sim.get_status()),simulation_job_id=sim._get_job().id,harvested_utc=now())
    logs=sim._get_job().get_logs(limit=1000)
    (folder/"solver.log").write_text("\n".join(logs)+"\n",encoding="utf-8")
    state["observed_solver_banner"]=next((line for line in logs if "Quanscient Allsolve" in line),None)
    write(folder/"state.json",state)
    if sim.get_status()!=allsolve.Job.SUCCESS:
        return
    data=sim.get_output_data()
    result={header:data.get_values_at(0,0,header) for header in data.get_value_headers()}
    result={key:(value[0] if isinstance(value,list) and len(value)==1 and not key.startswith('sample_') else value) for key,value in result.items()}
    write(folder/"samples.json",result)
    validate(folder,state,result)


def manifest():
    cases=[]
    for folder in sorted(RUNS.glob("dpf_d*_l*")):
        if not (folder/"validation.json").exists():
            continue
        state=json.loads((folder/"state.json").read_text())
        validation=json.loads((folder/"validation.json").read_text())
        samples=json.loads((folder/"samples.json").read_text())
        if not validation["passed"] or "fine" in folder.name or "refined" in folder.name:
            continue
        if any(digest(folder/f)!=sha for f,sha in validation["source_hashes"].items()):
            raise ValueError(f"Stale field validation for {folder.name}")
        cases.append(dict(case=folder.name,diameter_m=state["diameter_m"],length_m=state["length_m"],
            pressure_factor=validation["pressure_factor"],thermal_factor=validation["thermal_factor"],
            pressure_drop_pa=samples["pressure_drop_pa"],inlet_temperature_k=samples["inlet_temperature_k"],outlet_temperature_k=samples["outlet_temperature_k"],
            project_id=state["project_id"],project_url=state["project_url"],mesh_job_id=state["mesh_job_id"],simulation_job_id=state["simulation_job_id"],
            solver_ranks=1,validation=validation,source_hashes={str((folder/f).relative_to(BASE)).replace('\\','/'):digest(folder/f) for f in ["state.json","samples.json","validation.json","darcy_thermal.py","sample_dpf.py","solver.log"]},
            reference=state["reference"],coefficients={key:state[key] for key in DEFAULT}))
    parallelfile=RUNS/"dpf_parallel_batch.json"
    parallel=json.loads(parallelfile.read_text()) if parallelfile.exists() else {}
    meshfile=RUNS/"dpf_mesh_comparison.json"
    refinement=json.loads(meshfile.read_text()) if meshfile.exists() else {}
    data=dict(model="homogeneous_darcy_and_stabilized_plug_thermal",sdk_version="0.5.2",created_utc=now(),
        scope="Equivalent axial cartridge permeability and averaged steady gas temperature; no pore filtration, charging, soot oxidation, catalytic conversion or transient hot spots.",
        ready=len(cases)==9 and bool(refinement.get("passed")),expected_geometry_count=9,
        solver=dict(banner="Quanscient Allsolve 484 int64/float64",sdk_version="0.5.2",ranks_per_simulation=1,
            note="No distributed-solver scaling or runtime speedup measurement was performed."),
        concurrency=dict(max_active_jobs=parallel.get("max_active_jobs",1),peak_active_jobs=parallel.get("peak_active_jobs",1),
            requested_geometry_count=len(parallel.get("requested_cases",[])),verified_geometry_count=len(cases),
            note="Client dispatch overlap of independent one-rank cloud jobs; not a solver runtime speedup benchmark.",
            evidence_path="runs/dpf_parallel_batch.json" if parallel else None,evidence_sha256=digest(parallelfile) if parallel else None),
        mesh_verification=dict(passed=refinement.get("passed",False),geometry="160 mm diameter, 200 mm active length",
            coarse_mesh_m=refinement.get("coarse_mesh_m"),fine_mesh_m=refinement.get("fine_mesh_m"),
            pressure_relative_change=refinement.get("pressure_relative_change"),outlet_temperature_change_k=refinement.get("outlet_temperature_change_k"),
            evidence_path="runs/dpf_mesh_comparison.json" if refinement else None,evidence_sha256=digest(meshfile) if refinement else None),cases=cases)
    write(RUNS/"dpf_cloud_manifest.json",data)
    print("Manifest verified cases",len(cases),flush=True)


def mesh_comparison():
    coarse=RUNS/"dpf_d160_l200"
    fine=RUNS/"dpf_d160_l200_refined"
    if not (fine/"validation.json").exists():
        return
    states=[json.loads((folder/"state.json").read_text()) for folder in [coarse,fine]]
    values=[json.loads((folder/"samples.json").read_text()) for folder in [coarse,fine]]
    validations=[json.loads((folder/"validation.json").read_text()) for folder in [coarse,fine]]
    pressurechange=abs(values[1]["pressure_drop_pa"]/values[0]["pressure_drop_pa"]-1)
    outletchange=abs(values[1]["outlet_temperature_k"]-values[0]["outlet_temperature_k"])
    factorchange=abs(validations[1]["thermal_factor"]-validations[0]["thermal_factor"])
    pressurefieldchange=math.sqrt(sum((a-b)**2 for a,b in zip(values[0]["sample_pressure_pa"],values[1]["sample_pressure_pa"]))/sum(a*a for a in values[0]["sample_pressure_pa"]))
    thermalfieldchange=math.sqrt(sum((a-b)**2 for a,b in zip(values[0]["sample_temperature_k"],values[1]["sample_temperature_k"]))/len(values[0]["sample_temperature_k"]))
    data=dict(coarse_case=coarse.name,fine_case=fine.name,coarse_mesh_m=states[0]["mesh_size_max_m"],fine_mesh_m=states[1]["mesh_size_max_m"],
        passed=all(v["passed"] for v in validations) and pressurechange<.005 and outletchange<.5 and factorchange<.02,
        pressure_relative_change=pressurechange,outlet_temperature_change_k=outletchange,thermal_factor_change=factorchange,
        pressure_field_relative_l2_change=pressurefieldchange,temperature_field_rms_change_k=thermalfieldchange,
        scope="Central geometry only; mesh-dependent upwind diffusion explicitly included, bounded vs physical plug-flow and exact stabilized PDE.",
        source_hashes={str((folder/f).relative_to(BASE)).replace('\\','/'):digest(folder/f) for folder in [coarse,fine] for f in ["state.json","samples.json","validation.json"]})
    write(RUNS/"dpf_mesh_comparison.json",data)
    print("Mesh comparison",data,flush=True)


def batch(client,requested,max_active=3):
    jobs=[setup(client,case,d,l,size) for case,d,l,size in requested]
    # Bounded concurrency applies across meshing and solving jobs.
    pending=list(jobs)
    active=[]
    history=[]
    while pending or active:
        while pending and len(active)<max_active:
            folder,state,mesh,sim=pending.pop(0)
            if mesh.get_status()==allsolve.Job.SUCCESS:
                stage="simulation"
                if sim.get_status()==allsolve.Job.NOT_STARTED:
                    sim.start()
                    state["simulation_started_utc"]=now()
                    state["simulation_job_id"]=sim._get_job().id
            else:
                stage="mesh"
                if not mesh.is_running():
                    mesh.start()
                    state["mesh_started_utc"]=now()
                    state["mesh_job_id"]=mesh._get_job().id
            write(folder/"state.json",state)
            print(state["case"],"dispatched",stage,flush=True)
            active.append([folder,state,mesh,sim,stage])
            history.append(dict(at_utc=now(),event="dispatch",case=state["case"],stage=stage,active_jobs=len(active)))
        for item in list(active):
            folder,state,mesh,sim,stage=item
            current=mesh if stage=="mesh" else sim
            if current.is_running(refresh_delay_s=1):
                continue
            status=current.get_status()
            if status!=allsolve.Job.SUCCESS:
                current.print_new_loglines()
                (folder/f"failed_{stage}.log").write_text("\n".join(current.get_logs(limit=1000))+"\n",encoding="utf-8")
                state[f"{stage}_status"]=str(status)
                state[f"{stage}_failed_utc"]=now()
                write(folder/"state.json",state)
                raise RuntimeError(f"{state['case']} {stage} failed: {status}")
            if stage=="mesh":
                state["mesh_status"]=str(status)
                state["mesh_finished_utc"]=now()
                if sim.get_status()==allsolve.Job.NOT_STARTED:
                    sim.start()
                    state["simulation_started_utc"]=now()
                    state["simulation_job_id"]=sim._get_job().id
                write(folder/"state.json",state)
                item[4]="simulation"
                print(state["case"],"dispatched simulation",flush=True)
                history.append(dict(at_utc=now(),event="transition",case=state["case"],stage="simulation",active_jobs=len(active)))
            else:
                state["simulation_finished_utc"]=now()
                harvest(folder,state,mesh,sim)
                active.remove(item)
                history.append(dict(at_utc=now(),event="complete",case=state["case"],stage="simulation",active_jobs=len(active)))
        if active:
            time.sleep(2)
    historyname="dpf_parallel_batch.json" if len(requested)>1 else "dpf_single_batch.json"
    write(RUNS/historyname,dict(max_active_jobs=max_active,peak_active_jobs=max((e["active_jobs"] for e in history),default=0),
        requested_cases=[row[0] for row in requested],events=history,
        note="Concurrent independent one-rank jobs; client dispatch overlap, not a distributed-solver scaling benchmark."))
    mesh_comparison()
    manifest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["setup","run","batch","harvest","manifest","revalidate"])
    parser.add_argument("--case",default="dpf_d160_l200")
    parser.add_argument("--diameter-mm",type=float,default=160)
    parser.add_argument("--length-mm",type=float,default=200)
    parser.add_argument("--size-mm",type=float,default=10)
    args=parser.parse_args()
    if args.action=="manifest":
        manifest(); return
    if args.action=="revalidate":
        for folder in sorted(RUNS.glob("dpf_d*_l*")):
            if (folder/"samples.json").exists():
                validate(folder,json.loads((folder/"state.json").read_text()),json.loads((folder/"samples.json").read_text()))
        mesh_comparison(); manifest(); return
    (RUNS/"dpf_sdk_cache").mkdir(exist_ok=True)
    client=allsolve.Client(dotenv_file=BASE.parent/".env",cache_base_dir=str(RUNS/"dpf_sdk_cache"))
    if args.action=="batch":
        requested=[(f"dpf_d{d}_l{l}",d/1000,l/1000,args.size_mm/1000) for d in [120,160,200] for l in [150,200,250]]
        batch(client,requested); return
    if not args.case.startswith("dpf_") or (RUNS/args.case).resolve().parent!=RUNS.resolve():
        raise ValueError("Use direct dpf_ case directory")
    job=setup(client,args.case,args.diameter_mm/1000,args.length_mm/1000,args.size_mm/1000)
    if args.action=="run":
        batch(client,[(args.case,args.diameter_mm/1000,args.length_mm/1000,args.size_mm/1000)],1)
    elif args.action=="harvest":
        harvest(*job); manifest()


if __name__=="__main__":
    main()
