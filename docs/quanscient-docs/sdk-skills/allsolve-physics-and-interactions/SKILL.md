---
name: allsolve-physics-and-interactions
description: >-
  Add Allsolve physics, physics sets, and boundary condition interactions:
  HeatTransfer, SolidMechanics, HeatFluid, convection, heat sources,
  temperature constraints. Use when adding add_physics, PhysicsSet,
  create_physics_set, get_default_physics_set, Physics.HeatTransfer,
  Interaction, BoundaryAdmittance, convection, heat source, temperature
  constraint, joule heating, or coupled multiphysics.
disable-model-invocation: true
---

# Allsolve physics and interactions

## Adding physics

Each project has a default physics set (named `"Physics 1"`). Use it for single-physics workflows:

```python
physics_set = project.get_default_physics_set()
heat = physics_set.add_physics(allsolve.Physics.HeatTransfer())
```

For alternative physics configurations, create a named set:

```python
alt_set = project.create_physics_set(name="alt_physics")
heat = alt_set.add_physics(allsolve.Physics.HeatTransfer())
```

`project.add_physics(...)` is deprecated (v0.5.0) — use `physics_set.add_physics()` instead.

### Physics set management

```python
project.get_physics_sets()              # list all sets
project.get_default_physics_set()       # default set
project.create_physics_set(name="alt")  # new named set
PhysicsSet.copy_physics_set(set.id)     # copy an existing set
```

Simulations reference a physics set instead of a flat list of physics IDs — pass `physics_set=` to `create_simulation_*` (the old `physics=` list is deprecated).

Available physics types:

| Physics type | Field | Domain |
|-------------|-------|--------|
| `HeatTransfer` | Temperature (`T`) | Solid conduction |
| `HeatFluid` | Temperature | Fluid thermal |
| `SolidMechanics` | Displacement (`u`) | Structural |
| `ElasticWaves` | Displacement (`u`) | Wave propagation in solids |
| `AcousticWaves` | Pressure (`p`) | Acoustic domains |
| `ElectromagneticWaves` | EM fields | Full-wave EM |
| `Electrostatics` | Potential (`V`) | Static electric fields |
| `CurrentFlow` | Potential | Electric current |
| `MagnetismA` | Vector potential (`A`) | Magnetic (A-formulation) |
| `MagnetismH` | Magnetic field (`H`) | Magnetic (H-formulation) |
| `MagnetismPhi` | Scalar potential | Magnetic (scalar) |
| `LaminarFlow` | Velocity, pressure | Incompressible flow |
| `MeshDeformation` | Mesh displacement | ALE / moving mesh |

## Interactions (boundary conditions)

Interactions attach to a physics object and target a region:

```python
heat.add_interactions([
    allsolve.Interaction.HeatTransferConvection(
        name="Ambient convection",
        target=regions.exposed_surfaces,
        heat_transfer_convection_heat_transfer_coefficient="10",  # W/m²/K
        heat_transfer_convection_fluid_temperature="293.15",      # K
    ),
    allsolve.Interaction.HeatTransferHeatSource(
        name="Heater",
        target=regions.heat_surface,
        heat_source_power_density="100",  # W/m³
    ),
    allsolve.Interaction.HeatTransferTemperatureConstraint(
        name="Fixed temp",
        target=regions.fixed_surface,
        temperature_constraint="273.15",
    ),
])
```

## Domain-specific interactions

For domain-specific interaction details, load the corresponding domain skill:
- **Heat transfer**: `allsolve-domain-thermal`
- **Solid mechanics**: `allsolve-domain-structural`
- **Acoustic / elastic waves**: `allsolve-domain-acoustics`
- **Electromagnetic waves**: `allsolve-domain-rf`

**Coupled multiphysics example:** `examples/pin_fin_heat_sink/heat_sink_demo.py` in the SDK repo.

## Gotchas

### General

- **Coupled multiphysics: create ALL physics before adding interactions.** The server validates that required fields exist at interaction creation time. Fields (`displacement`, `electricPotential`, `meshDeformation`, `pressure`, `velocity`, …) are created as a side effect of `add_physics()`. Cross-physics interactions like `ElectrostaticsLargeDisplacement`, `SolidMechanicsElectricForce`, or `LaminarFlowFluidStructure` fail with `"project is missing a field required by the interaction"` (400) if the physics that owns the needed field has not been added yet. Safe pattern: call `add_physics()` for every physics first, then `add_interactions()` for each.
- **Sign convention:** all `integral()` terms are LHS (`sum = 0`). Negate known-value terms to move them to RHS.
- **`set_field_interpolation_order(n)` MUST be followed by `physic.save()`** — otherwise the generated script keeps the default order.
- **Multiple `integrate`/`average` ValueOutputs collide** on `var.discrete` in generated code (mis-ordered assignments). Use a single such value output per simulation.

### Wave physics (acoustics, EM — see domain skills for details)

- **`wavelet(freq, delay)`:** delay is in **periods**, not seconds. `delay=2.5` → peak at `2.5/freq` seconds. Works for both harmonic and transient.
- **Always set `target_frequency` on transient wave simulations** — omitting it can cause poor convergence or under/over-damping.
- **PML is a SURFACE interaction, not a volume.** Only one body of fluid is needed. Use a UNION region for multiple PML boundaries.
- **BOX PML for rectilinear domains** — explicitly pass `acoustic_waves_pml_type=allsolve.AcousticWavesPmlType.BOX` for axis-aligned box domains.
- **`pml_num_layers` is a project-level setting:** `project.pml_num_layers = N` followed by `project.save()`. Typical value is 6.
- **MUMPS ICNTL(14) workaround for PML + direct solver** — PMLs cause excessive fill-in (error -9). Inject `qs.universe.setmumpsicntl(14, N)` via `AFTER_FORMULATIONS_CREATED`. Default 20; large PML problems may need ~200.

### Piezoelectric / electrostatics (see `allsolve-domain-acoustics`)

- **Piezoelectric coupling: ONE interaction, not two.** Do NOT add both `ElasticWavesPiezoelectricity` and `ElectrostaticsPiezoelectricity` on the same region.
- **`ElectrostaticsLump` requires `namespace`** — omitting it crashes the script generator with a 500.

### Solid mechanics (see `allsolve-domain-structural`)

- **`SolidMechanicsConstraint` value is a 3x2 matrix `[active_flag, value]` per (x,y,z)** — first column must be numeric flags (1=constrain, 0=free), second column the value/expression. A plain `"[0;0;0]"` (3x1) is rejected.

### Electromagnetic / MQS (see `allsolve-domain-rf`)

- **Full-wave harmonic EM hits MUMPS `INFOG(1)=-3` at >~1.5M DOF.** Root cause is low-frequency breakdown of the E-field formulation. For sub-wavelength coils, use magnetoquasistatic `MagnetismA` instead.
- **MQS drive MUST be AC:** set lump current/voltage to `"sn(1)"`, not `"1"`. A constant drive generates zero excitation.
- **Coil impedance: use `CurrentFlowLumpVICut` (cohomology cut)** — a two-terminal `CurrentFlowLump` across a gap does NOT capture inductive EMF.
- **Output field tokens for MQS are DERIVED fields** (`B`, `H`, `j`, `E`) — primary tokens `A`, `v` evaluate to 0 in `integrate()`/`average()`. `curl(A)` is not valid; use `B`.
- **`ElectromagneticWavesRadiationPattern` fails on internal PEC loops** — likely needs an explicit Huygens box enclosing the antenna.
