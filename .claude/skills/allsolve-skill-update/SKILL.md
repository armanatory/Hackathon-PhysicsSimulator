---
name: allsolve-skill-update
description: >-
  Protocol for updating allsolve-* Cursor skills when the Allsolve SDK releases
  a new version. Use when updating skills after an SDK release, checking for
  SDK changes, auditing allsolve skill accuracy, or when pip install allsolve
  upgrades to a new version.
disable-model-invocation: true
---

# Allsolve skill update protocol

## When to run

- After `pip install --upgrade allsolve` produces a new version.
- When the user reports an SDK method behaving differently from a skill.
- Periodically (every 2–3 releases) for a full audit.

## Sources of truth

| Source | URL / location | What it tells you |
| ------ | -------------- | ----------------- |
| SDK reference docs | https://allsolve.quanscient.com/documentation/reference/allsolve-sdk | Full auto-generated API: every class, method, parameter, enum. Canonical but may lag latest PyPI by a few days. |
| GitHub tags | https://github.com/Quanscient-Public/allsolve-sdk-python/tags | Release tags (`v0.4.4`, `v0.5.0`, …). Use for diffing. |
| GitHub compare | `https://github.com/Quanscient-Public/allsolve-sdk-python/compare/v<old>...v<new>` | Diff between two releases — the primary change-detection mechanism. |
| PyPI version history | https://pypi.org/project/allsolve/#history | Release dates and version numbers. |
| Installed package | `.venv/lib/python3.*/site-packages/allsolve/` | Local source; inspect when docs lag behind PyPI. |
| Examples | `https://github.com/Quanscient-Public/allsolve-sdk-python/tree/main/examples` | Working scripts — reveal new patterns, renamed args, new features. |

As of v0.5.0, the repo has a CHANGELOG with structured entries (Added/Changed/Deprecated/Removed). Read it first — it summarizes changes faster than a full diff. No GitHub Release notes exist; rely on the CHANGELOG and tag diff.

## Skills to update

All live in `.cursor/skills/`:

| Skill | Primary API surface |
| ----- | ------------------- |
| `allsolve-sdk` | Top-level entry point, routing map, build order |
| `allsolve-project-workflow` | `Client`, `Project`, create/get/set/reset/copy |
| `allsolve-variables-and-overrides` | `create_variables`, `VariableOverrides`, `create_variable_overrides`, `SweepType` |
| `allsolve-geometry` | `geometry_builder()`, primitives, booleans, transforms, file imports, `CadAlignment` |
| `allsolve-regions` | `create_region_rule`, `create_region_computed`, `create_region_basic`, `RegionOperation` |
| `allsolve-materials` | `create_material`, `create_material_from_library`, `MaterialProperty`, material properties |
| `allsolve-physics-and-interactions` | `Physics.*`, `Interaction.*`, `PhysicsSet` |
| `allsolve-mesh` | `create_mesh`, `MeshSettings`, `MeshRefinement`, `AutoTransfiniteGroup`, `CPU` node types |
| `allsolve-simulation` | `create_simulation_*`, `Output.*`, `OnError`, `Runtime`, `Job` statuses |
| `allsolve-simulation-scripts` | `Script`, `CustomSection`, solver namespaces, `quanscient-stubs` |
| `allsolve-postprocessing` | FFT, windowing, impedance/sensitivity extraction |
| `allsolve-domain-rf` | `ElectromagneticWaves`, S-parameters, eigenmode ports, PEC, boundary admittance |
| `allsolve-domain-structural` | `SolidMechanics`, clamp, load, constraint, eigenmode, GDS import |
| `allsolve-domain-thermal` | `HeatTransfer`, `HeatFluid`, convection, heat source, Joule heating |
| `allsolve-domain-acoustics` | `ElasticWaves`, `AcousticWaves`, `Electrostatics`, piezoelectric coupling, PML |

## Update procedure

### 1. Identify the version delta

```bash
pip show allsolve | grep Version
```

Compare with the version noted at the bottom of each skill's internal comments or with the last-known version in this skill's update log (see bottom of this file).

### 2. Fetch the diff

Open the GitHub compare URL for the two versions:

