---
name: allsolve-domain-rf
description: >-
  RF, microwave, and antenna simulations with the Allsolve SDK:
  ElectromagneticWaves, S-parameters, eigenmode port, microstrip, waveguide,
  antenna, PEC, dielectric loss, boundary admittance, full-wave EM, harmonic
  simulation. Use when the simulation involves electromagnetic wave propagation,
  port excitation, or S-parameter extraction.
disable-model-invocation: true
---

# RF / Microwave / Antenna simulations

End-to-end guide for full-wave electromagnetic simulations using `ElectromagneticWaves` physics. For generic SDK building blocks (project lifecycle, geometry, variables, mesh settings), see the corresponding `allsolve-*` skills.

## Physics

```python
physics_set = project.get_default_physics_set()
em = physics_set.add_physics(
    allsolve.Physics.ElectromagneticWaves(target=regions.em_domain)
)
```

The EM `target` region should cover the volume where Maxwell's equations are solved — typically the UNION of all dielectric and air volumes. If conductors are modelled as PEC (surface boundary condition), exclude those volumes. If conductors are volumetric (with finite conductivity), include them.

## Interactions

### Perfect electric conductor (PEC)

Metallic walls, ground planes, and traces:

```python
allsolve.Interaction.ElectromagneticWavesPerfectConductor(
    name="PEC walls and trace",
    target=regions.pec,
)
```

PEC surfaces are typically the domain boundary minus port faces:

```python
pec = project.create_region_computed(
    name="pec",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.DIFFERENCE,
    source_regions=[em_boundary.id, ports.id],
)
```

### Boundary admittance

`ElectromagneticWavesBoundaryAdmittance` (replaces the removed `BoundaryImpedance` from v0.4.x):

```python
allsolve.Interaction.ElectromagneticWavesBoundaryAdmittance(
    name="Surface admittance",
    target=regions.boundary,
    electromagnetic_waves_boundary_admittance_type=allsolve.ElectromagneticWavesBoundaryAdmittanceType.ADMITTANCE,
    electromagnetic_waves_boundary_admittance_yr="1.0",
    electromagnetic_waves_boundary_admittance_yi="0.0",
)
```

Admittance types: `ADMITTANCE` (specify Yr, Yi) or `GOOD_CONDUCTOR` (specify conductivity, magnetic permeability).

### Dielectric loss

Lossy substrate (e.g. FR-4):

```python
allsolve.Interaction.ElectromagneticWavesDielectricLoss(
    name="FR-4 loss",
    target=regions.substrate,
    electromagnetic_waves_dielectric_loss_loss_tangent="0.02",
)
```

### Eigenmode port (S-parameter extraction)

```python
em.add_interactions([
    allsolve.Interaction.ElectromagneticWavesEigenmodePort(
        name="Port 1",
        port_target=regions.port1,
        electromagnetic_waves_eigenmode_port_driving_signal="sn(1)",
        electromagnetic_waves_eigenmode_port_drive=True,
        electromagnetic_waves_eigenmode_port_num_eigenmodes="5",
        electromagnetic_waves_eigenmode_port_eigenmode_index="0",
        electromagnetic_waves_eigenmode_port_target_eigenvalue_type=(
            allsolve.ElectromagneticWavesEigenmodePortTargetEigenvalueType.EFFECTIVE_REFRACTIVE_INDEX
        ),
        electromagnetic_waves_eigenmode_port_effective_refractive_index="n_eff",  # project variable
    ),
    allsolve.Interaction.ElectromagneticWavesEigenmodePort(
        name="Port 2",
        port_target=regions.port2,
        electromagnetic_waves_eigenmode_port_driving_signal="sn(1)",
        electromagnetic_waves_eigenmode_port_drive=False,
        electromagnetic_waves_eigenmode_port_num_eigenmodes="5",
        electromagnetic_waves_eigenmode_port_eigenmode_index="0",
        electromagnetic_waves_eigenmode_port_target_eigenvalue_type=(
            allsolve.ElectromagneticWavesEigenmodePortTargetEigenvalueType.EFFECTIVE_REFRACTIVE_INDEX
        ),
        electromagnetic_waves_eigenmode_port_effective_refractive_index="n_eff",  # same as Port 1
    ),
])
```

The `effective_refractive_index` value is geometry- and substrate-dependent. Define it as a project variable and compute it from your substrate permittivity (e.g. `n_eff ≈ sqrt((ε_r + 1)/2)` for a microstrip approximation) or determine via eigenmode analysis.

### Eigenmode port gotchas

- **`driving_signal`** must be `"sn(1)"` for harmonic simulations (`sn` = sinusoidal at the fundamental frequency). Using a plain constant like `"1"` produces incorrect excitation.
- **`target_eigenvalue_type`** is required. If set to `PROPAGATION_CONSTANT`, supply `electromagnetic_waves_eigenmode_port_propagation_constant`. If set to `EFFECTIVE_REFRACTIVE_INDEX`, supply `electromagnetic_waves_eigenmode_port_effective_refractive_index`. Omitting the matching value raises `ValueError`.
- Only **one port** should have `drive=True` (the excited port); passive ports use `drive=False`.
- Port target regions must be surface regions **contained within** the physics domain boundary. If a bounding-box region rule picks up surfaces outside the EM domain, intersect with the domain boundary (see Port regions below).

