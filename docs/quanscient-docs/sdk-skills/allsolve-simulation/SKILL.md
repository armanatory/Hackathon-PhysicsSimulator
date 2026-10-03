---
name: allsolve-simulation
description: >-
  Create and run Allsolve simulations: simulation types, run pattern, error
  handling, outputs, job statuses, instance sizing, resource reservations. Use
  when creating create_simulation_static, create_simulation_transient, on_error,
  OnError, Output, FieldOutput, ValueOutput, get_output_data, JobError,
  get_status, sim.run, resource_reservation, ResourceReservation, physics_set,
  or simulation node type / Runtime.
disable-model-invocation: true
---

# Allsolve simulation

## Simulation types

All helpers are on `project`. Each maps to an `AnalysisType`.

| Method | Analysis type | Typical use |
| ------ | ------------- | ----------- |
| `create_simulation_static` | Steady-state | Equilibrium solutions (thermal, structural, EM, …) |
| `create_simulation_harmonic` | Harmonic | Single-frequency AC / frequency-domain |
| `create_simulation_multiharmonic` | Multiharmonic | Multiple harmonics in one solve |
| `create_simulation_transient` | Transient | Time-dependent (heating, dynamics over time) |
| `create_simulation_eigenmode` | Eigenmode | Natural frequencies / modes |

Low-level escape hatch: `create_simulation(...)` with explicit `analysis_type`.

## Common kwargs

- `name`, `description`, `max_run_time_minutes` — required on all helpers
- `mesh` — `Mesh` object or mesh ID string
- `solver_mode=allsolve.SolverMode.DIRECT` — or iterative with `solver_tolerance`
- `physics_set` — `PhysicsSet` object or ID string (v0.5.0+; replaces deprecated `physics=[id, ...]`)
- `variable_overrides` — for parametric sweeps (see `allsolve-variables-and-overrides`)

## Type-specific examples

**Transient:**

```python
sim = project.create_simulation_transient(
    name="Thermal transient",
    description="...",
    max_run_time_minutes=30,
    solver_mode=allsolve.SolverMode.DIRECT,
    mesh=mesh.id,
    timestep_algorithm=allsolve.TimestepAlgorithm.IMPLICIT_EULER,  # or GEN_ALPHA; SolidMechanics/ElasticWaves REQUIRE GEN_ALPHA
    transient_start_time="0",
    transient_end_time="3600",
    transient_timestep_size="30",
)
```

Use project variables for end time / timestep when sweeping: `transient_end_time="sim_end_time"`.

**Harmonic:**

```python
sim = project.create_simulation_harmonic(
    name="Harmonic",
    description="...",
    max_run_time_minutes=30,
    mesh=mesh.id,
    fundamental_frequency="1e6",
)
```

**Multiharmonic:**

```python
sim = project.create_simulation_multiharmonic(
    name="Multi",
    description="...",
    max_run_time_minutes=30,
    mesh=mesh.id,
    fundamental_frequency="1e6",
    harmonics=[1, 2, 3],
)
```

**Eigenmode:**

```python
sim = project.create_simulation_eigenmode(
    name="Modal analysis",
    description="...",
    max_run_time_minutes=30,
    mesh=mesh.id,
    num_requested_eigenmodes="10",
    target_eigenfrequency="1e6",
)
```

## Resource reservations

Cloud compute can be reserved ahead of time to avoid repeated queue waits across geometry, mesh, and simulation jobs:

```python
with client.resource_reservation(node_type=allsolve.CPU.CORES_4_64GB) as reservation:
    mesh.run(print_logs=True, on_error=allsolve.OnError.STRICT, resource_reservation=reservation)
    sim.run(print_logs=True, on_error=allsolve.OnError.STRICT, resource_reservation=reservation)
```

The `resource_reservation=` parameter is accepted by geometry `build()`/`run()`, mesh `run()`/`start()`, and simulation `run()`/`start()`. See `examples/resource_reservation/` for advanced patterns.

