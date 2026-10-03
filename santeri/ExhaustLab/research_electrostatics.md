# Electrostatic API and field export research

Checked 2026-10-03 against installed `allsolve 0.5.2` in the root `.venv`. This was read-only research: no project or cloud job was created. A successful solver run remains necessary to verify the complete path.

## Verified setup API

The expression tokens are case-sensitive: electrostatic potential **`v`**, electric field **`E`**, flow velocity **`V`**, flow pressure **`p`**. [Official expressions table](https://allsolve.quanscient.com/documentation/reference/expressions).

After geometry, regions and mesh setup, use separate physics sets for the uncoupled electrostatic and laminar-flow solves. On the gas volume:

```python
project.create_material(
    name="Pilot gas",
    target_region=gas,
    density="1.2",
    dynamic_viscosity="1.85e-5",
    electric_permittivity="epsilon0",
)
es_set = project.create_physics_set(name="Electrostatics")
es = es_set.add_physics(allsolve.Physics.Electrostatics(target=gas))
es.set_field_interpolation_order(1)
es.save()
es.add_interactions([
    allsolve.Interaction.ElectrostaticsConstraint(
        name="Ground plate", electrostatics_constraint="0", target=ground,
    ),
    allsolve.Interaction.ElectrostaticsConstraint(
        name="Driven plate", electrostatics_constraint="voltage", target=driven,
    ),
])
sim = project.create_simulation_static(
    name="Uniform electrostatic benchmark",
    description="No space charge; imposed plate voltage in dilute gas",
    max_run_time_minutes=10,
    mesh=mesh,
    physics_set=es_set,
    solver_mode=allsolve.SolverMode.DIRECT,
)
sim.add_outputs([
    allsolve.Output.FieldOutput(name="Potential", expression="v", target=gas),
    allsolve.Output.FieldOutput(name="Electric field", expression="E", target=gas),
    allsolve.Output.ValueOutput(
        name="Midpoint Ey",
        expression="interpolate(reg.gas, compy(E), [L/2,g/2,h/2])",
    ),
])
```

Here `gas` is a VOLUME region; `ground` and `driven` are SURFACE regions. `voltage`, `L`, `g`, `h` must be defined project variables. The gas properties above describe a provisional cool-air pilot, not arbitrary hot exhaust.

The official [electrostatics page](https://allsolve.quanscient.com/documentation/using-allsolve/physics/v-formulation-electrostatics) documents potential constraints, E = -grad(v), and static analysis support. Unconstrained faces use the natural zero-normal-flux condition in the weak formulation; verify this inference against the uniform-field benchmark.

## Boundary selection

For a box spanning `[0,L] x [0,g] x [0,h]`, explicitly use `CadAlignment.CORNER`. Select the gas by volume name or full bounding box. Compute its boundary:

```python
boundary = project.create_region_computed(
    name="gas_boundary", entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.BOUNDARY, source_regions=[gas],
)
plate_all = project.create_region_rule(
    name="ground_all", entity_type=allsolve.Region.SURFACE,
    bounding_box=((-eps, -eps, -eps), (L+eps, eps, h+eps)),
)
ground = project.create_region_computed(
    name="ground", entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.INTERSECTION,
    source_regions=[plate_all, boundary],
)
```

Use the analogous thin bounding box around `y=g` for the driven plate. `eps` should be a small coordinate tolerance, for example `1e-7 m`. Refresh `project.get_regions()` after constructing regions and inspect each region's `entity_tags`; do not assume entity IDs. For one box expect one volume and one face per plate. Confirm the selected plates are disjoint and subsets of the gas boundary. Subtract inlet/outlet and electrode surfaces from wall sets when preparing flow BCs. New baffle geometry requires repeating these checks.

## Uniform field acceptance check

With `v(y=0)=0`, `v(y=g)=U`, the analytic solution is `v=U*y/g` and `E=(0,-U/g,0)`. For `U=1000 V`, `g=0.01 m`, expect `Ey=-100000 V/m`. Check midpoint and multiple interior points, potential extrema, transverse components, and the sign of force `qE`. Check both field export arrays and direct scalar interpolation outputs. A positive charge moves toward ground in this convention.

## Export API and local mesh

Run mesh and simulation with `OnError.STRICT` and proceed only on success. The destination folder must already exist:

```python
out = Path("results/electrostatics")
out.mkdir(parents=True, exist_ok=True)
data = sim.get_output_data(refresh=True)
for output_name in ("Potential", "Electric field"):
    names = data.get_filenames_for_output_field(output_name, 0, None)
    sim.save_output_field(output_name, output_dir=str(out), refresh=False)
    # Persist names in the run manifest rather than guessing suffixes.
```

`step_index=None` is appropriate for a static solve. For transient output select an explicit step index. Use a different export directory per sweep point because filenames may repeat.

Although the skill describes VTU outputs, the installed SDK also downloads `.hdf` files, detects zstd magic, and decompresses them to HDF5 in place. The actual format and field-array names must be inspected after a real run. `save_output_field` downloads every rank file referenced by the output definition. `save_output_mesh(name, ...)` exists, but a volume FieldOutput ordinarily contains its own geometry and topology; do not assume a mesh output exists under the field's name.

For VTKHDF UnstructuredGrid, inspect `VTKHDF` attributes and datasets `Points`, `Connectivity`, `Offsets`, `Types`, `NumberOfPoints`, `NumberOfCells`, `NumberOfConnectivityIds`, `PointData`, and `CellData`. Preserve rank/partition offsets. [Official VTKHDF specification](https://docs.vtk.org/en/v9.6.0/vtk_file_formats/vtkhdf_file_format/vtkhdf_specifications.html).

Prefer VTK's `vtkHDFReader` for loading and `vtkStaticCellLocator` for point location/interpolation. A lighter `h5py` reader must explicitly support the encountered cell type, point/cell association, partitioning, and high-order elements. Do not remesh the exported point cloud with unconstrained Delaunay interpolation: that can bridge baffles or fill holes. Skin-only export is unsuitable for volume particle trajectories; leave `field_output_skin_only=False`.

## Remaining limitations

- No successful 3D electrostatic job or result export was performed in this research.
- `numpy`, `scipy`, `h5py`, `vtk`, `pyvista`, and `meshio` were absent from the shared root `.venv` when checked. Local postprocessing needs suitable dependencies in this case's environment.
- No turnkey particle tracer, corona/charging model, soot chemistry, or emission certification path was verified. Trace particles locally only from validated Allsolve fields and retain clear provenance.
- Ignoring space charge and electrical feedback on gas flow is conditional on a dilute, precharged pilot aerosol. Static electrostatics does not solve current consumption or corona power. A cost/power model requires an entered supply efficiency/leakage assumption or separate current-flow physics.
- The official examples directory lists a `lumped_pull_in_analysis` example, but individual example source retrieval failed in the web tool. Installed generated SDK classes and official API/expression documentation supplied the verified signatures.

## Solver-side sampled arrays as an export alternative

Read-only inspection of installed `quanscient-stubs/__init__.pyi:9346` verifies:

```python
qs.allinterpolate(physreg: int, expr: expressionlike,
                  xyzcoords: Sequence[float]) -> list[float]
```

The global helper accepts a **flat sequence of multiple xyz triples**, returns one value per input point for a scalar expression, and errors if a point cannot be located. Sample vector components separately. At line 15469, `qs.setoutputvalue(name, value, step=None, specifier=None)` accepts both a float and a sequence of floats, so a whole grid fits in a single output array.

`CustomSection.AFTER_ALL` runs after static solution and normal outputs. A custom script can sample the actual FE field without an HDF reader. The following assumes the generated names have been checked with `sim.save_generated_scripts(...)`; the official expression tokens imply `fld.v` (potential), `fld.V` (velocity), `fld.p` (pressure), while actual server-generated namespaces remain the authority. The available generated thermal/acoustic example confirms `utils.Fields` holds primary symbols; no local electrostatic generated script existed during research. `-qs.grad(fld.v)` avoids uncertainty about whether the derived E field lives in `df.E`.

```python
# Inline AFTER_ALL script, using locally baked numeric extents.
# Change L/g/h and grid counts to the current geometry.
L, g, h = 0.2, 0.01, 0.02
nx, ny, nz = 25, 17, 9
xs = [L * i/(nx-1) for i in range(nx)]
ys = [g * j/(ny-1) for j in range(ny)]
zs = [h * k/(nz-1) for k in range(nz)]
coords = [c for x in xs for y in ys for z in zs for c in (x,y,z)]
count = nx*ny*nz
efield = -qs.grad(fld.v)
for label, component in (("sample_Ex", qs.compx(efield)),
                         ("sample_Ey", qs.compy(efield)),
                         ("sample_Ez", qs.compz(efield)),
                         ("sample_potential", fld.v)):
    values = qs.allinterpolate(reg.gas, component, coords)
    if len(values) != count:
        raise RuntimeError(label + " grid length mismatch")
    qs.setoutputvalue(label, values)
qs.setoutputvalue("sample_x", [coords[i] for i in range(0,len(coords),3)])
qs.setoutputvalue("sample_y", [coords[i] for i in range(1,len(coords),3)])
qs.setoutputvalue("sample_z", [coords[i] for i in range(2,len(coords),3)])
qs.setoutputvalue("sample_shape", [nx,ny,nz])
```

Grid order is x outermost, y next, z fastest, compatible with NumPy `reshape((nx,ny,nz))`. Use the same grid for flow components via `qs.compx(fld.V)` and pressure `fld.p` in the flow simulation. A rectangular box admits endpoint-inclusive coordinates, subject to verifying boundary interpolation. A baffled gas domain contains excluded solid points; the global helper must not receive those points. Either mask known geometry or call expression-method `expr.allinterpolate(reg.gas, [x,y,z])` pointwise and record missing values. That method's separate stub documents an empty list for a point that cannot be found. Do not extrapolate sampled fields through solids.

Sampled grids add an interpolation approximation beyond FE error. Before tracing particles, compare 25x17x9 and a refined sampling grid, use a separate timestep convergence check, verify analytic zero-force/constant-drift trajectories, and confirm capture changes are small. Keep the original Allsolve field exports as evidence when practical.
