---
name: allsolve-geometry
description: >-
  Build Allsolve CAD geometry for multiphysics simulations: primitives, booleans,
  transforms, file imports, alignment. Use when creating geometry_builder,
  add_cylinder, add_box, add_sphere, add_union, add_difference, CadAlignment,
  build, or fixing PLC / segment-facet intersection errors.
---

# Allsolve geometry

## Geometry builder

```python
builder = project.geometry_builder()

builder.add_box(name="part", position=(0, 0, 0), size=("L", "W", "H"))
builder.add_cylinder(
    name="rod",
    position=(0, 0, 0),
    axis=(0, 0, "H"),
    radius="R",
    inner_radius="R_inner",  # optional — hollow cylinder / shell
    alignment=allsolve.CadAlignment.BASE,
)
builder.add_difference(
    name="shell",
    cad_names_1=["outer"],
    cad_names_2=["inner"],
    delete_tool=False,
)
builder.build(print_logs=True, on_error=allsolve.OnError.RAISE)
```

## Methods by category

| Category   | Methods                                                                                                                |
| ---------- | ---------------------------------------------------------------------------------------------------------------------- |
| Primitives | `add_box`, `add_cylinder`, `add_sphere`, `add_cone`, `add_torus`, `add_disk`, `add_rectangle`, `add_surface_rectangle` |
| Booleans   | `add_union`, `add_difference`, `add_intersection`, `add_fragments`, `add_fragment_all`                                 |
| Transforms | `add_translate`, `add_rotate`, `add_grid`, `add_remove`                                                                |
| Import     | `add_step_file`, `add_iges_file`, `add_brep_file`, `add_sat_file`, `add_msh_file`, `add_nas_file`, `add_gds2_file`     |

Shared helpers: `CadAlignment`, `CadPath`, `CadGlob`.

Import types: `CadStepFile`, `CadIgesFile`, `CadMshFile`, etc.

## Conditional geometry for sweeps

Use `enabled` to activate geometry parts only when a sweep variable matches:

```python
gb = project.geometry_builder()
for i, step_path in enumerate(step_files):
    gb.add_step_file(filepath=str(step_path), name=f"sample_{i}",
                     enabled=f"eq(sample_idx, {i})")
gb.build(print_logs=True, on_error=allsolve.OnError.RAISE)
```

The `enabled` expression uses `eq(var, value)` — **not** `==`. Combine with `create_variable_overrides` to sweep over different geometries (see `allsolve-variables-and-overrides`).

## Alignment

| Enum                  | Primitives        | Meaning                                              |
| --------------------- | ----------------- | ---------------------------------------------------- |
| `CadAlignment.CENTER` | All (default)     | Bounding-box center at `position`                    |
| `CadAlignment.CORNER` | Box, rectangle    | Smallest XYZ corner at `position`                    |
| `CadAlignment.BASE`   | Cylinder, cone    | Bottom center at `position` (radial geometries)      |

## Resource reservations

`build()`, `run()`, and `start()` accept `resource_reservation=` (v0.5.0+):

```python
with client.resource_reservation(node_type=allsolve.CPU.CORES_4_64GB) as reservation:
    builder.build(print_logs=True, on_error=allsolve.OnError.RAISE, resource_reservation=reservation)
```

See `allsolve-simulation` for the full resource reservation API.

## Gotchas

- **All geometry dimensions in SI (metres):** 50 mm = 0.05 m.
- **`alignment` defaults to `CadAlignment.CENTER`** — `position` is the bounding-box center, so box/rectangle span `[position - size/2, position + size/2]`. For `[0,W]×[0,H]`, use `position=(W/2, H/2)` or `alignment=CadAlignment.CORNER, position=(0, 0)` (smallest corner at `position`). Cylinder/cone: `CadAlignment.BASE` pins bottom center at `position`. Wrong alignment silently shifts the domain.
- **STEP import: no `scale_factor` needed.** Allsolve handles mm-to-m conversion internally. Setting `scale_factor=0.001` causes double-conversion and hangs the mesher.
- **`geometry_no_implicit_fragment=True` breaks acoustic-elastic coupling** — coupling requires shared curves between domains. Only disable implicit fragmentation when no inter-domain coupling is needed.
- **Boolean cut + separate add = orphaned surfaces.** If you create a solid independently and also `box.cut(track)`, adding both produces duplicated interface surfaces that the V2 pipeline cannot close.
- **Shared subshape names are LOST during `fragmentall`** — a face/edge name shared between two solids does not survive. Select shared port entities by bounding box instead. Unshared names do survive.
- **(EM/RF)** Model conductors as THIN SOLIDS, not zero-thickness sheets — zero-thickness PEC sheets produce sliver/low-quality tets and the mesher rejects with `lowQualityData`.
- **(EM/RF)** Axis-aligned via/feed boxes fused onto CURVED trace ends make sliver tets — give the trace a straight radial lead stub so the via/pad shares an aligned face.
- **(External CAD)** CadQuery coordinates in mm, Allsolve in metres — no `scale_factor` needed on STEP import. Use `lineTo` (not `spline`) to ensure adjacent layers share exact interface vertices after STEP export and `fragmentall`.
- **(Curved geometry)** Arc-length resampling for spirals — a uniform-in-theta Archimedean spiral gives uneven edge lengths. Resample the centreline by arc length for mesh-friendly geometry.

## Pitfalls

| Error                                    | Cause                             | Fix                                                                 |
| ---------------------------------------- | --------------------------------- | ------------------------------------------------------------------- |
| `PLC Error: segment and facet intersect` | Overlapping solid volumes         | Remove overlap; inset one body; use hollow shell + fill             |
| Thin feature mesh OOM                    | Mesh refined below real thickness | Use coarser `scale_factor`; avoid sub-mm refinement unless required |
| `no elements in volume`                  | Bad geometry after boolean        | Rebuild; check `build(print_logs=True)`                             |