## Run pattern

Always mesh before simulate. Pick one error-handling style:

| `on_error` | Behavior |
|------------|----------|
| `IGNORE` (default) | Never raises — check `get_status()` yourself |
| `RAISE` | Raises `JobError` on hard failures only; **allows** `PARTIAL_SUCCESS` and `ABORTED` through |
| `STRICT` | Raises `JobError` unless status is exactly `SUCCESS` |

**Recommended — strict success:**

```python
def run_mesh_and_simulation(mesh, sim, verbose=True):
    mesh.run(print_logs=verbose, on_error=allsolve.OnError.STRICT)
    sim.run(print_logs=verbose, on_error=allsolve.OnError.STRICT)
```

**Alternative — manual status check (default `IGNORE`):**

```python
def run_mesh_and_simulation(mesh, sim, verbose=True):
    mesh.run(print_logs=verbose)
    if mesh.get_status() != allsolve.Job.SUCCESS:
        raise RuntimeError(f"Mesh failed: {mesh.get_status()}")

    sim.run(print_logs=verbose)
    if sim.get_status() != allsolve.Job.SUCCESS:
        raise RuntimeError(f"Simulation failed: {sim.get_status()}")
```

Do **not** combine `OnError.RAISE` with a manual `get_status() != SUCCESS` check unless you intentionally want two layers. For most scripts, use `STRICT` instead.

## Instance size (node type)

Simulation OOM during solve → increase node type via `Runtime`:

```python
sim.set_runtime(allsolve.Runtime(node_type=allsolve.CPU.CORES_4_64GB))
sim.save()
```

Mesh and simulation node types are configured independently. See `allsolve-mesh` for the full node type table.

## Outputs

```python
sim.add_outputs([
    allsolve.Output.FieldOutput(name="Temperature", expression="T"),
    allsolve.Output.ValueOutput(name="Max stress", expression="max(reg.part, vmises, 1)"),
])
```

Additional output types:

| Type | Use |
|------|-----|
| `Output.FieldOutput` | Spatial field (VTU download) |
| `Output.ValueOutput` | Scalar/vector value per step |
| `Output.FieldState` | Raw field state snapshot |
| `Output.Eigenfrequencies` | Natural frequencies (eigenmode) |
| `Output.Eigenvalues` | Eigenvalues (eigenmode) |
| `Output.SParameters` | S-parameters (EM) |

After a successful run:

```python
data = sim.get_output_data()          # refresh=True by default
csv_text = data.to_csv(csv_format=allsolve.CsvExportFormat.NORMAL)
data.to_csv_file("results.csv")
data.clean_cache()                    # free local cache when done
```

CSV notes:
- Transient rows often use column **`Step`** for time (seconds).
- **`Sweep step`** appears for parametric sweeps.
- Match output names exactly when parsing (e.g. `"Average temperature (part)"`).
- **`to_csv_file()` does NOT overwrite** existing files — delete or rename the target file before calling, or use unique filenames.

**Downloading field output VTU files:**

```python
sim.save_output_field(name="Temperature", output_dir="./results")
# For sweep: sim.save_output_field(name="Temperature", output_dir="./results", sweep_index=0)
```

**Non-blocking run:**

```python
sim.start()
while sim.is_running(refresh_delay_s=1):
    sim.print_new_loglines()
sim.print_new_loglines()
print("Status:", sim.get_status())
```

## Job statuses

- With `on_error=allsolve.OnError.IGNORE` (default), check `.get_status()` after `run()` — only proceed on `allsolve.Job.SUCCESS`.
- With `on_error=allsolve.OnError.STRICT`, `run()` raises `JobError` on any non-`SUCCESS` status; no separate check needed.
- With `on_error=allsolve.OnError.RAISE`, hard failures raise `JobError`; `PARTIAL_SUCCESS` / `ABORTED` return normally.

