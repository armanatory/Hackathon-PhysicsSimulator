---
name: allsolve-domain-structural
description: >-
  Structural mechanics simulations with the Allsolve SDK: SolidMechanics,
  bending beam, clamp, load, displacement, eigenmode, eigenmodes, natural
  frequency, stress, von Mises, structural simulation. Use when the simulation
  involves static deformation, eigenmode analysis, or mechanical loading.
disable-model-invocation: true
---

# Structural mechanics simulations

End-to-end guide for solid mechanics simulations using `SolidMechanics` physics. For generic SDK building blocks (project lifecycle, geometry, variables, mesh settings), see the corresponding `allsolve-*` skills.

## Physics

```python
physics_set = project.get_default_physics_set()
solid = physics_set.add_physics(allsolve.Physics.SolidMechanics())
```

For multi-body problems where only a subset of volumes is structural, pass an explicit target:

```python
solid = physics_set.add_physics(
    allsolve.Physics.SolidMechanics(target=regions.solid_domain)
)
```

## Interactions

### Clamp (fixed support)

```python
allsolve.Interaction.SolidMechanicsClamp(
    name="Fixed end",
    target=regions.clamp_surface,
)
```

### Applied load

```python
allsolve.Interaction.SolidMechanicsLoad(
    name="Force",
    target=regions.load_surface,
    force=(0, 0, "F"),
)
```

`force` is a 3-tuple `(Fx, Fy, Fz)` — components can be numeric or project variable expressions.

### Prescribed displacement (constraint)

```python
allsolve.Interaction.SolidMechanicsConstraint(
    name="Constraint",
    target=regions.movable_plate,
    solid_mechanics_constraint="[1, 0; 1, 0; 0, 0]",
)
```

The constraint format is `[flag, value; ...]` per component — `1` = constrained, `0` = free.

### Additional interactions

| Interaction | Purpose |
|-------------|---------|
| `SolidMechanicsLump` | Lumped spring/force coupling (MEMS actuators) |
| `SolidMechanicsElectricForce` | Electrostatic force coupling (requires `Electrostatics` physics) |
| `SolidMechanicsLargeDisplacement` | Enable geometric nonlinearity for large deformations |
| `SolidMechanicsGeometricNonlinearity` | Fine control over nonlinear strain measures |

## Materials

Structural materials need `density` and `elasticity_matrix`. See `allsolve-materials` for general material creation.

### Isotropic

```python
project.create_material(
    name="Aluminium",
    target_region=regions.beam,
    density=2700,
    elasticity_matrix=allsolve.MaterialProperty.ElasticityMatrixYoungsModulusPoissonsRatio(
        "68e9", "0.32",
    ),
)
```

### Anisotropic (full 6x6 elasticity matrix)

```python
elasticity_matrix=allsolve.MaterialProperty.ElasticityMatrix(
    value=[
        [194.5e9, 35.7e9, 64.1e9, 0, 0, 0],
        [35.7e9, 194.5e9, 64.1e9, 0, 0, 0],
        [64.1e9, 64.1e9, 165.7e9, 0, 0, 0],
        [0, 0, 0, 79.6e9, 0, 0],
        [0, 0, 0, 0, 79.6e9, 0],
        [0, 0, 0, 0, 0, 50.9e9],
    ]
)
```

## Simulation types

Use `create_simulation_static` for equilibrium deflection, `create_simulation_eigenmode` for natural frequencies. See `allsolve-simulation` for full kwargs.

Eigenmode-specific parameters:
- `num_requested_eigenmodes` — how many modes to find.
- `target_eigenfrequency` — solver searches near this frequency; `"0"` finds the lowest modes.

## Outputs

### Displacement field

```python
allsolve.Output.FieldOutput(
    name="Displacement",
    expression="u",
)
```

Visualize in the Allsolve web app with a **Warp** filter and scale factor.

### Scalar value outputs

```python
allsolve.Output.ValueOutput(
    name="Tip deflection Z",
    expression="probe(reg.tip_point, compz(u))",
)
allsolve.Output.ValueOutput(
    name="Max von Mises stress",
    expression="max(reg.beam_volume, vmises, 1)",
)
allsolve.Output.ValueOutput(
    name="Deflection along beam",
    expression="lineinterpolate(reg.beam_volume, compz(u), getcoords(reg.start_point), getcoords(reg.end_point), 10)",
)
```

### Eigenmode outputs

```python
allsolve.Output.FieldOutput(
    name="u",
    expression="u",
    field_output_skin_only=True,
)
allsolve.Output.Eigenfrequencies(name="Eigenfrequencies")
```

## MEMS structures (GDS import + extruded mesh)

For MEMS devices imported from GDSII layout files, use `add_gds2_file` with `CadGdsLayer` entries for each layer. Pair this with `MeshExtrusion` for structured meshing through thin-film layers.

Key API surfaces:
- `geometry_builder.add_gds2_file(filepath, name, unit, layers, extrude_parameters)` — import GDS geometry
- `allsolve.CadGdsLayer(layer, type, absolute_z0, thickness, name)` — per-layer definition
- `allsolve.MeshExtrusion(regions, sub_layer_counts)` — structured extrusion mesh

See `examples/combdrive_eigenmodes/combdrive_eigenmodes.py` in the SDK repo for a complete working example with multi-layer GDS import, extruded meshing, and eigenmode analysis. Layer numbers, thicknesses, and mesh parameters are device-specific — adapt from the example to your geometry.

## Reference examples

- `bending_beam/bending_beam.py` — basic cantilever beam, static analysis, displacement field output.
- `bending_beam/bending_beam_sweep.py` — parametric sweep over height, material, and force.
- `combdrive_eigenmodes/combdrive_eigenmodes.py` — MEMS comb-drive eigenmode analysis with GDS import and extruded mesh.

## Gotchas

- **`SolidMechanicsConstraint` value is a 3x2 matrix** — `[active_flag, value]` per (x,y,z). First column must be numeric flags (1=constrain, 0=free), second column the value/expression. A plain `"[0;0;0]"` (3x1) is rejected.
- **Isotropic elasticity values MUST be strings** in `ElasticityMatrixYoungsModulusPoissonsRatio`: `("70e9", "0.32")`, not bare numbers.
