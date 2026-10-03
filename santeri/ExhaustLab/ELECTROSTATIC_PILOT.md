# ExhaustLab

Working local comparison of three **cold, low-flow electrostatic pilot collectors**. Genuine Allsolve 3D velocity/pressure and potential/electric-field solves are verified against rectangular-channel flow and uniform-field benchmarks. Particle capture is calculated separately by local trajectories through those exported fields.

The preserved pilot interface is at <http://127.0.0.1:5176/electrostatic/>. The main interface now hosts the diesel filter installation planner. API: <http://127.0.0.1:8003/>. Start both servers from this folder using the installed bundled Python:

```powershell
$exhaustPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $exhaustPython server.py
```

The optional `start.ps1` launcher also finds this runtime and detects an already-running app; it accepts an alternative interpreter with `-Python`. The web app needs only NumPy and Python's standard library; it reads recorded results and does not launch cloud jobs or load API keys.

## Bounded model and result

One 60 mm long, 20 mm wide plate gap carries **0.2 L/min** of conditioned gas with density 1.2 kg/m³ and viscosity 1.81e-5 Pa·s. Compare gaps of 4, 6 and 8 mm. Reynolds numbers are approximately 18.4, 17.0 and 15.8. The inlet is the developed rectangular-duct profile; lateral walls are no-slip, outlet pressure is zero gauge. Plates are at 0/200 V; other electric boundaries are insulating.

Allsolve runs the explicit stationary incompressible weak form. For the reference axial developed profile, the advective term vanishes. This formulation and its validation support straight channels; bends, baffles and developing flows require further physics work.

At **1 µm diameter, +30 elementary charges and 200 V**, using the finest verified fields and 1,536 flux-weighted inlet seeds:

| Plate gap | Conditional single-pass capture | Simulated pressure drop |
|---|---:|---:|
| 4 mm | 57.6% | 0.03883 Pa |
| 6 mm | 37.9% | 0.01240 Pa |
| 8 mm | 28.5% | 0.00567 Pa |

All nominal charged trajectories resolve; hits are on the grounded collector. Zero-charge cases give zero capture in this transport model; 0.025–0.361% of inlet weight remains unresolved at the 30 s integration limit. Capture, outlet and unresolved weight always sum to one.

The 4 mm gap leads modeled capture at these fixed inputs and also has the highest pressure penalty. Enter actual prototype costs and supply power in the app to compare budget feasibility. There are no researched or assumed build prices. Pressure × flow is ideal hydraulic power; the electrostatic solve does not estimate charging or supply consumption.

## Numerical checks and provenance

Both coarse and fine 3D meshes pass volume, boundary, flow conservation, velocity-profile, pressure-gradient and electric-field checks. Direct finite-element flux mismatch is below 0.002% in the fine cases. Independent mesh refinement changes fitted pressure by at most 0.0164% and velocity L2 by at most 0.079%.

Nominal capture changes in the tested refinements are below the entered **one-percentage-point** criterion: timestep change 0; inlet-grid change at most 0.945 pp; exported-field-grid change at most 0.871 pp; mesh change at most 0.00577 pp. This is numerical refinement evidence, not a combined uncertainty bound or physical calibration. Inlet quadrature is the largest remaining tested effect for the 4 mm case.

- [Fine nominal comparison CSV](runs/fine_nominal_comparison.csv) and [size/charge sensitivity CSV](runs/fine_sensitivity_comparison.csv).
- [Fine comparison with convergence evidence](runs/fine_comparison.json) and [all field mesh comparisons](runs/all_field_convergence.json).
- Each `runs/gap*` folder contains `state.json` with exact project, mesh, simulation and job IDs; genuine `flow_samples.json`/`electric_samples.json`; validation with SHA256 hashes; and particle/convergence reports.
- [Particle model](PARTICLE_MODEL.md) defines Stokes/Cunningham drag, inlet weighting, ideal absorbing walls, midpoint integration and unresolved accounting.
- [SDK findings](sdk_flow_feedback.md) record the predefined-flow helper failure and the explicit formulation recovery. Original failed native results remain preserved; `runs/gap4/invalid_original_flow` contains the original nonconservative snapshot.

Fine Allsolve projects: [4 mm](https://allsolve.quanscient.com/#/projects/zGDsVITicdtGPhAAbR/model), [6 mm](https://allsolve.quanscient.com/#/projects/K0pjyYL9U2mAYvdVRv/model), [8 mm](https://allsolve.quanscient.com/#/projects/Asw8FbQLHL-sei8Opb/model).

## Reproduce and verify

Cloud scripts use the workspace `.venv` with Allsolve 0.5.2 and the root `.env`. They preserve successful results and reject changes to an existing case's geometry, mesh or grid. Use a new case name for an intentional independent refinement.

```powershell
..\.venv\Scripts\python.exe cloud_study.py run --case gap6fine
..\.venv\Scripts\python.exe cloud_study.py harvest --case gap6fine
```

`run` skips completed jobs. `harvest` refreshes local snapshots without solving; rerun validation afterward because source hashes include state. The cloud API requires network access.

With a NumPy-capable Python, from this folder:

```powershell
python validate_fields.py runs\gap6fine
python analyze_study.py --case gap6fine
python analyze_convergence.py --fine-case gap6fine --coarse-case gap6
python qa_api.py
```

From the workspace root, run `python -m unittest discover -s ExhaustLab\tests -v`: all 13 analytic, export-contract, and provenance-gate tests pass. The API check verifies genuine fine sources, fate accounting, budget filtering, zero-charge behavior and out-of-envelope rejection. Initial browser rendering was checked; later browser automation timed out, while the final API checks passed.

## Physical scope

The model assumes a dilute precharged spherical aerosol, fixed charge, constant gas properties and perfect wall sticking. It omits particle charging/corona, Brownian diffusion, gravity, resuspension, deposition feedback, hot/turbulent exhaust, combustion chemistry and filter regeneration. It predicts conditional particle collection for this pilot. It does not predict measured or certified car/ship/plant emissions, CO₂/NOx reduction or regulatory compliance. See [AGENTS.md](AGENTS.md) for the case requirements and official references.
