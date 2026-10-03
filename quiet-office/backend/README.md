# QuietOffice backend

FastAPI backend that searches for the best placement of a few acoustic screens in an
open-plan office by running Allsolve acoustic simulations through the Python SDK.

Structure follows the reference app in
[beer_cooling_app/backend](../../docs/quanscient-docs/beer_cooling_app/backend).

```
backend/
├── app/
│   ├── allsolve/
│   │   ├── project_builder.py      # office -> 2D Allsolve project (geometry, regions, physics)
│   │   ├── project_builder_3d.py   # office -> 3D Allsolve project, with heights
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
| `/api/optimization/{id}/log` | GET | The run log: every request sent to Allsolve and every answer (`?since=n`) |
| `/api/optimization/{id}/abort` | POST | Stop the search and the running cloud job |
| `/api/explain` | POST | Plain-language explanation of a result, written by an OpenAI model |

```http
POST /api/optimization/start
Content-Type: application/json

{
  "n_screens": 3,
  "model": "3d",
  "screen_height_m": 1.6,
  "screen_absorbing": false,
  "frequencies_hz": [250],
  "strategy": "greedy",
  "parallel_jobs": 4
}
```

Leaving out `office` uses the default demo office.

## Physics model

Harmonic acoustic waves, in one of two models chosen per request with `model`.

### 3D room (`"model": "3d"`, the default)

The room outline pulled up to the ceiling, so heights are real:

- **Talker**: a 0.15 m pulsating sphere at mouth height (1.5 m, standing)
- **Screens**: boxes standing on the floor with the chosen `screen_height_m`. Sound passes
  over anything lower than the ceiling, which is the difference between a 1.2 m desk divider
  and a 2 m partition
- **Material**: with `screen_absorbing` the panel faces get an absorbing boundary; otherwise
  they reflect
- **Floor** reflects. **Walls and ceiling** absorb
- **Outputs**: pressure at ear height (1.2 m, seated) above each desk

Cost is the catch. The number of unknowns grows with the cube of frequency: for the demo
office about 0.4 million at 250 Hz and 3.3 million at 500 Hz, per layout. Up to about 0.7
million the direct solver runs on one large machine; above that the iterative solver is used
on 4 or 8. **Start with 250 Hz only.**

### 2D slice (`"model": "2d"`)

Top-down slice of the office. Fast and cheap, but every panel is floor-to-ceiling and the
panel height and material are ignored:

- **Room**: any outline. A rectangular room is one rectangle of air. For any other shape the
  air is the bounding rectangle, and a 0.2 m solid strip is added along every wall that is not
  on that rectangle. The strips seal the room off from the leftover corners. This is a
  workaround: the SDK geometry builder has no polygon primitive
- **Air**: density 1.225 kg/m³, speed of sound 343 m/s
- **Talker**: a 0.15 m pulsating disk, `AcousticWavesNormalAcceleration` on its edge
- **Screens**: thin rectangles left out of the air domain, so they are sound-hard
- **Walls**: `AcousticWavesAbsorbingBoundary` (no reflections in v1)
- **Outputs**: pressure magnitude at every desk, read with `interpolate(...)` value outputs
- **Mesh**: element size = wavelength / 6 at the highest frequency

Levels are calibrated so the untreated office reads 60 dB one metre from the talker.
The layout score is the average desk pressure plus half the worst desk, scaled so the
untreated office is 100.

## Proof that a result comes from Allsolve

Every run keeps a **run log** (`app/allsolve/run_log.py`): one entry per request sent to
Allsolve (project, variables, geometry, physics, sweep, mesh, simulation), per answer
(ids, job status, pressures read back), per line of the cloud jobs' own logs, and per local
step (scoring). The frontend shows it live.

The results also carry an `evidence` block: the Allsolve project id and URL, every mesh and
simulation job with its id and final status, the number of solves, and the raw pressures the
solver returned at each listening point for the untreated office and the chosen layout. The
frontend puts those next to the quick estimate for the same layout, so the difference between
"estimated" and "simulated" is visible.

## Explanation in plain language

With `OPENAI_API_KEY` in `.env`, `POST /api/explain` sends the result summary and a shortened
run log to an OpenAI model (`OPENAI_MODEL`, default `gpt-4o-mini`) and returns four short
paragraphs for a non-engineer: what was done, what was found, what to do, how sure we can be.
The model only narrates the figures it is given; it calculates nothing and is told not to
invent numbers. No key means the endpoint answers 503 and the rest of the app is unaffected.

What is sent to OpenAI: room size, source names and levels, zone names, settings, scores and
levels, the Allsolve project URL, and the run log messages. No API keys.

## Noise sources, quiet zones and listening points

The office can hold up to six **noise sources**, each with its own level 1 m away, and any
mix of **desks** (single listening points) and **quiet zones** (rectangles sampled with a
listening point about every 0.8 m). The search minimises the noise over all listening points
together; results report each desk and the average over each zone.

Sources are independent, so they must not interfere with each other in the result. Each one
is therefore solved on its own (a project variable switches the others off) and the results
are added as energy afterwards. One layout costs *sources × bands* solves. Each source is
calibrated separately: with no screens, the pressure 1 m from it defines its stated level.

## Parallel jobs

Each round of layouts is split into `parallel_jobs` Allsolve jobs (default 4, up to 8). Every
job is its own sweep, mesh and simulation, started from its own thread and running in the
cloud at the same time as the others; the backend only waits and collects. If one job fails
or the user stops the run, the others are aborted.

More parallel jobs finish sooner but hold more of the account's compute quota at once. On a
shared workshop account, start with 2.

## Search strategies

| Strategy | Layouts for 3 screens, 12 positions | How |
|----------|-------------------------------------|-----|
| `greedy` (default) | 1 + 12 + 11 + 10 = 34 | Place one screen at a time, keep the best, repeat |
| `exhaustive` | 1 + 220 = 221 | Every combination in one sweep |

Each round is one geometry sweep: the screen positions are project variables, the mesh is
rebuilt per layout and one harmonic simulation solves all layouts and frequencies.

## Status

**Confirmed on Allsolve** with real runs on 3 October:

| Run | Layouts | Time | Result |
|-----|---------|------|--------|
| 2D, 250 Hz, baseline script | 2 | about 50 s | untreated 100, one screen 57.5 |
| 2D, 250 Hz, from the UI, 4 parallel jobs | 13 | about 60 s | best 57.5 |
| 3D, 250 Hz, baseline script, 1.6 m screen | 2 | about 5 min | untreated 100, one screen 80.3 |

The 3D screen does less than the 2D one because sound passes over a 1.6 m panel, which the 2D
slice cannot represent.

One bug was found this way: the first runs completed without error but returned exactly zero
pressure everywhere. A harmonic simulation needs the source to oscillate; a constant
acceleration is a steady push, which gives silence. The source is now `accel * sn(1)`.

Check a new setup with the small job in
[`simulations/baseline`](../simulations/baseline/run_baseline.py) (`2d` or `3d`), which
prints the run log.

Still not run on Allsolve:

- several noise sources at once, quiet zones, and absorbing panels
- 3D with more than one frequency (large; needs the iterative solver on several machines)
- non-rectangular rooms: the wall strips are selected by name (`attribute_path`), and slanted
  walls use `add_rectangle(rotation=...)`, assumed to turn about the rectangle centre
