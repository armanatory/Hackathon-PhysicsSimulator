---
name: allsolve-mesh
description: >-
  Create and tune Allsolve meshes: MeshSettings, refinements, scale factor,
  node types, failure recovery. Use when creating create_mesh, MeshSettings,
  MeshRefinement, scale_factor, curvature_enhancement, mesh OOM, mesh failure,
  or setting mesh node_type / CPU size.
disable-model-invocation: true
---

# Allsolve mesh

## Mesh creation

```python
mesh = project.create_mesh(
    allsolve.MeshSettings(
        name="Default mesh",
        scale_factor=1.0,           # >1 = coarser, <1 = finer globally
        curvature_enhancement=4.0,
        max_run_time_minutes=15,
        refinements=[
            allsolve.MeshRefinement(
                region=regions.fine_feature,
                max_size="feature_height / 10",
            ),
        ],
    )
)
```

`scale_factor` is the main tuning knob for mesh density — it scales all element sizes uniformly, including regions with explicit `MeshRefinement`.

**Start coarse, refine later.** For new 3D problems, begin with a larger `scale_factor` (e.g. `1.5`–`2.0`) and a larger node type (e.g. `CORES_4_64GB`). Verify the simulation runs to completion before tightening the mesh. This avoids wasted time on OOM failures during setup iteration.

For direct size control instead of relative scaling, use `mesh_size_min` and `mesh_size_max`:

```python
allsolve.MeshSettings(
    name="Sized mesh",
    mesh_size_min=0.000002,
    mesh_size_max=0.004,
    max_run_time_minutes=10,
    refinements=[
        allsolve.MeshRefinement(region=regions.small_part, max_size=0.0002),
    ],
)
```

Alternatively (v0.5.0+), use `min_size_factor` / `max_size_factor` for factor-based size control (mutually exclusive with `mesh_size_min`/`mesh_size_max`).

Refine **bulk domains** (fluid, large solids), not ultra-thin shells, unless the study requires it.

## Instance size (node type)

Cloud jobs run on compute nodes with fixed RAM. Default is small/fast-start (`lambda`, 3 cores / 10 GB). If meshing logs show **out of memory** or the job is killed, move to a larger node type before coarsening the mesh.

Node types (`allsolve.CPU`):

| Node type                 | Cores | RAM             |
| ------------------------- | ----- | --------------- |
| `CORES_3_10GB_FAST_START` | 3     | 10 GB (default) |
| `CORES_1_16GB`            | 1     | 16 GB           |
| `CORES_2_32GB`            | 2     | 32 GB           |
| `CORES_4_64GB`            | 4     | 64 GB           |
| `CORES_8_128GB`           | 8     | 128 GB          |
| `CORES_16_256GB`          | 16    | 256 GB          |
| `CORES_32_512GB`          | 32    | 512 GB          |

Set at creation or on the mesh object:

```python
mesh = project.create_mesh(
    allsolve.MeshSettings(
        name="Default mesh",
        node_type=allsolve.CPU.CORES_4_64GB.value,
        scale_factor=1.0,
        max_run_time_minutes=15,
    )
)

# Or after creation:
mesh.node_type = allsolve.CPU.CORES_4_64GB.value
mesh.save()
```

Larger nodes cost more and may have queue time — try the smallest size that fits.

## Running the mesh

```python
mesh.run(print_logs=True, on_error=allsolve.OnError.STRICT)
```

Always mesh before simulate. See `allsolve-simulation` for the full run pattern and `on_error` modes.

## Mesh status

Check mesh job status after run:

```python
mesh.get_status()          # Job.SUCCESS, Job.PARTIAL_SUCCESS, etc.
mesh.get_status_reason()   # human-readable reason on failure
```

For variable-override sweeps, use `MeshInstance` (v0.5.0+):

```python
instance = mesh.get_override(variable_overrides)
instance.get_sweep_status(sweep_index=0)   # per-step job status
instance.get_sweep_count()                 # number of sweep steps
```

Detailed mesh element metrics (node/element counts, quality) are visible in the Allsolve web UI.

## Resource reservations

Mesh `run()` and `start()` accept `resource_reservation=` to use reserved compute:

```python
with client.resource_reservation(node_type=allsolve.CPU.CORES_4_64GB) as reservation:
    mesh.run(print_logs=True, on_error=allsolve.OnError.STRICT, resource_reservation=reservation)
    sim.run(print_logs=True, on_error=allsolve.OnError.STRICT, resource_reservation=reservation)
```

See `allsolve-simulation` for the full resource reservation API.

## Failure guide

| Symptom                                                | Likely cause                 | Action                                                                                               |
| ------------------------------------------------------ | ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| `ran out of memory` / refiner killed                   | Mesh too large for node RAM  | **First:** increase node type. **Then:** increase `scale_factor`; remove aggressive `MeshRefinement` |
| `PARTIAL_SUCCESS` / status reason `lowQualityData`     | Low-quality elements in mesh | Inspect element quality in web UI; increase `scale_factor` or relax refinements                      |
| `PLC Error: segment and facet intersect`               | Invalid/overlapping geometry | Fix geometry (see `allsolve-geometry`)                                                               |
| `no elements in volume`                                | Bad geometry after boolean   | Rebuild; check `build(print_logs=True)`                                                              |
| `Invalid regions in mesh parameters: zero entity tags` | Region rule matches nothing  | Fix region selectors before meshing (see `allsolve-regions`)                                         |

## Gotchas

### Sizing

- **Two independent knobs control DOF** — getting them wrong turns a 0.5 MDoF job into a 6 MDoF one: (1) `mesh_size_max` — global element size for large bodies (keep coarse); (2) `MeshRefinement(region, max_size)` — per-region override for small features. Over-refining a swept region balloons DOF on the thick variants.
- **`scale_factor` scales everything uniformly** — including regions with explicit `MeshRefinement`. For targeted sizing, use `MeshRefinement(region, max_size)` with a coarse global `mesh_size_max`.
- **Making the global size fine to resolve a thin feature explodes large bodies.** Keep the global coarse and refine only the small features.
- **Element size for thin features ≈ thickness / 2.5** — ensures at least 2 elements through the feature with quadratic order. Bulk/stiff bodies ≈ body size / 7.
- **(Wave physics)** Wavelength / 6 rule of thumb — global mesh size should be approximately `min_wavelength / 6`. Do NOT apply per-region refinements to match thin geometric features unless specifically needed. See `allsolve-domain-rf` and `allsolve-domain-acoustics` for domain-specific mesh strategies.
- **(Wave physics)** For wave-propagation devices, consider setting `use_mesh_refiner=False` if the auto-refiner over-resolves thin layers. Density should be driven by wavelength, not geometric features. Test with and without to compare DOF counts.
- **Always sanity-check base-mesh DOF on one point before launching a sweep of 100.** Use the coarsest refinement that still meshes the smallest geometry in the sweep.

### DOF and solver scaling

- **2nd-order elements** give scalar DOF ≈ 6–7× the vertex count. A coupled thermal+structural solve ≈ 4× the scalar DOF.
- **DIRECT solver memory grows fast; caps around ~1M DOF** on a modest node. For larger problems use ITERATIVE DDM and/or multiple instances with a bigger node.
- **Coupled nonlinear problems can be ill-conditioned for ITERATIVE** — DIRECT on a large-memory node is often more robust up to a few M DOF.
- **Set mesh node large enough** — thick/fine geometries can OOM a small mesh node; use `CORES_4_64GB`+ for meshing big assemblies.

### 2D and structured meshing

- **Default 2D meshing is UNSTRUCTURED TRIANGLES** (consistent mass). For structured quads needed in dispersion-matched coupling, use `AutoTransfiniteGroup` in `MeshSettings(auto_transfinite=...)` or set transfinite counts explicitly. Opposite edges must get matching segment counts.
- **`import_msh` of gmsh quads is re-triangulated** — do NOT `create_mesh` after import; use `project.get_meshes()[0]`.

### Other

- **`CORES_3_10GB_FAST_START`** (`"lambda"`) — use for lightweight meshes and tiny sims to avoid queue wait.
- **`mesh.save_mesh_file(output_dir, filename)` does NOT overwrite** existing files — always `os.remove(path)` before saving, or use unique filenames.
- **The hard floor on coarseness** is meshability of the smallest feature: an element must be smaller than the thinnest member's diameter. If the thin end fails, narrow the swept range rather than globally over-refining.
