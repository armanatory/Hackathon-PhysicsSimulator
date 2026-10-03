---
name: allsolve-project-workflow
description: >-
  Manage Allsolve SDK projects: authentication, current-project persistence,
  reuse across scripts, reset/rebuild, and browser + SDK editing. Use when
  connecting to Allsolve, selecting a project, set_current_project,
  get_current_project, or keeping a project open in the browser while editing via SDK.
disable-model-invocation: true
---

# Allsolve project workflow

## Authentication

Create an Organization API key in the Allsolve UI: **Settings → API keys → Create key**.

```python
client = allsolve.Client(dotenv_file=".env")
# or explicit: Client(api_key=..., api_secret=..., host=...)
print(client.host)
```

Add to `.gitignore`:

```
.env
.allsolve_cache/
.venv/
```

## Current project (multi-script workflow)

Persist a project so follow-up scripts reuse it without creating duplicates:

```python
project = client.create_project(name="My study", description="...")
client.set_current_project(project)

# Later script:
project = client.get_current_project()
if project is None:
    raise RuntimeError("No current project — run setup script first")
```

Storage: `.allsolve_cache/.allsolve_current_project_id` (project ID only), relative to the working directory.

Clear selection: `client.set_current_project(None)`.

**During development**, prefer `get_current_project()` over `create_project()` — reuse one project and reset in place when iterating. **Once mesh or results exist**, keep that project unless the user wants a fresh start; do not reset and lose results.

## One folder per project

Each project script should live in its own folder. The `.allsolve_cache` that stores the current project ID is per-directory. If two unrelated projects share a folder, `get_current_project()` gets mixed.

```
my_projects/
├── bending_beam/
│   ├── bending_beam.py
│   └── .allsolve_cache/      ← tracks the beam project
├── chessboard/
│   ├── chessboard.py
│   └── .allsolve_cache/      ← tracks the chessboard project
└── .env                      ← shared credentials (symlink or parent-level)
```

When creating a new project script, always create a dedicated folder for it first. The `.env` file can be shared (e.g. symlinked or placed in a parent directory and referenced with a relative path).

## Browser + SDK editing

Keep the project open in the browser (`client.get_url(project)`) while editing via SDK — refresh to see changes. Reference: `examples/edit_project/edit_project.py`.

## Reset project (rebuild simulation setup)

Delete in this order to avoid dangling references:

```python
def reset_project(project: allsolve.Project) -> None:
    for sim in project.get_simulations():
        sim.delete()
    for mesh in project.get_meshes():
        mesh.delete()
    for physic in project.get_physics():
        for interaction in physic.interactions:
            interaction.delete()
        physic.delete()
    for material in project.get_materials():
        material.delete()
    for region in project.get_regions():
        region.delete()
    project.geometry_builder().delete()
    for fn in project.get_interpolated_functions():
        fn.delete()
    for fn in project.get_functions():
        fn.delete()
    for var in reversed(project.get_variables()):
        var.delete()
    for file in project.get_files():
        allsolve.delete_file(file, project.id)
```

Use before rebuilding geometry/physics when iterating on the same project ID.

## Teams (v0.5.0+)

When team credits enforcement is active, assign projects to a team:

```python
teams = allsolve.get_teams()  # discover available teams
project = client.create_project(name="...", description="...", team_id=teams[0].id)
print(project.team_id)
```

If the API user belongs to exactly one team with active credits, assignment is automatic. If multiple teams exist, `team_id` is required.

## Thread-safe client (v0.5.0+)

Use `client.in_thread()` instead of `with client` when sharing a `Client` across threads:

```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor() as pool:
    def worker():
        with client.in_thread():
            project = client.get_current_project()
            # ...
    pool.submit(worker)
```

## Copy and cleanup

```python
project.delete()                           # delete entirely
project.copy(with_results=False)        # duplicate project
client.clean_cache()                    # remove local .allsolve_cache
```

## Temporary project pattern (sweep-and-delete)

For tuning sweeps or convergence studies where results are extracted then discarded:

```python
project = client.create_project(name="Tuning sweep", description="...")
try:
    # ... build, sweep, extract results ...
finally:
    project.delete()
```

Use when: two-stage tuning, mesh convergence, or any exploration where the project is disposable.

## Shared-account concurrency

On shared accounts, others' jobs consume the vCPU quota. Check before launching:

```python
quota = allsolve.get_quota()
# Organization-level: quota.max_concurrent_cores, quota.total_running_cores
# Team enforcement: quota.team_quota_enforcement_active
# Per-team: quota.teams → list of TeamQuota with team-level limits
```

- Prefer the **smallest node** that fits in memory — more jobs run in parallel.
- Catch `vcpu_limit_exceeded` gracefully and retry later rather than crashing.
- Big nodes (`CORES_8_128GB` = 8 vCPU) exhaust the limit fast on shared accounts.

## Gotchas

- **`project.export()` / `export_yaml()` crash on older/web-UI projects** with `ValueError: None is not a valid GeometryPipelineVersion`. Use per-resource `get_all(project_id=...)` calls for inspection instead.
- **`Project.get(id)` to load existing projects** — use for inspecting or modifying projects created via the web UI.
- **`get_logs(limit=100)` truncates and has no timestamps.** For full logs with timestamps, use `job._get_logs(after_id=..., limit=...)` and inspect `JobLogEvent.timestamp`. The default limit can be found in the SDK source as `LOG_MAX_LIMIT`.
- **Never delete a project while any process is still polling it.** A driver mid-`mesh.run()`/`sim.run()` will crash with `NotFoundException (404)`. Only delete inside the same process that owns the run. Read-only polls (`get_status`, `get_output_data`) are safe.
- **Launch/harvest split for long runs.** Cloud sims survive local process death. Split into a **launcher** (`sim.start()`, non-blocking, skips already-run) and a **harvester** (reads cloud state, pulls results, re-runnable). The launcher should be idempotent — match meshes/sims by name, skip anything already running or completed, and exit in seconds.
