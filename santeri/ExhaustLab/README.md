# ExhaustLab

A working local web app for **constraint-driven exhaust installation planning** for a small stationary diesel engine. Enter an operating cycle and limits for backpressure, space, cost, specified particle capture and thermal response. The planner searches a finite installation grid, selects the best feasible design for the chosen objective, and shows tradeoffs. When no candidate fits, it explains the violated constraints without inventing a winner.

Open [the planner](http://127.0.0.1:5176/). API: <http://127.0.0.1:8003/>.

## Start the app

From this folder:

```powershell
$exhaustPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $exhaustPython server.py
```

Alternatively run `start.ps1`; it finds the bundled runtime and detects an already-running app. The server requires NumPy and Python's standard library. It reads archived cloud results; using the app does not submit cloud jobs or load API credentials.

## Using the planner

1. Edit the ordered duty cycle: duration, exhaust mass flow and temperature at the start of the upstream pipe.
2. Set installation limits and choose lowest entered cost, smallest package volume or lowest backpressure.
3. Expand **Filter & model inputs** to enter cartridge specifications, resistance and thermal calibration, costs, ambient conditions and candidate dimensions.
4. Select **Find a feasible design**. Inspect the recommendation, constraint checks, operating-point results and Pareto alternatives. Selecting an alternative updates the detailed view.

The default grid is 120/160/200 mm filter diameter × 150/200/250 mm active length × 100/300/600 mm upstream pipe × 0/10/20 mm insulation: **81 installations**. Pipe bore is editable and defaults to 80 mm. In Allsolve-backed mode, cartridge diameter/length pairs require an exact verified cloud case. Unsupported dimensions are rejected with an explanation. The optimum is within this finite grid and under the supplied assumptions.

## Default inputs and example result

The engine reference is the [FG Wilson P22-1 supplier datasheet](https://www.fgwilson.jo/images/document/19867560/P22-1L_SKID_EN-XUZENrzO_pyIozFA7Ecs6g.pdf): 16 kW prime electrical output, 445 °C prime exhaust temperature, 3.6 m³/min exhaust flow and 10.2 kPa maximum exhaust backpressure. The app's rated mass flow of 0.030 kg/s is a rounded inference treating that volume as hot actual flow with ideal dry-air density at 445 °C and 101.325 kPa; it is not a published mass-flow measurement. Other duty points and every duration are illustrative.

Cartridge permeability, capture specification, loaded resistance multiplier, thermal properties, minimum cartridge volume and cost coefficients are **editable demonstration inputs**, not a measured supplier dataset or price quotation. The engine backpressure allowance applies to the full exhaust system; reduce the installation allowance to account for equipment outside this model.

With these defaults, 62 of 81 candidates pass. The lowest-cost candidate is a **120 mm diameter × 200 mm filter core**, with 100 mm upstream pipe and no insulation. It has 5.47 kPa worst loaded backpressure and a 120 × 300 mm modeled envelope. Its €353 entered cost follows the illustrative cost coefficients. Tightening the pressure limit to 3 kPa selects a 160 × 150 mm core at 2.34 kPa. Requiring capture above the entered filter specification produces no feasible design.

[Saved example API results](runs/planner_examples.json) preserve the defaults, the 3 kPa pressure case and the infeasible 99% capture requirement, including all candidate decisions and provenance.

## What is simulated

| Component | Calculation and evidence |
|---|---|
| Equivalent porous cartridge | Nine genuine 3D Allsolve homogeneous Darcy/steady thermal solves, with exported fields, project/job IDs and hashed validation sources. The planner uses each exact geometry's pressure normalization with the linear Darcy scaling law. |
| Upstream pipe and housing | Local pipe friction and entered housing-loss correlation; cylindrical pipe heat loss. |
| Ordered thermal history | Local uniform filter-temperature model with exact constant-step heating/cooling and threshold crossing times. |
| Clean/loaded comparison | Entered cartridge resistance multiplier; no evolving soot or ash inventory. |
| Particle capture | An entered filter specification compared with the required capture. Capture is not inferred from pressure or temperature. |
| Costs and optimization | Entered cost coefficients and exact enumeration of the finite candidate grid; feasible Pareto tradeoffs. |

This is an **equivalent homogeneous axial cartridge installation screen**. A conventional wall-flow DPF has plugged channels and flow through porous walls; sizing it requires a calibrated wall-flow resistance model and cartridge data. Time above a temperature threshold is a heat-retention metric. It does not predict soot oxidation, regeneration completion, reaction hot spots, catalyst conversion, emissions certification or spatial temperature gradients. The separate steady Allsolve thermal benchmark is shown as evidence and is not multiplied into the local transient calculation.

See [the model and assumptions](PLANNER_MODEL.md) for equations, input envelopes and the data needed for a real cartridge installation.

## Allsolve validation and parallel work

All nine cartridge geometries pass analytical pressure, velocity/flux, volume and steady thermal checks. Maximum pressure error is 0.122%; maximum velocity-profile relative L2 error is 0.147%; prescribed finite-element inlet/outlet flux mismatch is at most 0.104%. The central 160 × 200 mm case also passes independent 10 → 7 mm mesh refinement: pressure changes by 0.0271% and outlet temperature by 0.234 K. These checks establish numerical consistency of the stated equations, not physical calibration of a commercial DPF.

The batch dispatched up to **three independent cloud jobs concurrently**. Each solve used one rank. This demonstrates parallel design evaluation; no distributed-solver scaling or runtime speedup was measured. The app's local installation search combines the nine verified cores into 81 alternatives without new cloud jobs.

- [Cloud manifest](runs/dpf_cloud_manifest.json): dimensions, IDs, normalization factors, physical gates and source hashes.
- [Batch overlap evidence](runs/dpf_parallel_batch.json) and [mesh refinement evidence](runs/dpf_mesh_comparison.json).
- [Cloud model, validation and SDK findings](research_dpf_cloud.md): weak forms, stabilization, sampling correction and preserved failed refinement.
- Each `runs/dpf_d*_l*` folder preserves input state, generated solver scripts, sampled fields, solver logs and validation.

If source validation fails or the archive is absent, the API explicitly labels the result **analytic screening** and exposes the reason. It does not claim Allsolve support for that fallback.

## Verify and reproduce

Run the unit suite from the workspace root, using a NumPy-capable Python:

```powershell
python -m unittest discover -s ExhaustLab\tests -v
```

With the server running, from this folder:

```powershell
python qa_planner_api.py --require-cloud
python qa_api.py
node --check frontend\app.js
```

The planner checks include gas-property coupling, pressure and thermal scaling, exact threshold crossings, loaded resistance, objective selection, pressure-driven sizing, infeasibility, input validation and cloud provenance replacement. API checks cover the default result, tighter requirements, invalid inputs and unsupported cloud geometry. `qa_api.py` also checks the preserved electrostatic pilot routes.

Final verification on 2026-10-03: all 30 unit tests passed (17 planner and 13 previous-pilot checks), both live API checks passed, and Python compilation and JavaScript syntax checks passed. Browser verification confirmed the default result, visible filter schematic and the switch to a 160 × 150 mm core when the backpressure limit was lowered to 3 kPa. A subsequent capture-infeasibility UI check was interrupted when the browser surface became unavailable; the same behavior passed the API checks.

Cloud reproduction uses the workspace `.venv` with Allsolve SDK 0.5.2 and credentials from the root `.env`. Read [the cloud run notes](research_dpf_cloud.md) and `dpf_cloud.py --help` before submitting a new bounded study. Keep credentials server-side and never embed them in the frontend.

## Previous pilot

The original low-flow electrostatic collector is preserved at [the benchmark app](http://127.0.0.1:5176/electrostatic/). Its results, trajectories, convergence evidence and scope are documented in [ELECTROSTATIC_PILOT.md](ELECTROSTATIC_PILOT.md).
