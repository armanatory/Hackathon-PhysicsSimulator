---
name: allsolve-materials
description: >-
  Assign materials to Allsolve simulation regions: custom properties or library
  materials. Use when creating create_material, create_material_from_library,
  target_region, density, heat_capacity, thermal_conductivity, or assigning
  material properties to geometry.
---

# Allsolve materials

Each material needs a `target_region` matching the geometry it represents.

## Custom material

```python
project.create_material(
    name="Steel",
    target_region=regions.solid,
    density=7850,
    heat_capacity=460,
    thermal_conductivity=50,
)
```

Properties can be numeric literals or project variable expressions (strings):

```python
project.create_material(
    name="Custom",
    target_region=regions.part,
    density="rho",
    heat_capacity="cp",
    thermal_conductivity="k",
)
```

### Conditional activation for sweeps

Use `enabled` to activate a material only when a sweep variable matches:

```python
project.create_material(
    name="Aluminium",
    enabled ="material_index == 0",
    target_region=regions.part,
    density=2700,
    thermal_conductivity=237,
    heat_capacity=897,
)
project.create_material(
    name="Steel",
    enabled="eq(material_index, 1)",
    target_region=regions.part,
    density=7850,
    thermal_conductivity=50,
    heat_capacity=460,
)
```

## Library material

```python
project.create_material_from_library(name="Copper", target_region=regions.part)
```

Library materials come with standard property values. Check the Allsolve material library in the UI for available names.

## Common properties

| Property                  | Unit     | Typical use     | Notes |
| ------------------------- | -------- | --------------- | ----- |
| `color`                   | —        | Visualization   | Direct kwarg; hex `#RRGGBB` (e.g. `"#99D9FF"`). Library materials inherit their color |
| `density`                 | kg/m³    | All physics     | Direct kwarg |
| `heat_capacity`           | J/(kg·K) | Thermal         | Direct kwarg |
| `thermal_conductivity`    | W/(m·K)  | Thermal         | Direct kwarg |
| `electric_permittivity`   | F/m      | Electromagnetic | Direct kwarg |
| `magnetic_permeability`   | H/m      | Electromagnetic | Direct kwarg |
| `electric_conductivity`   | S/m      | Electromagnetic | Direct kwarg (note: `electric_`, not `electrical_`) |
| `speed_of_sound`          | m/s      | Acoustic        | Direct kwarg |
| `longitudinal_attenuation`| Np/m     | Acoustic damping| Direct kwarg |
| `shear_attenuation`       | Np/m     | Acoustic damping| Direct kwarg |

**Structural elasticity** — Young's modulus and Poisson's ratio are NOT direct kwargs. Use `MaterialProperty`:

```python
project.create_material(
    name="Steel",
    target_region=regions.solid,
    density=7850,
    elasticity_matrix=allsolve.MaterialProperty.ElasticityMatrixYoungsModulusPoissonsRatio(
        youngs_modulus="210e9",
        poissons_ratio="0.3",
    ),
)
```

Note: `youngs_modulus` and `poissons_ratio` values MUST be strings, not bare numbers.

Viscous damping (v0.5.0+) — use `MaterialProperty` classes:

```python
allsolve.MaterialProperty.ViscousDampingBulkViscosityShearViscosity(
    bulk_viscosity="1e-3", shear_viscosity="1e-4",
)
# or attenuation-based:
allsolve.MaterialProperty.ViscousDampingLongitudinalAttenuationShearAttenuation(
    longitudinal_attenuation="0.1", shear_attenuation="0.05",
)
```

All values use SI units. Use `"epsilon0"` and `"mu0"` for free-space EM constants.

## Gotchas

- **Isotropic material values MUST be strings** in `ElasticityMatrixYoungsModulusPoissonsRatio`: `("70e9", "0.32")`, not bare numbers.
- **One material per substance, multiple target volumes.** Do not call `create_material_from_library` twice for the same material on different volumes. `target_region` accepts a single `Region` object — for multiple volumes, create a computed UNION region first and pass that as the target.
- **`orientation` does NOT support spatial expressions** — only constant Euler angles. Passing expressions with `x`, `y`, etc. fails with `"Orientation expression can't be space dependent"`.
- **Monkey-patching material properties** — to override stiffness with a spatially-varying expression, inject an `AFTER_IMPORTS` custom script snippet that replaces the material class's method before `par.H()` is constructed. Avoids the 5000-char expression limit.
- **Arbitrary spatial profiles from splines** — convert to solver expressions via piecewise cubic (`qs.ifpositive()` tree) or Fourier series (`qs.cos`/`qs.sin` sum). Do the fitting in Python during project setup.
- **Spatially-graded material from grid data** — `qs.grid(gridticks=[x,y], gridvalues=vals.flatten())` does linear interpolation; grid ticks should span the geometry (points outside clamp to nearest edge). For `(nely, nelx)` arrays, use `rho.T.flatten()` to match grid tick order.
