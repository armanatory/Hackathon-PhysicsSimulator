# QuietOffice

**Put acoustic treatment where physics says it matters.**

An open office can afford only a few acoustic screens. QuietOffice simulates how speech from
one conversation spreads through the room and searches for the screen positions that lower
the speech level at the desks the most.

This folder is self-contained so it does not collide with the other ideas in the repository.
Everything QuietOffice lives here; the shared `backend/`, `frontend/` and `simulations/`
folders in the repository root are left untouched.

## Read first

| Document | What it answers |
|----------|-----------------|
| [docs/why-allsolve.md](docs/why-allsolve.md) | **Why use Allsolve and its SDK for this problem** instead of a formula, a ray tracer or another FEM tool |
| [docs/idea.md](docs/idea.md) | The idea, scope, demo flow and pitch |
| [docs/sdk-feedback.md](docs/sdk-feedback.md) | SDK pain points and suggestions found while building |
| [backend/README.md](backend/README.md) | API, physics model, search strategies, current status |
| [frontend/README.md](frontend/README.md) | UI structure and the two sources of numbers |
| [docs/deploy.md](docs/deploy.md) | Running it in Docker, locally and on a server |

UI sketches that led to this look: [docs/ui-exploring/03-quiet-office](../docs/ui-exploring/03-quiet-office/index.html).

## Layout

```
quiet-office/
├── run.bat             # double-click: installs what is missing and starts everything
├── docker-compose.yml  # the same app as two containers, for shipping
├── backend/         # FastAPI + Allsolve SDK: builds the project, runs the layout search
├── frontend/        # Vue 3 UI: floor plan, before/after sound map, score, search chart
├── simulations/
│   └── baseline/    # one small Allsolve run to verify the model before the full search
└── docs/            # the documents listed above
```

## Run it

Double-click [`run.bat`](run.bat). It installs the frontend packages, creates the Python
environment, starts the backend on port 8000 and the frontend on port 5173, and opens
http://localhost:5173.

Shared with the rest of the repository, in the repository root:

- `.venv/` — the Python environment
- `.env` — Allsolve keys (`QS_ACCESS_KEY`, `QS_SECRET_KEY`), copied from `.env.example`.
  A `quiet-office/.env` is also read and takes precedence if this project needs its own keys.

Without Python or keys the frontend still runs and shows a quick in-browser estimate.

### In Docker

With Docker Desktop running, from this folder:

```bash
docker compose up -d --build
```

Then open http://localhost:8080. Details and server notes: [docs/deploy.md](docs/deploy.md).

## How it works

1. The office is described as data: room size, where the conversation is, desk positions and
   the places a screen is allowed to stand.
2. The backend turns that into a 2D Allsolve project: air, a pulsating talker, sound-hard
   screens whose positions are project variables, absorbing walls.
3. A search runs rounds of layouts as geometry sweeps: harmonic acoustic simulations at the
   chosen speech bands, with the pressure read at every desk.
4. Desk pressures become speech levels and one score per layout; the untreated office is 100.
5. The UI shows the best layout, before and after, and every layout that was tested.

## Status

- Frontend: working, checked in a browser.
- Backend: starts, the SDK is installed and keys are configured. The Allsolve run itself has
  not been confirmed yet; run [`simulations/baseline`](simulations/baseline/run_baseline.py)
  first and fix what the solver reports.
- The coloured sound map is still the quick estimate, also after an Allsolve run. Showing the
  solver's pressure field is the next piece.