```
https://github.com/Quanscient-Public/allsolve-sdk-python/compare/v<old>...v<new>
```

Also fetch the compare page to read the diff directly:

```
https://github.com/Quanscient-Public/allsolve-sdk-python/compare/v0.4.4...v0.5.0
```

Focus on these paths in the diff:

| Path pattern | Affects skills |
| ------------ | -------------- |
| `src/allsolve/client.py` | `allsolve-sdk`, `allsolve-project-workflow` |
| `src/allsolve/project.py` | All skills (methods on `Project`) |
| `src/allsolve/geometry/` | `allsolve-geometry` |
| `src/allsolve/region.py` | `allsolve-regions` |
| `src/allsolve/material.py` | `allsolve-materials` |
| `src/allsolve/physics/` | `allsolve-physics-and-interactions` |
| `src/allsolve/mesh.py` | `allsolve-mesh` |
| `src/allsolve/simulation/` | `allsolve-simulation`, `allsolve-simulation-scripts` |
| `src/allsolve/varint.py`, `override.py` | `allsolve-variables-and-overrides` |
| `src/allsolve/job*.py` | `allsolve-simulation` (run pattern, statuses) |
| `examples/` | Any skill — new examples reveal new patterns |

### 3. Categorize changes

For each changed file, classify:

- **New method / class / enum** — add to the relevant skill if user-facing.
- **Renamed or moved** — update skill references; note old name in a deprecation line if the old name still works.
- **Changed signature** (new param, removed param, default change) — update code examples and kwargs tables.
- **Removed** — remove from skill; add deprecation note if recently removed.
- **Bug fix / internal only** — no skill change needed.

### 4. Update each affected skill

For each skill that needs changes:

1. Read the current `SKILL.md`.
2. Apply the changes identified in step 3.
3. Keep the skill under 500 lines (see `create-skill`).
4. Preserve the existing structure — do not reorganize sections unless necessary.
5. If a new major feature area appears (e.g., a whole new physics type), add it in the appropriate skill rather than creating a new skill.

### 5. Update the routing map

If new top-level entry points were added, update the "Key API surfaces" table in `allsolve-sdk/SKILL.md`.

### 6. Cross-check the SDK reference page

Fetch the SDK reference docs page and compare the module listing against the skills:

```
https://allsolve.quanscient.com/documentation/reference/allsolve-sdk
```

This catches things missed by the diff (e.g., methods that were always there but never documented in the skills).

**Do this full cross-check every 2–3 releases or on any major version bump, not on every patch.**

### 7. Log the update

Append an entry to the update log at the bottom of this file.

## Diff-only vs full audit

| Approach | When | Scope |
| -------- | ---- | ----- |
| **Diff between tags** | Every release | Only changed files; fast; primary mechanism |
| **Full audit against SDK reference** | Every 2–3 releases or major bump | All modules vs all skills; catches accumulated drift and undocumented methods |

A diff alone risks missing things the skills never covered. A full audit every time is wasteful (~11K lines of reference). Alternate between them.

## Pitfalls

- The SDK reference page may lag behind the latest PyPI release by days. If the docs version header doesn't match the installed version, inspect the installed package source directly.
- Examples in the repo may use patterns not yet in the skills — always check `examples/` in the diff.
- Enums (`Physics.*`, `Interaction.*`, `Output.*`, `CPU.*`) are generated code — changes there often mean new physics types or output types. These are high-impact additions.

## Update log

Record each update here so the next run knows the baseline.

| Date | From version | To version | Skills touched | Notes |
| ---- | ------------ | ---------- | -------------- | ----- |
| 2026-07-16 | 0.4.4 | 0.5.0 | allsolve-sdk, allsolve-simulation, allsolve-physics-and-interactions, allsolve-mesh, allsolve-materials, allsolve-geometry, allsolve-project-workflow, allsolve-variables-and-overrides | Physics sets, resource reservations, teams, library expressions, mesh size factors, EM BoundaryAdmittance, viscous damping materials, batch job polling, thread-safe client. Full audit against CHANGELOG + source diff. |
| *(initial)* | — | 0.4.4 | All | Skills created from SDK reference + examples |
