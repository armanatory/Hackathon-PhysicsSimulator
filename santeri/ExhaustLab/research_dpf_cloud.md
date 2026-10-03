# Diesel planner cloud model and validation

This dataset is a real Allsolve 3D finite-element solve of a **homogeneous equivalent cylindrical cartridge**. It is an engineering demonstration with entered material coefficients. It does not resolve ceramic channels or filtration pores, particle capture, soot oxidation, catalyst chemistry, ash, regeneration, or hot spots. The previous rectangular electrostatic pilot is retained separately.

The nine design geometries are diameters 120/160/200 mm crossed with active lengths 150/200/250 mm. A separate 160 × 200 mm case refines the maximum mesh size from 10 to 7 mm. Every simulation uses one rank; the batch dispatcher allows three independent meshing/solving jobs at a time. Recorded client job dispatch overlap demonstrates a parallel design batch, not distributed-solver speedup.

## Pressure model

The unknown `fld.v` is used as a generic scalar pressure field in pascals. The native electrostatic formulation is replaced by an explicit Darcy weak form; this is not an electric-field solve:

`u = -(K_eff / mu) grad(p)` and `div(u) = 0`.

A uniform axial velocity `Q/A` is imposed through the inlet Neumann flux, the outlet has zero gauge pressure, and the cylindrical wall is impermeable. The reference pressure loss is `mu L Q / (K_eff A)`. Both end fluxes use `qs.on(reg.cartridge, ...)` to trace volume gradients onto their surfaces. Applying `grad(p)` directly on the lower-dimensional surface incorrectly gives a tangential derivative; the first such exports are preserved under `dpf_d160_l200/original_surface_exports`.

The effective axial permeability belongs to the complete homogenized cartridge, including its tortuous paths. It is not ceramic-wall permeability. The demonstration reference is `K_eff = 2e-8 m²`, viscosity `3.35e-5 Pa s`, mass flow `0.025 kg/s`, and gas density from ideal gas at 101325 Pa and 723.15 K. These coefficients are assumptions for a bounded demonstration, not measured product properties. Darcy scaling is linear and excludes inertial/Forchheimer losses.

Curved surfaces are approximated by straight-sided tetrahedra. Inlet flux is therefore validated against prescribed velocity times the **finite-element face area**, while inlet area and volume errors are separately checked against the analytic cylinder. The recorded difference from the analytic curved-cylinder flow is also retained.

## Steady thermal model

The temperature field solves an averaged plug-flow advection/conduction model:

`-k_parallel T_xx - k_radial (T_yy + T_zz) + (mdot cp / A) T_x + (4h/D)(T - T_ambient) = 0`.

The inlet temperature is fixed and the remaining faces have natural zero diffusive flux. The volumetric sink represents the distributed external heat loss of an equivalent well-mixed cartridge cross-section. It does not resolve radial wall cooling or gas/solid temperature differences.

Reference entered values are `cp = 1100 J/(kg K)`, `h = 20 W/(m² K)`, `k_radial = 0.5 W/(m K)`, inlet 723.15 K and ambient 293.15 K. High Peclet-number advection is stabilized with axial upwind diffusion: `k_parallel = k_radial + (mdot cp / A) mesh_size/2`. This numerical diffusion is explicit, not a material property. Each case is compared both to the exact stabilized one-dimensional boundary-value solution and to the physical zero-diffusion plug-flow limit `T_out - Ta = (T_in - Ta) exp(-h pi D L/(mdot cp))`.

The exported `thermal_factor` is the NTU inferred from the stabilized temperature field divided by the physical plug-flow NTU. It is a **diagnostic of numerical diffusion at the recorded reference condition**. It should not be used as a fitted material coefficient for an arbitrary transient engine duty cycle. The planner's transient thermal calculation remains a separately labeled reduced model.

## Numerical gates and provenance

- Pressure loss, pressure-profile relative L2 error, velocity-profile relative L2 error, and flux error against the imposed finite-element inlet flux: less than 0.5% each.
- Analytic cylinder inlet-area and volume relative errors: less than 0.5% each.
- Mean outlet temperature error against the stabilized exact solution: less than 0.5 K.
- Mean outlet excess-temperature error relative to the physical plug-flow limit: less than 0.5%; temperature must remain between ambient and inlet.
- Central 10-to-7 mm refinement: pressure-loss change below 0.5%, mean outlet temperature change below 0.5 K, diagnostic thermal-factor absolute change below 0.02.

`runs/dpf_cloud_manifest.json` records verified cases, original Allsolve project/mesh/simulation job identities, source-file SHA-256 hashes, solver/SDK identity, independent-job concurrency evidence, and central refinement evidence. Case files preserve sampled pressure, temperature, and Darcy velocity fields, direct finite-element integrals, custom weak forms, and solver logs. `ready` requires all nine geometry validations plus the central mesh comparison. Numerical validation establishes the solution of these entered equations; real hardware optimization needs measured pressure-loss, heat-transfer, soot-loading and capture characteristics.

## Official API references

- [Allsolve SDK parameter studies and parallel simulations](https://allsolve.quanscient.com/documentation/reference/public-api-introduction)
- [Heat fluid advection/diffusion equations](https://allsolve.quanscient.com/documentation/using-allsolve/physics/heat-fluid)
- [Heat solid and convective heat transfer](https://allsolve.quanscient.com/documentation/using-allsolve/physics/heat-solid)
- [Expression reference, volume trace `on` and surface flux integrals](https://allsolve.quanscient.com/documentation/reference/expressions)

The SDK used is 0.5.2. The observed solver banner is `Quanscient Allsolve 484 int64/float64`.

A finer 5 mm attempt (`dpf_d160_l200_fine`) produced 812,838 degrees of freedom and exceeded the one-rank direct-solver memory allocation: the factorization requested 17.169 GB with 16.47 GB physical RAM available. The failed cloud job and log are retained. The 7 mm refinement uses the same bounded hardware class.
