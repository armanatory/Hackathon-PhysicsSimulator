# Allsolve SDK feedback: optical slab spike

Recorded 2026-10-03 using Allsolve SDK 0.5.2 and cloud solver 484 in [project jgeSELslGe3PYqB2N9](https://allsolve.quanscient.com/#/projects/jgeSELslGe3PYqB2N9/model). This is a periodic lossless slab at 1000 nm, with a vacuum control, before any sensor model. The acceptance outcome is the latest `simulations/slab_validation/results/report.json` `validated` flag; the existence of a project, mesh, or running revision does not establish success.

The [official EM documentation](https://allsolve.quanscient.com/documentation/using-allsolve/physics/em-waves) supplies the weak formulation, periodicity, and absorbing interactions. A rectangular port explicitly assumes four PEC edges, so it is inappropriate to assume it excites an ordinary periodic optical cell. The slab therefore adds an incident-wave forcing to the built-in impedance boundary through the [SDK custom-script hook](https://allsolve.quanscient.com/documentation/reference/allsolve-sdk).

## Observed runtime constraints

| Observation | Working formulation / implication | Suggested improvement |
| --- | --- | --- |
| `dt(cn(1))` raises an operation-copy error. | Use the exact analytic derivative `dt(cos(omega t)) = -omega sin(omega t)`. The residual source is consequently `+2 Y0 E0 omega sn(1) test(Ex)`. | Support derivatives of analytic harmonic sources, or validate their restriction before a paid run. |
| That analytic forcing still fails without explicit FFT handling, producing an `optime` FFT error. | Use `qs.integral(reg.entrance, 3, forcing_expression)`. | Automatically recognize `sn/cn` harmonics, or provide a clear example explaining when the integral FFT argument is required. |
| `dt(curl(E))` is rejected: time derivatives are allowed only on ports, fields, dofs, and test functions. | Extract quadratures directly: `Hcos = harm(2,curl(E),3)/(mu0*omega)`, `Hsin = -harm(3,curl(E),3)/(mu0*omega)`. Map volume derivatives to monitor surfaces using `qs.on`. | Document a supported EM magnetic-field and power readout recipe; ideally expose H as a derived field. |
| Referenced harmonic skill guidance reverses sine/cosine indices. | Installed API and its Fourier expansion define **2 = sine, 3 = cosine**. This project explicitly uses `E_cos - i E_sin` with `exp(+i omega t)`. | Correct the conflicting guidance and distinguish harmonic indices from a chosen complex phasor convention. |
| `get_generated_scripts` returns the base main script without custom hooks or the commented disabled solve. | Persisted `get_scripts()` and fresh `disabled_script_sections` confirm configuration; child runtime tracebacks confirm the hook actually executes. The returned base main is not proof of the final executable composition. | Expose the fully composed runtime script, including imports, disabled sections, custom hooks, and sweep overrides. |
| Sweep-parent logs omit the failed child's traceback. | Retrieve `simulation.get_output_data()._get_simulations_sorted()`, find the child row's `job_id`, and fetch that `Job`'s logs. This currently depends on private SDK access. | Add a public child-job/log API or include a concise linked child traceback in parent logs. |

The revised scripts retain old failed simulations and source hashes instead of overwriting evidence. The first three attempts exposed the source derivative, explicit FFT, and magnetic derivative restrictions. Their failures do not establish that the physical boundary formulation is wrong.

## Measured periodic-boundary discrepancy

The generated ordinary-periodicity call omits `lagmultorder`, whose installed API default is zero, even though this benchmark uses an order-two hcurl E field. Original coarse simulation `ZZGQpwIZW3aZVkHAFE` produced vacuum R = 0.00924974, T = 0.982542 and slab R = 0.119757, T = 0.873669. Refinement with that default still failed the fixed gate. These values are retained separately from the repaired results.

The offline [field audit](simulations/slab_validation/audit_fields.py) and [recorded measurements](simulations/slab_validation/results/default_periodicity_audit.json) compare corresponding samples on geometrically matched tetrahedral facets. Both material interfaces match all 230 facets on each side, with tangential E jumps at roundoff (maximum 2.53e-14 V/m across the two sweeps). Measured geometry spans are `(5e-7, 5e-7, 1.166666666666667e-6)` m, with interfaces at z = 0 and `1.6666666666666665e-7` m. This excludes a misplaced interface or nonconforming internal tangential trace as the observed explanation.

The lateral traces are different. Of 360 facets per opposite face, 311 x-face pairs and 229 y-face pairs match geometrically after translation by `5e-7` m. For the 1 V/m vacuum excitation, sampled tangential jump RMS on x faces is Ey = 1.755 and Ez = 4.157 V/m (maxima 5.643 and 8.541); on y faces it is Ex = 0.2122 and Ez = 0.2455 V/m (maxima 0.8104 and 0.8446). The slab has similarly large violations. Unmatched facets remain unassessed; these are sampled diagnostic norms, not a continuous trace norm. Normal-component jumps are not tests of hcurl conformity.

Projecting the saved surface-average Ex/Hy onto the coherent zeroth mode gives vacuum R = 0.000765743, T = 0.976187 and slab R = 0.112542, T = 0.868881. The transmission phase error is +0.3427 rad in vacuum and +0.3681 rad in the slab. Thus changing power projection alone does not explain the discrepancy. Integrated local plane-wave splitting includes spatial variance and transverse channels; its separate forward/backward terms are not valid propagating-mode powers for arbitrary evanescent transverse fields.

An explicit `lagmultorder=2` comparison on the same coarse and fine meshes then passed the unchanged gate (`report.json` has `validated=true`). Fine simulation `ZIcIMoFe_imveYQxwx` gives slab R = 0.1490303333, T = 0.8511445897, energy residual = -0.0001749231, and vacuum R = 3.30258e-6, T = 1.000016238. The composed source hash is `113bba747bb1960a7c05ab5cb82d7aafb01cdd59dc939bf2b7f4c959aab4f121`; coarse comparison is `Yfo6lrDoKUV19EaRjT`.

The [explicit-order field audit](simulations/slab_validation/results/periodic_order2_audit.json) uses the same matched facets and directly measures the recovered periodic trace. Vacuum tangential jump RMS changes as follows; all values are V/m:

| Periodic face / tangential component | Default order zero | Explicit order two |
| --- | ---: | ---: |
| x / Ey | 1.75502 | 3.76376e-5 |
| x / Ez | 4.15669 | 2.90446e-5 |
| y / Ex | 0.212187 | 2.03227e-5 |
| y / Ez | 0.245529 | 1.86993e-5 |

For the slab, the explicit-order tangential RMS values are x/Ey = 5.09098e-5, x/Ez = 5.55913e-5, y/Ex = 7.10285e-5, y/Ez = 3.81265e-5 V/m. The largest sampled tangential jump is 9.634e-4 V/m in vacuum and 1.677e-3 V/m in the slab. Internal tangential continuity remains at roundoff. Coarse transmission phase errors fall to +0.0008783 rad in vacuum and +0.0007329 rad in the slab; local-versus-coherent power excesses fall to approximately 1e-6–2e-6 of specified incident power.

Together, the controlled numerical and field comparisons identify periodic trace enforcement as the source of the original discrepancy. The more specific explanation that multiplier order zero underconstrains higher-order trace modes remains an inference; the SDK's internal constraint matrix was not inspected. The benchmark gate is unchanged, and these measurements establish the slab result only.

`audit_fields.py` uses workspace-root h5py/numpy and performs no SDK or cloud calls. Its `--run-folder` selects the folder containing `fields/sweep_*`; `--scalar-root` optionally selects separately archived raw scalars. Each raw scalar simulation ID must match `--simulation-id`. `--periodic-order` records the tested configuration and `--output` selects a separate audit artifact. This keeps original fields/scalars distinct from repaired evidence.

The SDK should expose the multiplier order in generated periodic settings, document its relationship to hcurl field order, and provide an example that checks translated tangential traces along with mesh convergence. An order-zero multiplier default should not be assumed to deliver pointwise equality of an arbitrary higher-order trace.

Final order-two solve logs report 209,568 coarse and 621,552 fine degrees of freedom and null-pivot warnings (5–6 coarse, 8–14 fine). Jobs succeeded and the unchanged scalar gates plus field audits passed. Redundant periodic constraints are a possible explanation for the warnings, but no constraint-matrix diagnosis was performed. Better diagnostics should identify the affected multiplier/field blocks. The initial fine 10 GB attempt failed during factorization without an explicit out-of-memory message; the same source and mesh succeeded on 4 cores / 64 GB.

## Additional gaps to resolve before a metasurface sensor

- Provide a documented polarized plane-wave source for periodic cells, including normal direction, amplitude, phase, and open-boundary behavior. An impedance source is straightforward for the slab but should not require discovering low-level harmonic restrictions through cloud failures.
- Provide normalized reflection/transmission and diffraction-order power extraction. `modedrive` constrains boundary E to supplied modes; an analytic constant mode might serve a uniform slab, but omitted diffraction modes must not be silently eliminated in a pillar cell.
- Document Bloch phase support for oblique incidence. Ordinary translation periodicity is sufficient only for this normal-incidence benchmark.
- Add semantic script checks for supported derivative expressions and expression arithmetic. The installed expression stub does not advertise `__pow__`; this source uses multiplication to square expressions.
- Clarify local versus collective integration. Monitor power must use `allintegrate` under MPI, because `setoutputvalue` writes only rank zero.

Source sign follows the documented weak term `-(n × dt(H)) · test(E)`: for entrance outward normal -z, `n × H = Y0(2 Einc - Et)`. Readout separates positive forward/backward power before normalization and checks both polarizations. Poynting agreement with this decomposition is a consistency identity; Fresnel agreement and mesh convergence are the physical checks.

The exact setup, formulas, fixed tolerances, recovery commands, and limits are in [the slab README](simulations/slab_validation/README.md). No optical constants are inferred from molecular coordinates, and no slab result is evidence of protein detection, assay performance, or clinical utility.
