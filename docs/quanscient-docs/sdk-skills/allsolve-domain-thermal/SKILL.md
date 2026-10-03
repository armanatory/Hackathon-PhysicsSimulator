---
name: allsolve-domain-thermal
description: >-
  Thermal and heat transfer simulations with the Allsolve SDK: HeatTransfer,
  HeatFluid, temperature, convection, heat source, thermal, heat sink,
  conduction, cooling, thermal simulation, Joule heating. Use when the
  simulation involves temperature fields, thermal conduction, convection
  cooling, or coupled thermal problems.
disable-model-invocation: true
---

# Thermal / Heat transfer simulations

End-to-end guide for heat transfer simulations using `HeatTransfer` (solid conduction) and `HeatFluid` (fluid thermal) physics. For generic SDK building blocks (project lifecycle, geometry, variables, mesh settings), see the corresponding `allsolve-*` skills.

## Physics

```python
physics_set = project.get_default_physics_set()
heat = physics_set.add_physics(allsolve.Physics.HeatTransfer())
```

For fluid thermal problems, use `HeatFluid` instead:

```python
heat_fluid = physics_set.add_physics(allsolve.Physics.HeatFluid())
```

`HeatFluid` solves the energy equation in a fluid domain. It requires a coupled `LaminarFlow` physics for the velocity field — without it, there is no advection term. Typically used for conjugate heat transfer (solid conduction + fluid convection).

Temperature field symbol: **`T`**. Temperatures are always **kelvin**.

## Interactions

### Convection (Robin BC)

Heat loss to an ambient fluid:

```python
allsolve.Interaction.HeatTransferConvection(
    name="Ambient convection",
    target=regions.exposed_surfaces,
    heat_transfer_convection_heat_transfer_coefficient="h_conv",  # project variable [W/m²/K]
    heat_transfer_convection_fluid_temperature="T_ambient",       # project variable [K]
)
```

Define `h_conv` and `T_ambient` as project variables. Typical values: `h_conv` = 5–25 W/m²/K for natural convection in air, 50–1000+ for forced convection; `T_ambient` = 293.15 K (20 °C).

### Heat source

Volumetric or surface heating:

```python
allsolve.Interaction.HeatTransferHeatSource(
    name="Heater",
    target=regions.heat_surface,
    heat_source_power_density="Q_heat",  # project variable [W/m³]
)
```

### Temperature constraint (Dirichlet)

Fixed temperature on a boundary:

```python
allsolve.Interaction.HeatTransferTemperatureConstraint(
    name="Fixed temp",
    target=regions.fixed_surface,
    temperature_constraint="273.15",
)
```

### Joule heating

Coupled electrical heating (requires a current-flow or EM physics):

```python
allsolve.Interaction.HeatTransferJouleHeating(
    name="Joule heating",
    target=regions.conductor,
)
```

### Interaction summary

| Interaction | Purpose |
|-------------|---------|
| `HeatTransferConvection` | Robin BC to ambient fluid |
| `HeatTransferHeatSource` | Volumetric or surface heating (W/m^3) |
| `HeatTransferTemperatureConstraint` | Dirichlet (fixed T) |
| `HeatTransferJouleHeating` | Coupled electrical heating |

## Thermal contact

For solid heat transfer (`Physics.HeatTransfer`), touching volumes share temperature at interfaces automatically. **A gap between bodies blocks conduction** — volumes must meet (coincident shared faces after geometry `build()`).

## Initial temperature

The default initial temperature is 0 K. Set a physical initial condition via a custom script in `AFTER_FIELDS_CREATED`:

```python
sim.set_scripts([
    allsolve.Script(
        name="init_temp.py",
        section_name=allsolve.CustomSection.AFTER_FIELDS_CREATED,
        content="fld.T.setvalue(reg.all, expr.room_temp)",
    )
])
```

`room_temp` must be a project variable (e.g. `("room_temp", "293.15", "Ambient temperature [K]")`). To initialize subsets differently: `fld.T.setvalue(reg.my_region, expr.freezer_temp)`.

## Materials

Thermal materials need `density`, `heat_capacity`, and `thermal_conductivity`. See `allsolve-materials` for general material creation.

- `density` and `heat_capacity` are required for transient (thermal mass).
- `thermal_conductivity` is required for all thermal simulations.

## Simulation types

Use `create_simulation_static` for steady-state or `create_simulation_transient` for time-dependent problems. See `allsolve-simulation` for full kwargs.

For transient thermal: use `TimestepAlgorithm.IMPLICIT_EULER` and always set an initial temperature (see above) — the default 0 K is unphysical.

## Outputs

### Temperature field

```python
allsolve.Output.FieldOutput(
    name="Temperature",
    expression="T",
)
```

Visualize in the Allsolve web app with a **Clip** filter to see the temperature distribution inside the geometry.

### Scalar value outputs

```python
allsolve.Output.ValueOutput(
    name="Average temperature (part)",
    expression="average(reg.copper_material_region, T, 3)",
)
allsolve.Output.ValueOutput(
    name="Max temperature",
    expression="max(reg.all, T, 1)",
)
```

## Typical region pattern

For a heat sink with convection on exposed surfaces:

```python
regions.solid = project.create_region_rule(
    name="solid",
    entity_type=allsolve.Region.VOLUME,
    bounding_box=(solid_min, solid_max),
)
regions.exposed = project.create_region_computed(
    name="exposed_surfaces",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.BOUNDARY,
    source_regions=[regions.solid.id],
)
regions.bottom = project.create_region_rule(
    name="bottom_surface",
    entity_type=allsolve.Region.SURFACE,
    bounding_box=(bottom_min, bottom_max),
)
```

## Reference examples

- `pin_fin_heat_sink/heat_sink_demo.py` — transient pin-fin heat sink with convection cooling, volumetric heat source, library materials, mesh refinement, and average temperature outputs.
