# Periodic optical slab benchmark

The 3 October 2026 benchmark passed its fixed acceptance gate using real Allsolve cloud jobs: [`results/report.json`](results/report.json) records `status: completed`, `validated: true`, and `synthetic: false`. The cloud project is [MetaSense optical slab validation](https://allsolve.quanscient.com/#/projects/jgeSELslGe3PYqB2N9/model). This establishes normal-incidence excitation and power readout for this planar dielectric slab. A successful job or passing local test alone is insufficient.

## Assumptions

| Quantity | Value |
| --- | --- |
| Vacuum wavelength | 1000 nm |
| Cell | 500 nm × 500 nm |
| Slab thickness | 166.6666667 nm, a quarter wave at index 1.5 |
| Exterior | Vacuum, index 1, permeability `mu0`, zero conductivity |
| Slab sweep | Index 1 vacuum control; index 1.5 lossless dielectric |
| Excitation | Normal incidence, +z propagation, x polarization, 1 V/m peak |
| Boundaries | Zero-phase x/y periodicity, multiplier order 2; first-order absorbing ends |
| Air clearance | 500 nm on each side |
| Field | Second-order `hcurl`, harmonics 2 and 3 |

Indices are explicit benchmark assumptions, not measured material data. The quarter-wave Fresnel prediction is `R = 0.1479289941`, `T = 0.8520710059`; the vacuum control predicts `R = 0`, `T = 1`. This benchmark contains no pillars, binding layer, molecular model, detector, or biological inference. A later sensor needs a justified assay, optical constants, and calibration.

## Source and power extraction

We define peak phasors by `E(t) = Re[(E_cos - i E_sin) exp(+i omega t)]`. Installed API harmonic **2 is sine; 3 is cosine**. Positive z propagation therefore has spatial phase `exp(-ikz)` and positive `Hy/Ex = Y0`, where `Y0 = sqrt(epsilon0/mu0)` and `Z0 = 1/Y0`.

At the entrance, outward normal is -z. Combining the incident wave with the outgoing impedance boundary gives the boundary residual

```text
Y0 dt(E_t) · test(E_t) - 2 Y0 dt(E_inc) · test(E_t).
```

[`source_readout.py`](source_readout.py) runs at `AFTER_FORMULATIONS_CREATED`, with both generated **FORMULATIONS and SOLVE disabled**. It creates `qs.formulation()`, adds `predefinedemwave` and absorbing boundary admittance at each end, applies `qs.periodicitycondition(..., 1, 2)` on each lateral pair, adds the incident forcing, and solves once at relative residual tolerance `1e-9`. The explicit multiplier order 2 matches the second-order field trace. SDK-generated periodicity used order 0; that earlier study is retained in `state.json` under `default_periodicity_runs`.

For incident `E_inc,x = E0 cos(omega t)`, the forcing is `+2 Y0 E0 omega sn(1) test(Ex)`. Its integral explicitly supplies the FFT argument `3`. This analytic derivative avoids the runtime's unsupported `dt(cn(1))` operation. See [SDK feedback](../../SDK_FEEDBACK.md) for the tested syntax constraints.

Magnetic quadratures follow Faraday's law:

```text
H_cos = harm(2, curl(E), 3)/(mu0 omega)
H_sin = -harm(3, curl(E), 3)/(mu0 omega)
```

`qs.on(adjacent_air_volume, expression)` maps these volume derivatives onto entrance/exit surfaces. Surface evaluation of curl alone can omit normal derivatives. The directional electric amplitudes are

```text
Ex+ = (Ex + Z0 Hy)/2       Ex- = (Ex - Z0 Hy)/2
Ey+ = (Ey - Z0 Hx)/2       Ey- = (Ey + Z0 Hx)/2
P± = (Y0/2) integral_surface(|Ex±|² + |Ey±|²).
```

Every integral uses collective `allintegrate`. Reflection and transmission divide positive directional powers by entrance forward power, never by net entrance flux. Specified incident power is `period² Y0 E0²/2`. The report also checks exit backward power, cross polarization, and Poynting/decomposition consistency. The latter is an algebraic consistency check on the same fields. These formulas apply to normal plane waves in this slab; a diffracting pillar cell requires appropriate mode projection and open-boundary validation.

## Fixed acceptance gate

Both indices must complete successfully on coarse and fine meshes with matching source SHA-256 values and finite required outputs. `harvest.py` fixes these tolerances before examining results:

| Check | Requirement |
| --- | --- |
| Fresnel agreement | Absolute R and T error ≤ 0.01 each |
| Energy balance | `abs(1 - R - T)` ≤ 0.01 |
| Incident normalization | Absolute error from 1 ≤ 0.02 |
| Exit incoming wave | Backward power / incident power ≤ 0.001 |
| Cross polarization | Power / incident power ≤ 0.0001 at each end |
| Mesh convergence | Absolute coarse/fine change ≤ 0.005 for R and T, both indices |
| Reported scalar consistency | Absolute error ≤ 1e-8 |
| Flux/decomposition consistency | Error / incident power ≤ 1e-6 |

Coarse spacing is at most `lambda0/12` in air and `lambda0/(1.5*12)` in the slab; fine uses denominator 18. If the fixed gate fails, diagnose the field/source/mesh and retain the failed result. Passing the slab establishes this limited excitation/readout workflow; the app's `allsolve` sensor mode still needs its own real geometry and validation.

## Saved evidence

The final explicit-periodicity runs share source SHA `113bba747bb1960a7c05ab5cb82d7aafb01cdd59dc939bf2b7f4c959aab4f121`. The report preserves project, mesh, simulation, and job IDs, source hashes, and earlier attempts.

| Case | R | T | `1 - R - T` |
| --- | ---: | ---: | ---: |
| Analytic homogeneous control | 0 | 1 | 0 |
| Fine cloud homogeneous control | 0.0000033025803 | 1.0000162381 | -0.000019540703 |
| Analytic index-1.5 slab | 0.1479289940828403 | 0.8520710059171601 | ≈ 0 |
| Coarse cloud index-1.5 slab | 0.1500097119682781 | 0.8501649940812087 | -0.000174706049 |
| Fine cloud index-1.5 slab | 0.14903033331869026 | 0.8511445897356873 | -0.000174923054 |

Fine slab absolute Fresnel errors are `0.0011013392` for R and `0.0009264162` for T. Slab mesh changes are `0.0009793786` for R and `0.0009795957` for T. Fine slab incident normalization is `1.0044038968`, exit backward fraction `2.6974e-6`, and entrance/exit cross-polarized fractions `4.5076e-7` / `9.3255e-8`. All saved acceptance checks pass. Small energy residuals and control T slightly above 1 reflect numerical error.

| Run | Air maximum mesh size | Slab maximum mesh size | Solve runtime |
| --- | ---: | ---: | --- |
| Coarse, 12 elements per vacuum wavelength | 83.3333 nm | 55.5556 nm | 3 cores, 10 GB fast start |
| Fine, 18 elements per vacuum wavelength | 55.5556 nm | 37.0370 nm | 4 cores, 64 GB |

Both meshes use the 3-core meshing runtime. The fine 10 GB solve failed abruptly during factorization; memory exhaustion is the likely explanation, without an explicit out-of-memory log. The identical solve succeeded on 4 cores / 64 GB. The failed attempt remains in `state.json`.

Final solves have 209,568 coarse and 621,552 fine degrees of freedom. Their logs contain null-pivot warnings (5–6 coarse; 8–14 fine), despite successful solves and passing scalar/field checks. Redundant periodic constraints are a possible explanation, not a confirmed diagnosis. Retain these warnings when extending the formulation.

## Run and recover

From `F:\H4H quanscient\MetaSense`, use the existing Python environment. Credentials are read server-side from the private root `F:\H4H quanscient\.env` and must not appear in results or frontend code.

```powershell
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py setup
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py advance
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py harvest
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py refine
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py advance
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py harvest
```

`setup` reuses saved state, creates the coarse configuration once, and starts its mesh. `advance` starts an unstarted simulation only after its mesh succeeds; later calls inspect progress. `harvest` also calls `advance`, then retrieves successful scalar sweeps, CSV exports, and writes the report. `refine` creates the separate fine mesh/run with its larger solve runtime. Run `advance` or `harvest` again after a mesh/job finishes. Each job has a ten-minute limit; capacity is checked before launch. The runner preserves completed jobs.

For a new independent study, use a separate folder under `simulations` containing `runner.py`, `source_readout.py`, `fresnel.py`, and `harvest.py`, without copying state or SDK cache. Retaining this directory depth preserves root `.env` resolution.

After diagnosing a failed simulation and changing `source_readout.py`, run:

```powershell
.\.venv\Scripts\python.exe .\simulations\slab_validation\runner.py repair
```

`repair` retains the old attempt, requires a changed source hash, creates a revision on the existing successful mesh, and advances it. `larger` retains an errored attempt and retries on 4 cores / 64 GB. `periodic` preserves the earlier completed order-0 study and creates order-2 revisions; it does nothing once order 2 is recorded. `archive-default` retrieves that earlier study into `results/default_periodicity` without changing the active report or launching jobs. `sync` uploads an edited script only to unstarted simulations; it refuses any started job. `inspect` refreshes generated scripts and prints saved state. `logs` saves sweep child-job logs. `fields` saves E sine/cosine fields under each simulation ID and records their paths in state, preserving earlier fields. Keep `state.json` because it connects local evidence with project, mesh, simulation, and job IDs. `results/report.json` can lag changes until the next harvest.

Local checks verify Fresnel math, signs/units, normalization, and strict result gating with explicitly synthetic fixtures:

```powershell
.\.venv\Scripts\python.exe -m pytest .\simulations\slab_validation -q --basetemp .\.runtime\slab-tests
```

They do not execute or validate the cloud solver. Raw public sweep JSON and CSV live in `results/coarse` and `results/fine`. The report separates cloud values, analytic values, checks, and provenance; generated scripts, logs, and field files remain separate evidence.
