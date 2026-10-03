# Local particle trajectory model

`particles.py` is local postprocessing. It consumes independently obtained velocity and electric fields, never creates an Allsolve result, and never submits a cloud job. The fields in `tests/test_particles.py` are analytic validation fixtures only. No capture result from those fixtures is a device prediction.

## Narrow pilot envelope

The first model is a convex, unobstructed rectangular gap: axial length `x = 0..0.060 m`, plate separation `y = 0..H`, and plate span `z = 0..0.020 m`. Compare `H = 0.004, 0.006, 0.008 m`. The specified flow is **0.2 L/min per modeled gap**, equivalent to `3.333333e-6 m³/s`; it is not the total flow through a multi-gap assembly. Gas properties are entered pilot assumptions at room temperature: density `1.2 kg/m³`, dynamic viscosity `1.81e-5 Pa·s`, mean free path `65 nm`. They must be revised for hot exhaust or different pressure/composition.

Particles are precharged, dilute, spherical, monodisperse `1 µm` diameter with nominal charge `+30e` and an entered charge sensitivity. The nominal plate potential difference is `200 V`. Neither particle charge nor charging efficiency is solved by this model. A fixed input charge does not describe the charge distribution of untreated soot.

## Motion and force assumptions

The overdamped equation is

`dx_p/dt = u(x_p) + [q Cc / (3 π μ d_p)] E(x_p)`.

`q = charge_e × 1.602176634e-19 C` and

`Cc = 1 + (2 λ / d_p) [1.257 + 0.4 exp(-1.1 d_p / (2 λ))]`.

