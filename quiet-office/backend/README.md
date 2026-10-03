# QuietOffice backend

FastAPI backend that searches for the best placement of a few acoustic screens in an
open-plan office by running Allsolve acoustic simulations through the Python SDK.

Structure follows the reference app in
[beer_cooling_app/backend](../../docs/quanscient-docs/beer_cooling_app/backend).

```
backend/
├── app/
│   ├── allsolve/
│   │   ├── project_builder.py      # office -> Allsolve project (geometry, regions, physics)
│   │   └── optimization_runner.py  # layout search: sweeps, polling, scoring
│   ├── models/office.py            # Pydantic models + the default demo office
│   ├── routers/optimization.py     # API endpoints
│   ├── scoring.py                  # desk pressures -> levels -> layout score
│   ├── config.py                   # settings from the repo-root .env
│   └── main.py                     # FastAPI application
├── sim/                            # custom solver scripts (none needed yet)
└── requirements.txt
```

## Setup

Needs Python 3.10 or newer.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r quiet-office/backend/requirements.txt
```

Copy `.env.example` to `.env` in the repository root and fill in `QS_ACCESS_KEY` and
`QS_SECRET_KEY`.

## Running the server

From the `quiet-office/backend/` folder (or just double-click `quiet-office/run.bat`):

```bash
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/office/default` | GET | The demo office: room, talker, desks, candidate screen positions |
| `/api/capabilities` | GET | Whether the SDK is installed and credentials are configured |
| `/api/optimization/start` | POST | Start a layout search |
| `/api/optimization/{id}/status` | GET | Progress, layouts done, best score so far |
| `/api/optimization/{id}/results` | GET | Baseline, best layout and every layout tested |
| `/api/optimization/{id}/abort` | POST | Stop the search and the running cloud job |

```http
POST /api/optimization/start
Content-Type: application/json

{
  "n_screens": 3,
  "frequencies_hz": [250, 500],
  "strategy": "greedy"
}
```

Leaving out `office` uses the default demo office.

## Physics model

2D top-down slice of the office, harmonic acoustic waves:

- **Air**: density 1.225 kg/m³, speed of sound 343 m/s
- **Talker**: a 0.15 m pulsating disk, `AcousticWavesNormalAcceleration` on its edge
- **Screens**: thin rectangles left out of the air domain, so they are sound-hard
- **Walls**: `AcousticWavesAbsorbingBoundary` (no reflections in v1)
- **Outputs**: pressure magnitude at every desk, read with `interpolate(...)` value outputs
- **Mesh**: element size = wavelength / 6 at the highest frequency

Levels are calibrated so the untreated office reads 60 dB one metre from the talker.
The layout score is the average desk pressure plus half the worst desk, scaled so the
untreated office is 100.

## Search strategies

| Strategy | Layouts for 3 screens, 12 positions | How |
|----------|-------------------------------------|-----|
| `greedy` (default) | 1 + 12 + 11 + 10 = 34 | Place one screen at a time, keep the best, repeat |
| `exhaustive` | 1 + 220 = 221 | Every combination in one sweep |

Each round is one geometry sweep: the screen positions are project variables, the mesh is
rebuilt per layout and one harmonic simulation solves all layouts and frequencies.

## Status

**Not yet confirmed against Allsolve.** The code was written from the SDK source and skill docs
before Python and keys were set up. Before the full search, run the small check in
[`simulations/baseline`](../simulations/baseline/run_baseline.py)
and fix what the solver complains about. Things most likely to need adjusting:

- the `obstacles` region (size filter) and whether unmeshed-physics surfaces are accepted
- the `interpolate(reg.air, ..., [x, y, 0])` output expression in 2D
- whether harmonic results sit at `NO_STEP` in the output data
