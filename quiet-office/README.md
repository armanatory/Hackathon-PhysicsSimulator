# Allquiet

**Put acoustic treatment where physics says it matters.**

An open office can afford only a few acoustic screens. Allquiet simulates how speech from
one conversation spreads through the room and searches for the screen positions that lower
the speech level at the desks the most.

This folder is self-contained so it does not collide with the other ideas in the repository.
Everything Allquiet lives here; the shared `backend/`, `frontend/` and `simulations/`
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
| [docs/scan-import.md](docs/scan-import.md) | Scanning a real office with a phone, opening the scan in the app and tracing the room |

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

1. The office is described as data: the room outline, the noise sources, the desks and quiet
   zones that should be quiet, and the places a screen is allowed to stand (marked by hand or
   suggested by the app). It is drawn in the app's editor, by hand or
   traced over a phone scan.
2. The backend turns that into an Allsolve project: air, a pulsating talker, and screens whose
   positions are project variables. By default this is the full 3D room, with ceiling height,
   panel height and panel material; a cheaper 2D top-down slice is the alternative.
3. A search runs rounds of layouts as geometry sweeps: harmonic acoustic simulations at the
   chosen speech bands, one source at a time, with the pressure read at every listening point.
   Each round is split into several Allsolve jobs that run in parallel.
4. Desk pressures become speech levels and one score per layout; the untreated office is 100.
5. The UI shows the best layout, before and after, and every layout that was tested.

## Status

- Frontend: working, checked in a browser, including the floor-plan editor and scan import.
- Backend: confirmed on Allsolve with real 2D and 3D runs; see the status table in
  [backend/README.md](backend/README.md). Each run records every request and answer, and the
  UI shows that record and the raw solver pressures.
- AI: with an OpenAI key, a result and its run record can be explained in plain language.
- 3D: the app has a 3D view, panel types by height and surface, and a 3D Allsolve model. The
  3D model is far more expensive than 2D: two layouts at 250 Hz took about five minutes.
- The coloured sound map is still the quick estimate, also after an Allsolve run. Showing the
  solver's pressure field is the next piece.
