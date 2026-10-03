---
name: allsolve-variables-and-overrides
description: >-
  Define Allsolve project variables and parametric sweep overrides. Use when
  creating project variables, create_variables, variable_overrides, parametric
  sweeps, sweep steps, or referencing expressions in geometry/materials/simulation.
---

# Allsolve variables and overrides

Variables must be created **before** geometry, regions, materials, or physics that reference them — expressions like `"base_length_x / 2"` resolve at build/solve time.

## Creating variables

```python
project.create_variables([
    ("L", "0.1", "Length [m]"),
    ("W", "0.05", "Width [m]"),
    ("H", "0.02", "Height [m]"),
    ("room_temp", "293.15", "Ambient temperature [K]"),
    ("h_conv", "10", "Convection coefficient [W/m²/K]"),
])
```

Each tuple is `(name, expression, description)`. Expressions can reference other variables defined earlier in the list (e.g. `"L / 2"`).

## Using variables

Variables are referenced **by name as strings** throughout the SDK:

```python
builder.add_box(name="block", position=(0, 0, 0), size=("L", "W", "H"))

project.create_region_rule(
    name="solid",
    entity_type=allsolve.Region.VOLUME,
    bounding_box=(("-L/2", "-W/2", 0), ("L/2", "W/2", "H")),
)

project.create_material(
    name="Steel",
    target_region=regions.solid,
    thermal_conductivity="k_steel",
)
```

## Parametric sweeps

Create a `VariableOverrides` object to sweep variable values across simulation runs:

```python
sweep = project.create_variable_overrides(
    name="param_sweep",
    overrides=[
        ("L", ["0.05", "0.1", "0.15", "0.2"]),
    ],
)

sim = project.create_simulation_static(
    name="Sweep",
    description="...",
    mesh=mesh,
    max_run_time_minutes=15,
    variable_overrides=sweep,
)
```

Results CSV includes a **`Sweep step`** column.

### Sweep types

```python
sweep = project.create_variable_overrides(
    name="param_sweep",
    sweep_type=allsolve.SweepType.CARTESIAN_PRODUCT,
    overrides=[
        ("height", ["3e-3", "3.5e-3"]),
        ("force", "linspace(-1000, -2000, 3)"),
    ],
)
```

`SweepType.CARTESIAN_PRODUCT` generates all combinations. Default is `SweepType.SPECIFIC_VALUES` (lockstep pairing by index).

### Geometry-dependent sweeps

When sweep variables affect geometry (dimensions, enabled parts), the mesh must also receive the sweep so it remeshes per sweep point:

```python
mesh = project.create_mesh(
    allsolve.MeshSettings(
        name="Default mesh",
        scale_factor=1.0,
        max_run_time_minutes=10,
        variable_overrides=[sweep],
    )
)
mesh.get_override(sweep).run(print_logs=True)

sim = project.create_simulation_static(
    ..., mesh=mesh, variable_overrides=sweep,
)
```

Only `mesh.get_override(sweep).run()` is needed — it meshes each geometry variant in the sweep. Do NOT call `mesh.run()` first; that would process only the default (non-swept) instance, which is redundant.

### Extracting per-sweep-point results

```python
output_data = sim.get_output_data(refresh=True)
n_sweeps = output_data.get_sweep_count()
overrides_list = output_data.get_sweep_step_overrides()  # list of dicts
nostep_idx = output_data.get_step_index(output_data.NO_STEP)  # for static sims

for si in range(n_sweeps):
    params = overrides_list[si]
    val = output_data.get_value_at(si, nostep_idx, "my_output_name")
```

- `get_value_at(sweep_index, step_index, value_header)` — step_index must be an int; use `get_step_index(output_data.NO_STEP)` for static sims
- `get_sweep_step_overrides()` returns a list of dicts mapping variable names to lists of floats

Pattern: define variables → reference in geometry/materials/sim → sweep via `variable_overrides`.

## Library shared expressions (v0.5.0+)

Copy variables, functions, and interpolated functions from the organization library:

```python
project.create_variable_from_library("room_temp")
project.create_function_from_library("wavelet")
project.create_interpolated_function_from_library("material_curve")
```

Discover available library items:

```python
allsolve.Variable.get_all_from_library()
allsolve.Function.get_all_from_library()
allsolve.InterpolatedFunction.get_all_from_library()
```

SDK examples: `examples/simple_sweep`, `examples/bending_beam`, `examples/geometric_sweep`.

## Gotchas

### Sweep mechanics

- **Sweep meshing is de-duplicated by geometry.** Override variables that change only boundary values or material properties (not geometry) reuse the mesh. A `(20 diameters × 5 temperatures)` grid = 20 meshes + 100 solves. Fewer meshes than sweep points is correct, not a bug.
- **`get_step_index(output_data.NO_STEP)` for static sims** — `step_index` must be an int. Do NOT pass `output_data.NO_STEP` directly to `get_value_at`.
- **`MeshExtrusion.sub_layer_counts` accepts string variable references** (e.g. `["mesh_N"]`) resolved per sweep point.

### Mesh convergence

- **ONE sim with 2D sweep for mesh convergence.** Make mesh size a variable referenced by region refinement, then sweep `(mesh_size × param)`. The mesh regenerates once per distinct `mesh_size`; non-geometry params reuse that mesh.
- **A flat QoI-vs-h curve means CONVERGED, not broken.** Go coarser until the QoI visibly moves, then refine back to the plateau.

### Tuning with sweeps

- **Two-stage tuning**: (1) coarse sweep over a design parameter → interpolate to target; (2) dense sweep over a second parameter to maximise a QoI. Use the temporary project pattern (see `allsolve-project-workflow`).
- **`scipy.interpolate.interp1d` requires monotonically increasing x.** For non-monotonic QoI, use `np.argmax`.
