---
name: allsolve-sdk
description: >-
  Build multiphysics cloud simulations with the Quanscient Allsolve Python SDK
  (pip install allsolve). Use when the user mentions Allsolve, allsolve,
  Quanscient, create_project, geometry_builder, add_physics, create_mesh,
  create_simulation, set_current_project, or programmatic simulation from Python.
---

# Allsolve Python SDK

Official repo: https://github.com/Quanscient-Public/allsolve-sdk-python

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install allsolve
```

Requires Python 3.10+. Credentials in `.env`:

```
ALLSOLVE_ACCESS_KEY=...
ALLSOLVE_SECRET_KEY=...
ALLSOLVE_HOST=https://allsolve.quanscient.com/
```

```python
import allsolve

client = allsolve.Client()  # auto-discovers .env in working directory, but if file is elsewhere, use dotenv_file="<path>/<to>/<file>"
```

## Documentation lookup — `allsolve-docs` MCP server (recommended)

An MCP server named **`allsolve-docs`** may be available in this workspace. When running, it can be used to search all Allsolve documentation locally:

| Tool | When to use |
|------|-------------|
| `search` | General lookup across all sources (skills, API, stubs, examples, docs site) |
| `search_api_spec` | Find REST API endpoints, request/response schemas, parameters |
| `search_scripting_api` | Find solver scripting classes/methods (the `.pyi` stubs) |
| `get_example` | Retrieve a full example script by name (e.g. `bending_beam`) |
| `list_examples` | See all available SDK examples |
| `refresh_web_cache` | Update the cached documentation website (auto-expires after 24h) |

When available, prefer the MCP server over fetching from the web. It has indexed:
- All `allsolve-*` skill files (this skill and its siblings)
- The full REST API specification
- Solver scripting type stubs and docstrings
- SDK example projects (scripts + READMEs)
- The full documentation website (cached locally)

**If the MCP server is not available**, fall back to these resources:
- **Skills**: read the `allsolve-*` SKILL.md files in this repo directly
- **Examples**: browse https://github.com/Quanscient-Public/allsolve-sdk-python/tree/main/examples
- **SDK reference**: https://allsolve.quanscient.com/documentation/reference/allsolve-sdk
- **Full docs**: https://allsolve.quanscient.com/documentation

## Before writing code

1. Look up the closest existing example — use `allsolve-docs` MCP → `search` or `get_example` if available, otherwise browse the examples on GitHub or read the sibling skill files directly.
2. If the simulation targets a specific domain, load the domain skill first:
   - **RF / Microwave / Antenna** → `allsolve-domain-rf`
   - **Structural mechanics** → `allsolve-domain-structural`
   - **Thermal / Heat transfer** → `allsolve-domain-thermal`
   - **Acoustics / Ultrasonics / Piezoelectric** → `allsolve-domain-acoustics`
3. Load only the focused building-block skill(s) relevant to the task:
   - **Project lifecycle** → `allsolve-project-workflow`
   - **Variables & parametric sweeps** → `allsolve-variables-and-overrides`
   - **Geometry** → `allsolve-geometry`
   - **Regions** → `allsolve-regions`
   - **Materials** → `allsolve-materials`
   - **Physics & boundary conditions** → `allsolve-physics-and-interactions`
   - **Mesh** → `allsolve-mesh`
   - **Simulation & outputs** → `allsolve-simulation`
   - **Custom simulation scripts** → `allsolve-simulation-scripts`
   - **FFT / post-processing** → `allsolve-postprocessing`

## Standard build order

Each project script must live in its own folder (see `allsolve-project-workflow` → "One folder per project"). Create the folder before writing the script.

Always follow this sequence — later steps depend on earlier ones:

1. **Variables** → `allsolve-variables-and-overrides`
2. **Geometry** → `allsolve-geometry`
3. **Regions** → `allsolve-regions`
4. **Materials** → `allsolve-materials`
5. **Physics** → `allsolve-physics-and-interactions`
6. **Mesh** → `allsolve-mesh`
7. **Simulation** → `allsolve-simulation`
8. **Run** — `mesh.run()` then `sim.run(print_logs=True)`; check `Job.SUCCESS`. For geometry-affecting sweeps, run `mesh.get_override(sweep).run()` instead of `mesh.run()` — see `allsolve-variables-and-overrides`

## Key API surfaces

Routing map — not exhaustive. For the full API, use the [SDK reference](https://allsolve.quanscient.com/documentation/reference/allsolve-sdk).

| Area       | Entry points                                                                                                                                        |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Client     | `Client`, `create_project`, `get_current_project`, `set_current_project`, `get_project`, `get_url`, `export_project_yaml`, `import_project`         |
| Teams      | `get_teams`, `team_id` on `create_project` and `ResourceReservation`                                                                                |
| Variables  | `create_variables`, `VariableOverrides`, `create_variable_overrides`, `create_variable_from_library`                                                 |
| Geometry   | `geometry_builder()` → `add_box`, `add_cylinder`, `add_union`, `add_difference`, … → `build()`                                                     |
| Regions    | `create_region_rule`, `create_region_computed`, `create_region_basic`                                                                                |
| Materials  | `create_material`, `create_material_from_library`                                                                                                   |
| Physics    | `PhysicsSet`, `get_default_physics_set`, `create_physics_set`, `Physics.*`, `Interaction.*`                                                          |
| Mesh       | `create_mesh`, `MeshSettings`, `MeshRefinement`, `scale_factor`, `curvature_enhancement`                                                            |
| Simulation | `create_simulation_static`, `create_simulation_transient`, `create_simulation_harmonic`, `create_simulation_eigenmode`, `create_simulation_multiharmonic` |
| Reservation| `client.resource_reservation()`, `ResourceReservation`, `ReservationStatus`                                                                         |

## Units

- User-facing geometry variables and material properties use **SI** (meters, kelvin, kg, Pa, W).
- The CAD kernel may log internal millimeter units — do not manually convert unless errors indicate a mismatch.

## General gotchas

- **PyPI package name is `allsolve`.**
- **The solver runs in the cloud** — the local Python process just streams logs and waits.
- **Start simple, verify, build up.** Begin with the simplest possible model (one body, one material, one physics, no interactions) and verify it runs before adding complexity. Add layers one at a time to avoid debugging multiple issues simultaneously.
- **Always prefer sweeps** over running individual simulations in a loop. Sweeps run all parameter points in a single cloud job, sharing geometry and mesh infrastructure.
- **Check quota before running:** `quota = allsolve.get_quota()` — shared accounts can hit `vcpu_limit_exceeded` from others' jobs.
- **Decompose scripts into focused functions** with a thin `main()`: `create_variables`, `build_geometry`, `create_regions`, `assign_materials`, `configure_physics`, `run_mesh`, `save_state`.
- **`allsolve.Physic.get_all(project_id)`** — the class is `Physic` (singular), not `Physics`.
- **Inspect existing projects via per-resource APIs**, not `export()` / `export_yaml()`. Export crashes on older/web-UI projects with `ValueError: None is not a valid GeometryPipelineVersion`. Use `get_variables()`, `get_regions()`, `get_materials()`, `get_physics()`, etc. instead.
- **Allsolve web UI URL format:** `https://<host>/#/projects/<id>`, not `https://<host>/project/<id>`.
- **Coupled multiphysics: create all physics before adding interactions** — cross-physics interactions require fields from other physics to exist. See `allsolve-physics-and-interactions` for details.

## Anti-patterns

### Project lifecycle

- **While iterating in development:** calling `create_project()` on every script run. Reuse the same project via `get_current_project()` / `set_current_project()`, reset its contents in place when the setup is wrong, or delete failed projects explicitly. Spawning a new project each run leaves orphaned, half-built projects on the server.
- **Once mesh or simulation results exist:** resetting project data, rebuilding from scratch, or re-running mesh/simulation without explicit user confirmation. Results belong to the project — wiping or re-running loses existing mesh and simulation output. Prefer loading the current project and modifying only what changed. Ask before starting over or before re-running when the current mesh or simulation has useful results the user may want to keep.

### General

- Ignoring `mesh.get_status()` / `sim.get_status()` before proceeding.
- Using `project.add_physics()` or `physics=[...]` on simulation creation — both deprecated in v0.5.0. Use `PhysicsSet.add_physics()` and `physics_set=` instead.
