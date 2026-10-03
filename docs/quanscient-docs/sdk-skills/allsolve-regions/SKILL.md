---
name: allsolve-regions
description: >-
  Create Allsolve regions for targeting materials, physics, and mesh refinements:
  region rules, computed regions, basic regions. Use when creating
  create_region_rule, create_region_computed, create_region_basic, bounding_box,
  min_size, max_size, RegionOperation, BOUNDARY, attribute_path, STEP product
  names, build123d, or fixing zero entity tags.
disable-model-invocation: true
---

# Allsolve regions

## Region types

| Method | Use when |
|--------|----------|
| `create_region_rule` | Select entities by bounding box, `min_size`, `max_size`, or `attribute_path` |
| `create_region_computed` | Boolean ops on regions: `UNION`, `DIFFERENCE`, `INTERSECTION`, `BOUNDARY`, … |
| `create_region_basic` | Explicit `entity_tags` from built geometry |

Entity types: `Region.VOLUME`, `Region.SURFACE`, `Region.CURVE`, `Region.POINT`.

### 2D vs 3D entity type mapping

| Concept | 2D simulation | 3D simulation |
|---------|---------------|---------------|
| Domain body | `Region.SURFACE` | `Region.VOLUME` |
| Boundary | `Region.CURVE` | `Region.SURFACE` |
| Point | `Region.POINT` | `Region.POINT` |

## Basic usage

`bounding_box`, `min_size`, and `max_size` accept plain tuples or typed `ExpressionBoundingBox`/`ExpressionVector` objects:

```python
vol = project.create_region_rule(
    name="solid",
    entity_type=allsolve.Region.VOLUME,
    bounding_box=(
        ("-L/2", "-W/2", "-H/2"),
        ("L/2", "W/2", "H/2"),
    ),
    # Equivalent typed form:
    # bounding_box=allsolve.ExpressionBoundingBox(
    #     min=allsolve.ExpressionVector(x="-L/2", y="-W/2", z="-H/2"),
    #     max=allsolve.ExpressionVector(x="L/2", y="W/2", z="H/2"),
    # ),
)

surface = project.create_region_computed(
    name="outer_surface",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.BOUNDARY,
    source_regions=[vol.id],
)
```

## Selection patterns

**Bulk volume** — bounding box around expected extent:

```python
project.create_region_rule(
    name="large_part",
    entity_type=allsolve.Region.VOLUME,
    bounding_box=((min_x, min_y, min_z), (max_x, max_y, max_z)),
)
```

**Small feature among many** — add `max_size` to filter by characteristic length:

```python
project.create_region_rule(
    name="pins",
    entity_type=allsolve.Region.VOLUME,
    max_size=("pin_radius * 2", "pin_radius * 2", "pin_height"),
)
```

**Large domain only** — `min_size`:

```python
project.create_region_rule(
    name="air",
    entity_type=allsolve.Region.VOLUME,
    min_size=("box_size", "box_size", "box_size"),
)
```

**Thin shell / annulus** — `max_size` on wall thickness often yields **zero entity tags**. Instead use computed difference:

```python
outer = project.create_region_rule(name="outer_vol", ..., bounding_box=full_extent)
inner = project.create_region_rule(name="inner_vol", ..., max_size=inner_dims)
shell = project.create_region_computed(
    name="shell",
    entity_type=allsolve.Region.VOLUME,
    operation=allsolve.RegionOperation.DIFFERENCE,
    source_regions=[outer.id, inner.id],
)
```

**Convection / flux BC surfaces** — `BOUNDARY` on the solid region:

```python
project.create_region_computed(
    name="exposed_surfaces",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.BOUNDARY,
    source_regions=[solid_region.id],
)
```

Union multiple surface regions with `RegionOperation.UNION`.

**Name-based selection** — `attribute_path` selects entities by name tag instead of spatial filters:

```python
project.create_region_rule(
    name="track",
    entity_type=allsolve.Region.VOLUME,
    attribute_path=[("name", "track_part")],
)
```

The key is `"name"` (not `"assembly"`). Works for assembly part names (volumes) and individually tagged faces (surfaces). Filters are AND with `bounding_box` when both are specified.

## Mapping STEP product names with build123d

