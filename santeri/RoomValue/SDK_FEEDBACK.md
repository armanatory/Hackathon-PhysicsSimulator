# Allsolve SDK notes from the RoomValue experiment

These observations come from the actual 6 Ã— 4 m, 250 Hz cafeteria proxy in `experiments/`. They are concrete usability feedback for the Quanscient challenge, not claims that the SDK lacks all possible alternatives.

| Observed friction | Evidence in this experiment | Suggested improvement |
| --- | --- | --- |
| Rectangle placement is easy to misread | An imported 6 Ã— 4 m rectangle positioned at `(0, 0)` initially meshed over `x = -3â€¦3`, `y = -2â€¦2`. The intended room was `x = 0â€¦6`, `y = 0â€¦4`; adding `alignment: "corner"` corrected the mesh bounds. | Make alignment explicit in project import examples and return geometry bounds before meshing. |
| New jobs are awkward to start reliably | `is_running()` treated a `NOT_STARTED` simulation as running in our workflow, so a `while is_running()` check skipped `start()`. We had to branch on `get_status() == NOT_STARTED`. | Provide `start_and_wait()` or make `is_running()` reflect only queued/running states. |
| Region and receiver mistakes appear late | A source curve outside the acoustic physics target passed project setup but failed at simulation script generation. A receiver `interpolate()` outside its target region also failed only during the cloud solve. | Preflight physics-target containment and probe coordinates against geometry before accepting or starting a job. |
| Receiver pressure takes expression knowledge | We used two `ValueOutput` expressions, `interpolate(..., getharmonic(2,p), [x,y,0])` and harmonic component `3`, then combined them with `hypot`. | Add a documented acoustic point probe that directly returns complex pressure, magnitude, phase, and transient time series. |
| Product absorption is hard to represent | The documented acoustic damping acts in a region; the documented absorbing boundary is an open-domain termination with no material input. Our 20 cm strips therefore use an illustrative loss parameter and cannot be mapped directly from a panel's advertised NRC. | Add a frequency-dependent wall impedance or absorption boundary with clearly stated units and example material calibration. |
| Comparing placements requires careful state control | The damping interaction's enabled flag and target region are changed between simulations in one project; the comparison code retrieves each completed job by its simulation ID to keep provenance clear. | Add simulation-scoped parameter overrides or immutable model snapshots, and expose their effective settings with each job result. |

The original 2D results established that the SDK can build, mesh, solve, and probe a small harmonic acoustic model. The 3D follow-on below now includes finite ceiling treatment. Simulated room impulse responses and calibrated commercial product optimization remain pending.

## New 3D dEchorate experiment

The separate [3D study](experiments/room3d/README.md) now exercises a real volumetric room and finite ceiling/wall loss regions. Its cloud provenance and numerical checks are in `experiments/room3d/VERIFIED_3D.json`. It remains harmonic, and the material loss is illustrative.

| Observation | Evidence | SDK feedback |
| --- | --- | --- |
| Named physics sets support independent alternatives | Baseline, east wall, ceiling and source-off sets share geometry and mesh without toggling a shared damping interaction. | Include this pattern in room-acoustics comparison examples. |
| A mesh size setting is not a measured maximum tetrahedral edge | A 0.32 m coarse mesh setting produced a largest edge of 0.53050 m; a 0.24 m setting produced 0.40222 m. We downloaded the mesh to check actual wavelength resolution, 3D bounds and volume. | Expose maximum edge length and elements per wavelength alongside mesh metrics. |
| The larger damped harmonic solve failed without a useful reason | The 446,542-DOF wall solve stopped during the direct matrix solve on the 3 core / 10 GB runtime. Status was ERROR, `get_status_reason()` returned None, and no solver error appeared after the matrix-solve log. A separate job with the same physics and mesh succeeded on 4 core / 64 GB. | Surface memory/termination diagnostics and estimated solver memory. Memory exhaustion is plausible here, but the API did not confirm the cause. |
| Field export requires format-aware scientific handling | `save_output_field()` returned VTKHDF with 10-node Lagrange tetrahedra (VTK type 71). Quadratic interpolation of this field reproduced the independently exported receiver pressure. | Document VTKHDF layout, element ordering and a Python scalar-field sampling example. |
| Rigid-room resonance makes convergence checks consequential | At 125 Hz, the 0.32-to-0.24 m refinement changed one baseline receiver by 0.680 dB, triggering a third resolution level. | Add acoustic mesh-convergence examples and encourage recording the modeled frequency and boundary assumptions. |

## Website placement optimizer

The website's separate project `wplkBNw5wTUbgLDuPI` uses nine source volumes and six treatment volumes, with one independent physics set and job per source/layout. This supports reusable complex fields rather than approximating multiple objects by adding single-object dB changes.

- `Client(cache_base_dir=...)` requires an existing directory. A case-specific cache isolates these jobs from teammate projects.
- Exported VTKHDF `PointData` uses the requested output name: outputs named `Real` and `Imag` yield those scalar keys. It is not consistently `Pressure`; field readers must inspect the actual key.
- Source/layout field caches must verify identical geometry and quadratic edge ordering, and reproduce an independently requested `ValueOutput` probe before accepting results.
- Physics-set creation spans several server mutations. A restart can leave a named but incomplete set; verify the wave, interpolation order, source and every damping interaction before reusing it.

The current website objective is minimum normalized SPL at one listening point subject to a panel-count limit, without a budget. All layout counts must be evaluated: with two allowed ceiling panels, the actual minimum at mic1 used only `ceiling_b`, although the two-panel combination was also solved. Finite damping can redistribute resonant pressure; adding objects does not guarantee a lower level at a particular receiver.

Editing source XYZ requires new geometry and mesh, not merely a changed point label. The live test at source 1 X +0.2 m created project `IAeg6z_rpMEQNfnDNg`, validated its mesh volume/bounds, and checked downloaded field interpolation against the cloud probe in simulation `jhulmZfEM45jP_YPlk`. Its cached field then served a different listener and source level; a 10 dB source-level decrease produced exactly a 10 dB listener decrease. Source coordinates belong in the model/cache signature, while levels and probe coordinates do not. The SDK's harmonic `sn(1)` basis is peak pressure; normalized source SPL must convert RMS to peak using sqrt(2).

## Parallel source/layout execution

- `Simulation.start()` returns without waiting for a solve. Calling `is_running(refresh_delay_s=3)` to completion after every start serialized an otherwise independent parameter search.
- SDK 0.5.2 `Job.refresh_statuses(jobs, delay_s=0)` batch-polls tracked jobs by project instead of imposing a per-job three-second polling delay. `Simulation._get_job()` is the version-specific adapter to that tracked Job; keep it covered by scheduler tests when upgrading.
- Quota exposes `max_concurrent_cores`, `total_running_cores` and `total_reserved_cores`. The scheduler accounts conservatively for both reported use and locally in-flight four-core jobs, because shared quota can change or lag during submission. Quota-related submission failures back off; authentication, credits and physics errors remain visible failures.
- Keep immutable physics/simulation definitions, serial SDK mutations, one state-file coordinator and independent field/probe checks. Parallelism happens in Allsolve's cloud. Actual batch-polled RUNNING observations and cloud IDs are retained separately from queued/in-flight counts.