## Port regions

Port faces selected by bounding box may include surfaces outside the EM domain (e.g. outer enclosure faces at the same coordinate as the port plane). This causes: `Interaction "..." targets tags [...] that are outside its physics target region.`

Fix by intersecting the bounding-box rule with the domain boundary:

```python
em_domain = project.create_region_computed(
    name="em_domain",
    entity_type=allsolve.Region.VOLUME,
    operation=allsolve.RegionOperation.UNION,
    source_regions=[substrate.id, air.id],
)
em_boundary = project.create_region_computed(
    name="em_boundary",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.BOUNDARY,
    source_regions=[em_domain.id],
)

port1_all = project.create_region_rule(
    name="port1_all",
    entity_type=allsolve.Region.SURFACE,
    bounding_box=(port1_min, port1_max),
)
port1 = project.create_region_computed(
    name="port1",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.INTERSECTION,
    source_regions=[port1_all.id, em_boundary.id],
)
```

## Materials

EM simulations need `electric_permittivity`, `magnetic_permeability`, and `electric_conductivity` on every material region. Use `"epsilon0"` and `"mu0"` for free-space constants.

| Material | `electric_permittivity` | Notes |
|----------|------------------------|-------|
| Air / vacuum | `"epsilon0"` | |
| FR-4 substrate | `"4.4 * epsilon0"` | Add `DielectricLoss` interaction for loss tangent |
| Copper trace | `"epsilon0"` | Conductor; often modelled as PEC instead |

The conductor region (trace) needs a material assigned even if it is outside the EM physics domain, because the mesh covers it.

## Simulation

Use `create_simulation_harmonic` for frequency-domain S-parameter extraction:

```python
sim = project.create_simulation_harmonic(
    name="S-parameter sweep",
    description="...",
    max_run_time_minutes=120,
    solver_mode=allsolve.SolverMode.DIRECT,
    mesh=mesh.id,
    fundamental_frequency="freq",
    physics_set=physics_set,
)
```

For modal analysis (finding propagation constants / effective indices), use `create_simulation_eigenmode`.

## Outputs

```python
sim.add_outputs([
    allsolve.Output.SParameters(name="S-parameters"),
    allsolve.Output.FieldOutput(
        name="E field (sin)",
        expression="harm(2, E)",
        field_output_skin_only=True,
    ),
])
```

- `Output.SParameters` extracts the full S-matrix from eigenmode port data.
- `harm(2, E)` gives the sine component of the electric field; `harm(3, E)` gives cosine.

## Mesh strategy

Full-wave EM meshes can be very large. Recommended approach:

1. **Start coarse** — `scale_factor=1.5`–`2.0` or higher and a larger node type (e.g. `CORES_4_64GB`). Verify the simulation runs before tightening.
2. **Set `mesh_size_max`** to approximately λ/6–λ/10 at the highest sweep frequency.
3. **Refine near traces and ports** with `MeshRefinement`.
4. **Consider `use_mesh_refiner=False`** if the auto-refiner over-resolves thin layers (e.g. microstrip traces) — density should be driven by wavelength, not geometric features.

```python
c0 = 3e8
lambda_min = c0 / f_max  # shortest wavelength at highest frequency

mesh = project.create_mesh(
    allsolve.MeshSettings(
        name="EM mesh",
        scale_factor=2.0,
        mesh_size_max=lambda_min / 6,
        max_run_time_minutes=30,
        refinements=[
            allsolve.MeshRefinement(region=regions.near_port, max_size=lambda_min / 20),
        ],
    )
)
```

Adapt `mesh_size_max`, `mesh_size_min`, and refinement sizes to your geometry — the values above are illustrative.

## Frequency sweeps

Use `create_variable_overrides` to sweep frequency (and optionally geometry parameters):

```python
sweep = project.create_variable_overrides(
    name="freq_sweep",
    sweep_type=allsolve.SweepType.CARTESIAN_PRODUCT,
    overrides=[
        ("freq", "linspace(f_start, f_end, N_freq)"),
    ],
)
```

Define `f_start`, `f_end`, and `N_freq` as project variables to keep the sweep range parameterized. Pass `variable_overrides=sweep` to both mesh settings (if geometry changes) and simulation.

## Reference examples

- `geometric_sweep/sweep.py` — microstrip stub filter with eigenmode ports; Cartesian product sweep over stub length and frequency for S-parameter extraction.

## Gotchas

- **MUMPS ICNTL(14) workaround for PML + direct solver** — PMLs cause excessive fill-in (error -9). Inject `qs.universe.setmumpsicntl(14, N)` via `AFTER_FORMULATIONS_CREATED`. Default is 20; large PML problems may need ~200.
- **Full-wave harmonic EM hits MUMPS `INFOG(1)=-3` at >~1.5M DOF** — root cause is low-frequency breakdown of the E-field formulation. `SolverMode.ITERATIVE` does NOT bypass it. For sub-wavelength coils, use magnetoquasistatic `MagnetismA` or analytic models.
- **Multi-node DDM may leave boundary regions with undefined interpolation order** — fix by injecting `fld.E.setorder(reg.all, 1)` at `AFTER_FIELDS_CREATED`.
- **`harmonic field output norm(field)` fails** — use `norm(harm(2, E))` for the magnitude of a specific harmonic.