STEP files from OpenCASCADE are not having self-describing product names. Before creating `attribute_path` region rules, use **build123d** (`pip install build123d`) to analyse the geometry locally:

```python
import math
from build123d import import_step

parts = import_step("model.step")

def describe(shape, indent=0):
    if shape.children:
        for child in shape.children:
            describe(child, indent + 1)
        return
    bb = shape.bounding_box()
    cx, cy = shape.center().X, shape.center().Y
    r = math.sqrt(cx**2 + cy**2)
    angle = math.degrees(math.atan2(cy, cx)) % 360
    print(f"{'  '*indent}{shape.label}  area={shape.area:.1f}  "
          f"r={r:.1f}  angle={angle:.1f}°  edges={len(shape.edges())}")

describe(parts)
```

Use area, centroid radius, angle, edge count, and bounding-box extent to identify each part:

| Property | Distinguishes |
|----------|---------------|
| Area | Annulus vs pocket vs winding (different magnitudes) |
| Centroid radius | Rotor parts (small r) vs stator parts (large r) |
| Centroid angle | Individual windings / air pockets within the same radial band |
| Edge count | Steel bodies (many edges from slot cutouts) vs simple annuli (2 edges) |
| BBox extent | Surrounding air (largest) vs localised features |

For parts that are geometrically similar (e.g. motor windings), angular position determines the physical role.

Build the mapping as named constants in the script, then use `attribute_path=[("name", step_name)]` in `create_region_rule`. **Never guess** which product name maps to which part — adjacent numbers (e.g. `2.2.12` vs `2.2.13`) can be completely different entities.

## Interaction target containment

Interaction targets (e.g. port faces, BC surfaces) must be **subsets of the physics domain boundary**. A bounding-box region rule can pick up surfaces outside the physics domain (e.g. outer air box faces at the same coordinate as a port plane), causing: `Interaction "..." targets tags [...] that are outside its physics target region.`

Fix by intersecting the rule-based region with the domain boundary:

```python
port_all = project.create_region_rule(
    name="port1_all",
    entity_type=allsolve.Region.SURFACE,
    bounding_box=(port_min, port_max),
)
port = project.create_region_computed(
    name="port1",
    entity_type=allsolve.Region.SURFACE,
    operation=allsolve.RegionOperation.INTERSECTION,
    source_regions=[port_all.id, em_boundary.id],
)
```

This guarantees only faces belonging to the physics domain are targeted. See `allsolve-domain-rf` for the full RF port region workflow.

## Gotchas

- **2D projects require `dimension=2`** — `client.create_project()` defaults to `dimension=3`. Without it, the script generator treats all CURVE-based interactions as invalid.
- **POINT regions select CAD vertices, not mesh nodes.** If no CAD vertex exists within the bbox, the region contains zero entities → solver fails with `"physical region number N is not defined"`. For probing at arbitrary coordinates, use `interpolate(reg, expr, [x, y, z])` in the output expression instead.
- **`interpolate()` expression syntax:** `interpolate(region, scalar_expr, [x, y, z])` — the third argument is a square-bracket comma-separated vector. Do not pass coordinates as separate arguments. Do not use semicolons (`[0; 0; z]` is force/vector syntax).
- **Region bounding boxes support project-variable expressions** (e.g. `("-L/2", "-W/2", 0)`) — these resolve at build time. If a region unexpectedly has zero entities, verify the expressions evaluate to coordinates that enclose the expected geometry entities.
- **Only one PML interaction per physics.** To apply PML to multiple boundaries, create a computed `UNION` region of all PML surfaces and target that single region.
- **`attribute_path` key is `"name"`**, not `"assembly"`. Filters are AND with `bounding_box` when both are specified.
- **STEP product names are not self-describing.** Always verify mappings with build123d before writing `attribute_path` rules (see above).

## Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `region had zero entity tags` | Wrong `min_size`/`max_size` filter | Adjust filters; use computed regions |
| `Invalid regions in mesh parameters: zero entity tags` | Region rule matches nothing | Fix region selectors before meshing |
| `targets tags [...] that are outside its physics target region` | Interaction target includes entities outside the physics domain | Intersect with domain boundary (see above) |
