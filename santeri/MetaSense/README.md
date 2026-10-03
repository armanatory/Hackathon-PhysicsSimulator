# MetaSense

MetaSense is an isolated hackathon scaffold for inverse design of a dielectric metasurface protein sensor. The initial example names **streptavidin** as the surface receptor and **biotin** as the analyte. The scientific device model and acceptance criteria are still to be specified.

## Current modes

| Mode | Current behavior |
| --- | --- |
| `surrogate_demo` | Runs a deterministic **synthetic toy model**: assumed surface coverage, arbitrary geometry-to-resonance mapping, a Lorentzian response dip, optional seeded detector noise, and a fit back to the same toy response family. Output is labeled `synthetic_surrogate_demo`, uses arbitrary normalized response units, and is neither experimental data nor an Allsolve result. No optical property is inferred from molecular coordinates. |
| `allsolve` | Checks server-side configuration but returns HTTP 501 until the optical geometry, materials, excitation, boundaries, mesh, outputs, and validation rules are defined and demonstrated in the SDK. With missing credentials it returns HTTP 503. It never substitutes synthetic output for a cloud solve. |

The [Allsolve SDK](https://allsolve.quanscient.com/documentation/reference/public-api-introduction) supports cloud project and mesh workflows, and [Allsolve electromagnetic waves](https://allsolve.quanscient.com/documentation/using-allsolve/physics/em-waves) supports harmonic analysis and relevant boundaries. A real normal-incidence slab benchmark now verifies the polarized source, periodic boundaries, open ends, and reflected/transmitted power readout. The metasurface spectrum and sensor pipeline still require their own validation.

## Verified optical benchmark

The separate Optical validation panel reads `GET /api/validation/slab`; this endpoint retrieves saved real results without launching jobs. At 1000 nm, a lossless n=1.5 slab of thickness 166.7 nm in vacuum gives fine-mesh R=0.149030 and T=0.851145, compared with Fresnel R=0.147929 and T=0.852071. Both meshes and the vacuum control pass the recorded checks. Slab R/T change by about 0.000980 between meshes; the fine energy residual `1-R-T` is -0.000175.

The default periodic multiplier order gave incorrect fields. Explicit order 2 with the order-2 electric field recovered the Fresnel result on the same meshes, and downloaded field audits confirm periodic continuity. The benchmark uses assumed constant index, vacuum exterior, normal incidence, and a subwavelength period. It does not validate a pillar resonance, dispersive/lossy materials, liquid sensing, or a biological detection claim.

See [the reproducible benchmark protocol](simulations/slab_validation/README.md), [the full report](simulations/slab_validation/results/report.json), and [SDK feedback](SDK_FEEDBACK.md). Failed attempts and the earlier default-periodicity comparison are preserved. Sensor `allsolve` mode remains HTTP 501 until the full device workflow is connected and verified.

## Layout

- `backend/app/binding.py`, `models.py`: sample metadata and assumed surface coverage.
- `backend/app/optics.py`: explicitly synthetic response generation.
- `backend/app/detector.py`: synthetic detector noise.
- `backend/app/inference.py`: toy inverse fit.
- `backend/app/optimization.py`: toy candidate ranking and reserved physical optimization interface.
- `backend/app/jobs.py`, `main.py`: in-memory jobs and FastAPI routes.
- `backend/app/allsolve_adapter.py`, `config.py`: honest cloud-mode boundary and server-side configuration.
- `backend/app/slab_validation.py`: saved real optical benchmark report.
- `simulations/slab_validation/`: cloud runner, source/readout, Fresnel reference, scalar/field evidence, and fixed acceptance checks.
- `frontend/`: React, TypeScript, and Vite UI.

## Run locally

The checked local environment uses **Python 3.11.17** in `.venv`. Its direct dependencies are pinned in `backend/requirements.txt`, and all 36 resolved packages are pinned in `backend/requirements-lock.txt`. On another machine, create a Python 3.11 virtual environment and install the lockfile. The frontend was checked with Node.js 24 and pnpm 11.25.0.

From this folder, check Python dependencies:

```powershell
.\.venv\Scripts\python.exe .\check_setup.py
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Start the backend from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Start the frontend from a second terminal:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open <http://127.0.0.1:5174/>. The backend API is at <http://127.0.0.1:8001/docs>. The separate ports keep MetaSense from colliding with the existing BatchCool app.

For a quick restart on this Windows machine, run `powershell -ExecutionPolicy Bypass -File .\start-local.ps1` from the MetaSense folder. It starts only missing services, checks that the reserved ports belong to MetaSense, and prints the working URLs.

To recreate the Python environment with a Python 3.11 executable, use `python3.11 -m venv .venv` (or the full Python 3.11 path on Windows), then `.venv\Scripts\python.exe -m pip install -r backend\requirements-lock.txt` on Windows.

## Credentials and validation

The backend reads `ALLSOLVE_ACCESS_KEY`, `ALLSOLVE_SECRET_KEY`, and optional `ALLSOLVE_HOST` **only from its process environment**. Copy `.env.example` to a private `.env` in the MetaSense folder if needed. When starting Uvicorn from `backend/`, append `--env-file ..\.env`, or export the variables in that terminal. Do not put secrets in Vite variables or frontend code. The `.env` file is ignored by `.gitignore`.

`GET /api/health` reports mode readiness and SDK/configuration status. `POST /api/jobs` accepts an explicit mode, sample, design, detector settings, and random seed. `GET /api/jobs/{id}` retrieves a completed synthetic job. Jobs are in memory for this scaffold and disappear on backend restart.

Before enabling Allsolve mode, define the unit-cell geometry, wavelength-dependent dielectric data, binding-layer representation, optical excitation, periodic/open boundaries, mesh convergence, observable spectrum, detector calibration, and optimization objective. The user's detailed physics and acceptance criteria will set these choices.

This folder is separate from `Hackathon-PhysicsSimulator`; no shared repository branch or file was changed for MetaSense.