The slip-adjusted mobility follows an electric-force/Stokes-drag balance described by [NISTIR 6935, equations 1–3](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=861193). The Davies Cunningham expression is reproduced in [the primary AerSett model paper, equation 22](https://gmd.copernicus.org/articles/16/1119/2023/index.html). For the entered `1 µm`, `65 nm`, `+30e` inputs, `Cc = 1.163421` and signed electrical mobility is `3.278075e-8 m²/(V·s)`. These are calculations from entered constants.

Particle inertia is removed rather than numerically integrated. The corresponding relaxation time is `τp = ρp d_p² Cc/(18 μ)`; at an illustrative spherical material density of `1000 kg/m³`, it is `3.57 µs`. This is an assumption check, not a measured soot density. Stokes drag additionally requires slip Reynolds number `ρgas d_p |v_p-u|/μ << 1`; `ParticleModel.slip_reynolds_number()` exposes this diagnostic. Check the largest simulated electric fields when expanding the operating envelope.

Initial trajectories omit Brownian diffusion, gravity, thermophoresis, lift, near-wall drag corrections, particle interactions, space-charge feedback, dielectric polarization, corona, collisions, charging/discharging, and resuspension. No conclusion of negligible gravity or diffusion is inferred from that omission. Very low charge, much smaller particles, long residence times, and hot gradients need additional terms or sensitivity studies. A static electrostatic field gives no electrical power consumption by itself; voltage alone cannot determine corona/current or operating power.

## Export contract and interpolation

The primary interface is `RegularGridFieldSampler(x_m, y_m, z_m, velocity_m_s, electric_v_m, provenance=...)`. It uses only NumPy. Each strictly increasing axis includes both physical endpoints. Vector arrays have shape `(nx, ny, nz, 3)` with component order `(x, y, z)`. Coordinates are meters, velocity is m/s, and electric field is V/m. The sign of `E` must follow `E = -grad(V)`.

The export adapter must establish coordinate ordering, domain ownership, units, field component names, and the association of velocity and electrostatics with the same geometry before constructing the sampler. Archive source project/run identifiers, model parameters, mesh and solve status, export axes, SDK version, and field validation checks in provenance/sidecar metadata. Do not infer units from magnitudes or replace failed field samples with zero. Actual Allsolve field exports and metadata must remain distinct from analytic validation arrays.

Interpolation is trilinear on the supplied cells. Query points outside any supplied axis are uncovered and return NaN. Inset export endpoints do not provide full physical boundary coverage; the trajectory code will report unresolved wall/outlet events rather than silently extending the fields. All grid values must be finite. For arbitrary scattered samples, optional `ScatteredFieldSampler` uses SciPy tetrahedral linear interpolation without extrapolation. Its convex-hull domain cannot represent baffles, holes, or disconnected fluid regions; those require original fluid mesh connectivity and a different geometry/event representation.

## Inlet flux, contact, and accounting

`flux_weighted_inlet()` places deterministic seed centers on a uniform grid of inlet cells. A uniform aerosol concentration in the carrier gas is assumed. Each seed weight is `max(ux,0) × Δy × Δz`. Thus fractions describe carrier-volume-weighted single-pass outcomes and do not treat a slowly moving wall-region seed as equal to a fast central seed. Reverse inlet carrier flow is rejected. An axial electric slip comparable to `ux` would require revising number-flux weighting; the baseline plate field is transverse.

All four lateral walls are ideal absorbing surfaces. A seed center reaching `y=0`, `y=H`, `z=0`, or `z=W` is classified captured with perfect sticking and no bounce/resuspension. This point-center rule neglects the `d_p/2` finite-radius contact offset. The result separately records plate-wall and span-wall hits so that sidewall loss can be distinguished from collection on a designated electrode. An exact corner tie gives wall contact precedence over outlet exit.

Reaching `x=L` without an earlier wall event is an outlet. Returning through `x=0`, leaving field coverage, or exceeding the entered integration-time limit is unresolved. An event also requires interpolation coverage at its physical terminal plane. Fractions always use **all inlet weight**: `captured + outlet + unresolved = 1`. Unresolved trajectories are never silently reclassified as outlets or excluded from the denominator. The conservative reported capture interval is `[captured_fraction, captured_fraction + unresolved_fraction]`; that interval represents unresolved numerical outcomes, not every physical model uncertainty. Computational seed counts are also returned for diagnostics; percentages must use weights.

## Integration and convergence

The code uses explicit midpoint time integration with first-plane segment intersection. If its first half-step reaches a terminal plane, a local linear event records that contact; otherwise the midpoint velocity gives the full step. Consequently terminal event accuracy must be checked by timestep refinement. Missing sampler coverage is a reason-coded unresolved outcome.

`timestep_convergence()` runs the same field and inlet grid at `dt`, `dt/2`, and `dt/4`, returning capture/outlet changes, weighted changes in classification, and terminal-time changes for equally classified resolved seeds. It reports evidence, not an automatic claim of convergence. A practical initial capture tolerance can be one percentage point between the final refinements, but it must be entered and reported along with unresolved weight and time-limit sensitivity. Independently refine the inlet quadrature (for example `24×16`, `48×32`, `96×64`), the exported field grid, and the Allsolve mesh. Timestep agreement alone does not establish field, inlet, or physical accuracy.

The analytic tests cover exact uniform drift/contact times, zero-charge outlet transport, charge sign, affine trilinear interpolation/no extrapolation, inlet flux weighting, explicit unresolved coverage/time outcomes, and decreasing terminal-time error for the exact nonuniform drift `dy/dt = a y`. Run them from the project root with `python -m unittest discover -s ExhaustLab/tests -v`.

Only after the field path and these convergence checks are verified may results be described as modeled, diameter- and charge-conditional single-pass capture for this room-temperature pilot. They are not measured or certified emission reduction for a car, ship, or power plant, and they do not predict CO₂ or NOx removal.

## Harvested-study adapter

`analyze_study.py --case gap6` processes `runs/gap6/state.json`, `flow_samples.json`, and `electric_samples.json` without importing the Allsolve SDK or making network requests. It requires recorded successful mesh, flow, and electrostatic jobs with identifiers **and a passing `validation.json` benchmark for those exact source snapshots**. Solver job success alone does not establish physical validity. Validation identifiers and SHA-256 hashes must match the loaded state/fields, and every flow/electric check must pass. It also checks finite output lengths, exactly matching coordinate samples, regular tensor ordering, full boundary coverage, and both integrated gas-volume outputs against the declared geometry. Failed benchmarks, incomplete jobs, or ambiguous field registration stop processing before integration or any particle artifact write. The adapter checks that source and validation files have not changed during integration before saving a result.

The cloud export loop is `for x ... for y ... for z ...`; therefore `z` varies fastest. Flat `sample_xyz_m` and `sample_vector` arrays contain `3 × nx × ny × nz` entries. Reshape into `(nx, ny, nz, 3)` only after verifying tensor coordinates. Flow `sample_vector` contains velocity; electrostatic `sample_vector` contains `-grad(potential)`. `sample_scalar` has exactly one scalar per sample: pressure for flow and potential for electrostatics. Both scalar arrays reshape into `(nx, ny, nz)`. `gas_volume_m3` is a one-value integrated output array. No absent sample is inferred or filled.

Area-averaged pressure at `x=0` minus that at `x=L` defines the reported static pressure drop. Trapezoidal integration of the exported face grid provides the area integrals and carrier-flow diagnostics. The adapter also compares potential and electric field with the expected linear/uniform plate solution and pressure with the independent entered channel reference. These are analytic checks against actual field outputs; reference values never replace the exported fields.

The output `particles.json` includes source identifiers, SHA-256 hashes of all three input snapshots, model assumptions, the nominal result, 24 evenly indexed illustrative inlet traces, timestep levels `0.02/0.01/0.005 s`, inlet grids `24×16/48×32/96×64`, and the full Cartesian sensitivity set of diameters `0.5/1/2 µm` with charges `0/15/30/60e`. Nominal and sensitivity runs use `48×32`, `0.01 s`, and a `30 s` integration time limit. `particle_sensitivities.csv` is a concise comparison table. A one-percentage-point capture change threshold is explicitly recorded for timestep/inlet refinement; mesh and exported-grid convergence remain separately unverified until additional actual solves/exports establish them.

`analyze_convergence.py --fine-case gap6fine --coarse-case gap6` writes a separate `runs/gap6fine/convergence_report.json` without modifying source snapshots or previous particle artifacts. It independently validates the exact source benchmark/hashes. The first comparison takes every second node of the actual refined export (`49×33×17` to `25×17×9`) and compares the two interpolants from the same finite-element solution. The second comparison uses the coarse-mesh export and the refined-mesh downsample at exactly identical export coordinates. This separates exported-grid interpolation effects from finite-element mesh effects. Both comparisons fix the inlet grid at `96×64`, timestep at `0.005 s`, charge at `+30e`, diameter at `1 µm`, and time limit at `30 s`. The report contains absolute capture changes, inlet-flux changes, and pressure differences. Agreement describes the tested refinements; it does not prove physical model accuracy across other particle sizes or operating conditions.