On failure, read the last log lines before retrying — do not blindly re-run with identical settings.

## Logs and debugging

- `mesh.run(print_logs=True)` / `sim.run(print_logs=True)` — stream cloud job logs.
- Transient logs show `@30s`, `@60s`, … progress markers.
- Simulation script errors (e.g. `NameError` in custom script) appear only in cloud job logs — see `allsolve-simulation-scripts`.
- Browser URL: `client.get_url(project)` — visualize field outputs after run.

## Simulation properties (v0.5.0+)

- `sim.project_id` — project this simulation belongs to.
- `sim.variable_overrides_id` — ID of the variable overrides set, or `None`.
- `sim.physics_set` — `PhysicsSet` object, or `None`.

## Batch job polling

Refresh status on multiple jobs in one API call:

```python
Job.refresh_statuses([sim1._get_job(), sim2._get_job()])
```

Custom simulation scripts (`set_scripts`, solver namespaces, stubs): see `allsolve-simulation-scripts` — rarely needed.

## Gotchas

### Timestep and solver

- **Solid Mechanics and Elastic Waves require `GEN_ALPHA`** — `IMPLICIT_EULER` is not applicable for these physics.
- **`genalpha` is implicit** — CFL stability limits do NOT apply. Choose `dt` based on temporal accuracy (~20 points per period).
- **Multi-node DDM: must use `SolverMode.ITERATIVE`** — `SolverMode.DIRECT` crashes with MPI errors on multi-node runs. Use `node_count=2` for ~500k DOF, `4` for ~1–2M DOF, `8` for >2M DOF.
- **Large runs need a bigger HEAD node** — rank 0 needs far more memory than workers. If the run dies right after `Time to partition the mesh ...` with no `Generalized alpha run for N dofs` line, use `client.resource_reservation(main_node_type=allsolve.CPU.CORES_8_128GB)` to upsize the head node. `main_node_type` is on `ResourceReservation`, not on `Runtime`.

### Output extraction

- **`get_output_values()` returns a dict of ALL steps** keyed by step label (e.g. time values for transient sims). For structured access, use `sim.get_output_data(refresh=True)` and iterate with `get_value_at(sweep_index, step_index, value_header)`. See `allsolve-variables-and-overrides` for sweep extraction patterns.
- **`to_dataframe()` / `sweep_step_to_dataframe(si)`** — pandas view of `OutputData`; alternative to `get_value_at` loops. Rows per array element; columns `Sweep step`, `Step`, `Array index`, overrides, value outputs. Scalar outputs broadcast (=`to_csv` `EXPLODED`). Needs `pip install allsolve[dataframe]`.
- **`save_output_field` `step_index` defaults to `None`** — fine for static/harmonic sims, but for transient sims you must pass an explicit `step_index=N` to select which time step to download. Pass `refresh=True` on the first call.
- **Harmonic field output: `norm(field)` fails** — use `norm(harm(2, E))` instead. Downloaded files are zstd-compressed VTKHDF named `<name>_nostep_0.hdf` (same name per sweep → overwrites; download+rename one sweep at a time).
- **`Output.FieldOutput(..., target=region)` restricts export to a region** — use for per-part renders.

### Robust result extraction

- **Static** results live at `NO_STEP`.
- **Eigenmode** results: one value per step (one frequency per mode).
- **A fully-errored sweep** has no steps → `get_step_index(NO_STEP)` raises `Step label nostep not found`.
- **Mechanics-only sims** cannot evaluate T-dependent material properties — assign density + elasticity only.
- **Do NOT parse streamed logs for per-step timing** — the server batches lines. Use `time.perf_counter()` around `timestepper.allnext()` and emit via `qs.setoutputvalue`.
- **FFT / impedance post-processing** — see `allsolve-postprocessing` for windowing, zero-padding, and division-by-zero safeguards.
