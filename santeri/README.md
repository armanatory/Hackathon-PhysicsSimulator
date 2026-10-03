# Santeri's Quanscient hackathon cases

This folder holds three independent prototypes and the presentation plan. It is isolated from the team's `quiet-office/` work.

| Case | Local UI port | State |
| --- | ---: | --- |
| [MetaSense](MetaSense/README.md) | 5174 | Metasurface sensor scaffold; real optical slab validation, sensor workflow still in progress |
| [RoomValue](RoomValue/README.md) | 5175 | 3D room-acoustic Allsolve model and placement planner |
| [ExhaustLab](ExhaustLab/README.md) | 5176 | Diesel exhaust installation planner with archived Allsolve flow/thermal cases and separate electrostatic pilot |

Read each case's `AGENTS.md` and README before running it. [Presentation plan](PRESENTATION_PLAN.md) maps the strongest current demo to the hackathon criteria.

Secrets and machine-specific runtimes were not copied. Put credentials in a private `santeri/.env` or supply them as server environment variables; never commit them. Large solver field files, mesh binaries, Python environments, Node modules, and runtime caches were omitted to keep Git usable. Compact model definitions, code, reports, validation JSON, CSV outputs, and cloud project IDs are included. Some cloud-backed searches need the original field exports fetched or regenerated before they can run from a fresh clone; follow the case READMEs and check the cloud provenance.
