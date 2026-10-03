# Hackathon-PhysicsSimulator

Allquiet lives in `quiet-office/`: a Vue frontend (`frontend/`) and a Python backend (`backend/`) that builds and runs acoustic simulations with the Quanscient Allsolve SDK. Start everything with `quiet-office/run.bat`. The `.venv` and `.env` (Allsolve keys) live in the repository root.

## Allsolve code

The Allsolve SDK skills are in `.claude/skills/allsolve-*`. Before writing or changing anything in `quiet-office/backend/app/allsolve/` or `quiet-office/simulations/`:

1. Load `allsolve-sdk` and `allsolve-domain-acoustics`.
2. Load the building-block skill for the step being touched (`allsolve-geometry`, `allsolve-regions`, `allsolve-materials`, `allsolve-physics-and-interactions`, `allsolve-mesh`, `allsolve-simulation`, `allsolve-variables-and-overrides`, `allsolve-postprocessing`, `allsolve-project-workflow`).

Simulations run in the cloud and use shared quota. Reuse the existing project instead of creating a new one per run, and ask before re-running a mesh or simulation or wiping a project that already has results.

SDK problems and surprises found along the way go in `quiet-office/docs/sdk-feedback.md`.
