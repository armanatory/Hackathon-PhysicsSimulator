# Laminar-flow SDK research

Read-only research, 2026-10-03. No geometry/mesh/solve jobs were created by this research. Installed `allsolve` version: 0.5.2. Read `AGENTS.md` and the local SDK, geometry, regions, physics/interactions, materials, mesh, simulation, and custom-script skills.

## Confirmed solver path

Official [laminar-flow docs](https://allsolve.quanscient.com/documentation/using-allsolve/physics/laminar-flow) describe incompressible Navier–Stokes with density and dynamic viscosity. Official [CHT tutorial](https://allsolve.quanscient.com/documentation/tutorials/heat-transfer/cht-001-manifold-microchannel-heat-sink) uses inlet velocity, zero outlet pressure, no-slip walls, static analysis/direct solve, pressure expression `p`, velocity expression `V`.

```python
flow = physics_set.add_physics(allsolve.Physics.LaminarFlow(target=fluid))
project.create_material(name="Pilot gas", target_region=fluid,
                        density="rho", dynamic_viscosity="mu")
flow.add_interactions([
    allsolve.Interaction.LaminarFlowVelocityConstraint(
        name="Inlet", target=inlet,
        laminar_flow_velocity_constraint=[[1, "u_in"], [1, 0], [1, 0]]),
    allsolve.Interaction.LaminarFlowPressureConstraint(
        name="Outlet", target=outlet, laminar_flow_pressure_constraint=0),
    allsolve.Interaction.LaminarFlowVelocityConstraint(
        name="No slip", target=walls,
        laminar_flow_velocity_constraint=[[1, 0], [1, 0], [1, 0]]),
])
velocity_id = flow.fields.velocity.id
pressure_id = flow.fields.pressure.id
flow.set_field_interpolation_order(2, field_id=velocity_id)
flow.save()
flow.set_field_interpolation_order(1, field_id=pressure_id)
flow.save()
# Physic.save() drops field-definition metadata from the local object in 0.5.2.
# Re-fetch if further field-name access is needed:
flow = next(p for p in project.get_physics() if p.id == flow.id)
```

The SDK constraint is **3x2**, with activation flag in column 1 and value in column 2, despite the GUI tutorial displaying a 3x1 vector. Typed solver stubs document velocity order 2 / pressure order 1 as satisfying the LBB condition. Save after **each** interpolation-order setter: in 0.5.2 the setter builds from committed fields and two consecutive setters before one save can discard the first order change.

**Observed setup failure, 2026-10-03:** after `flow.save()`, `flow.fields` raises `ValueError: Physics field has no definition`. `Physic.save()` reconstructs its cached `_physics` using update fields, which carry IDs and interpolation orders but no definition metadata; this is a local object-cache bug. Cache both field IDs before saving, and re-fetch physics through the public project API after the updates if name-based field access is needed. The serialization omits unset definitions rather than explicitly transmitting null, so the source does not imply lost server-side definitions.

Electrostatics and flow both commonly display `V`; use distinct physics sets and simulations and inspect generated scripts for precise field names before attaching custom code. `save_generated_scripts()` saves helpers, not the main simulation code; use raw `get_generated_scripts()` when the main script must be inspected.

## Rectangular channel without CAD ambiguity

Use flow in +x, width y, plate gap z. One fluid box with `alignment=allsolve.CadAlignment.CORNER`, `position=(0,-W/2,0)`, `size=(L,W,H)`. No solid plate bodies are needed for the first fluid benchmark: plate surfaces are no-slip fluid boundaries. This avoids duplicated/sliver interfaces.

Selected root-agent envelope: L=0.06 m, span W=0.02 m, gap h=0.004/0.006/0.008 m, volume flow Q=0.2 L/min = 3.333333333e-6 m³/s, rho=1.20 kg/m³, mu=1.81e-5 Pa·s, fixed ambient properties. Gap is **y**, span is **z** in this selected geometry; interchange y/z in the initial pattern above. This is a cooled/dilute pilot side-stream assumption, not hot full exhaust. Hydraulic diameter `2*W*h/(W+h)` and Reynolds number `rho*(Q/(W*h))*Dh/mu` should be recorded explicitly.

Region rule names: `fluid` (VOLUME, name attribute or box bounds), `inlet` (SURFACE, narrow x slab around 0), `outlet` (SURFACE, narrow x slab around L), `boundary` (computed BOUNDARY of fluid), `ports` (computed UNION inlet/outlet), `walls` (computed DIFFERENCE boundary minus ports). Use slab tolerance near 1e-7 m rather than exactly zero thickness. Expected entity counts for one box: fluid 1, inlet 1, outlet 1, walls 4. Refresh regions after geometry and reject empty or unintended selections before meshing. These selectors remain stable under gap/length overrides when bounds use project-variable expressions.

Start with mesh max size about H/3 or H/4 for feasibility, then tighten cross-gap resolution for numerical evidence. This is only an initial size estimate; compare pressure drop and velocity profiles at a finer size before calling the benchmark verified.

## Exact developed-flow benchmark

For W >= H, y in [-W/2,W/2], z in [0,H], constant axial pressure gradient G=-dp/dx>0:

`u(y,z)=4*G*H²/(mu*pi³) * sum_odd_n (1-cosh(n*pi*y/H)/cosh(n*pi*W/(2*H))) * sin(n*pi*z/H) / n³`

`C=1-192*H/(pi⁵*W)*sum_odd_n tanh(n*pi*W/(2*H))/n⁵`

`Umean=G*H²*C/(12*mu)`; therefore `G=12*mu*Umean/(H²*C)`, `Q=Umean*W*H`, `delta_p=G*L`.

Use a truncated developed inlet profile for the benchmark (e.g. 20 odd terms), comparing truncations locally first. That profile meets all four no-slip walls and avoids conflating inlet development with duct friction. A uniform inlet is valid for a pilot run but its total pressure drop contains the entrance penalty; compare the developed downstream pressure slope rather than expecting total `delta_p=G*L` exactly. The formula follows the Poisson momentum balance `mu*(u_yy+u_zz)=-G`, zero wall values, and Fourier expansion of a constant; numerical quadrature of the series provides an independent implementation check.

Useful planned acceptance gates: inlet/outlet volume-flow mismatch <1%; pressure-drop agreement within a stated tolerance (initially 5%); velocity-profile relative L2 error within a stated tolerance (initially 5%); both improve/stabilize with mesh refinement. These are proposed engineering gates, not achieved results.

For the selected geometry y in [0,h], z in [0,W], replace the cosh bracket by the stable equivalent:

`1-(exp(n*pi*(z-W)/h)+exp(-n*pi*z/h))/(1+exp(-n*pi*W/h))`.

Every exponent is nonpositive inside the duct. For a finite N-term profile, normalize to the intended volume flow using `C_N=(96/pi^4)*sum_odd_to_(2N-1)(1/n^4-2*h/(pi*W)*tanh(n*pi*W/(2*h))/n^5)` and `G=12*mu*Q/(W*h^3*C_N)`. At N=15, C_N differs from the converged coefficient by about 6e-6 absolute.

| Gap | Mean speed (m/s) | Re | Developed pressure drop (Pa) |
| --- | ---: | ---: | ---: |
| 4 mm | 0.0416667 | 18.4162 | 0.0388323 |
| 6 mm | 0.0277778 | 16.9996 | 0.01239994 |
| 8 mm | 0.0208333 | 15.7853 | 0.00567065 |

These small pressure differences require an adequately tight solve tolerance. Normalize comparison error by the analytical pressure difference, not atmospheric pressure.

## Field and scalar exports

```python
sim.add_outputs([
    allsolve.Output.FieldOutput(name="Pressure", expression="p", target=fluid),
    allsolve.Output.FieldOutput(name="Velocity", expression="V", target=fluid),
])
# after Job.SUCCESS, with output folder already created:
sim.save_output_field(name="Pressure", output_dir=str(result_dir), refresh=True)
sim.save_output_field(name="Velocity", output_dir=str(result_dir))
```

Installed 0.5.2 downloads VTKHDF `.hdf` when the backend supplies it and **automatically decompresses zstd in place**, unlike older skill wording. Read actual file names/format; do not assume VTU. Separate output folders per mesh/sweep prevent overwrite. `sim.get_output_data().to_csv_file()` refuses to overwrite existing CSV.

To avoid a known generated-code collision among multiple `average`/`integrate` ValueOutputs, put scalar reporting in custom `AFTER_ALL` code using `qs.setoutputvalue`. Exact field namespace names must come from the generated main script. Solver API supports scalar/vector `qs.expression(field).interpolate(reg.fluid,[x,y,z])` and returns flattened values or `[]` outside the region. `.allinterpolate` is the collective multi-node variant. This can export a regular sampling grid CSV for local tracing if native field readers are inconvenient. All custom code runs remotely only; syntax checking locally does not verify solver semantics.

For +x axis use the simple signed flow integral `compx(V).integrate(reg.inlet,4)` and the equivalent outlet integral; using component integrals removes normal-orientation ambiguity. Use `p.integrate(reg.inlet,4)/area_in-p.integrate(reg.outlet,4)/area_out` for mean pressure drop. Report hydraulic power `delta_p*Q`; this omits blower efficiency and electrostatic supply power.

## Primary evidence

- `.venv/Lib/site-packages/allsolve/physics/generated/interactions.py`: `LaminarFlowVelocityConstraint`, `LaminarFlowPressureConstraint`.
- `.venv/Lib/site-packages/allsolve/physics/generated/physics.py`: LaminarFlow fields `pressure`, `velocity`.
- `.venv/Lib/site-packages/allsolve/physics/physic.py`: field-ID order setters and save behavior.
- `.venv/Lib/site-packages/allsolve/simulation/simulation.py`: `save_output_field`, auto HDF decompression, arbitrary-file download.
- `.venv/Lib/site-packages/quanscient-stubs/__init__.pyi`: `predefinednavierstokes`, `interpolate`, `allinterpolate`.

No turnkey particle-tracing workflow was found in these focused SDK surfaces. The task's local trajectory fallback remains necessary unless further official evidence appears.

## Verified follow-up

The root implementation completed genuine field solves for all three gaps. The autogenerated Navier–Stokes and a predefined-Stokes attempt did not meet continuity/profile checks despite native successful job status; their underlying failure remains undiagnosed. An explicit stationary incompressible weak form in `cloud_study.py` passed the channel benchmark. This is justified for the developed straight-channel fixture because the advective term is zero; it does not extend automatically to baffles or developing/turbulent flow.

`validate_fields.py` checks the point exports, optional direct finite-element boundary integrals, and immutable source hashes. The 6/8 mm cases and the independent fine 6 mm case passed all numerical gates. A separate 1.5 mm versus 1.0 mm mesh comparison passed, with 0.00350% fitted-pressure change and 0.0783% common-grid velocity L2 change. See `runs/convergence_fields.json` and `sdk_flow_feedback.md` for evidence and scope. None of this validates particle charging or measured emission reduction.
