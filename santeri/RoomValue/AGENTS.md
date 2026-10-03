# RoomValue acoustic case thread instructions

Own this case in `F:\H4H quanscient\RoomValue`. Keep it separate from `MetaSense`, `ExhaustLab`, `beer_cooling_app`, and the shared `Hackathon-PhysicsSimulator` repository. Do not edit or push the shared repository for this case. Keep Allsolve keys on the server and out of chat.

## Current user goal

Connect an actual dataset room's 3D acoustic simulation to the local website. The latest user instruction replaces budget/quiet-area targets with **maximum number of panels, editable sound source positions/levels, and minimum noise at one chosen XYZ listening point, displayed in decibels**. No cost or budget belongs in the current website flow. Treat panel count as a maximum; fewer panels can be quieter at a resonant listening point.

## Current state

- Website: <http://127.0.0.1:5175/>; API: <http://127.0.0.1:8002/docs>. `start-local.ps1` starts missing localhost services and prefers the root `.venv` containing Allsolve.
- Main website: Sources / Listen here / Panels, up to three of nine dataset source IDs with editable XYZ and 0â€“120 dB levels; one movable listener; max panel count 0â€“6; six allowed/excluded wall/ceiling positions. It has orbit/zoom, floor placement, saved drafts/jobs, stale-result handling and cloud provenance.
- `experiments/optimizer3d.py` provides `run_point_optimization` and exhaustive `search_point`. Source dB specifies normalized RMS SPL at a 0.08 m sphere, referenced to 20 microPa. Unit basis is 1 Pa peak (90.9691 dB RMS SPL). Independent source powers add; coherent phase is not modeled. Minimize RMS at the listener across all allowed subsets from zero through the cap. Exact ties prefer fewer panels. No count-first early stop in this mode.
- Dataset-native source positions reuse project `wplkBNw5wTUbgLDuPI`; edited XYZ gets an isolated hashed source-geometry profile with only active source spheres, a new project and actual 3D mesh/solves under `experiments/room3d_optimizer/scenarios/`. Levels/listener changes reuse complex fields. Checksums, straight P2 tetra ordering, room bounds/volume and independent cloud-probe checks guard cached fields.
- Current endpoints: `GET /api/room3d/catalog`, `POST /api/room3d/minimize`, `GET /api/room3d/minimize/latest`, generic job GET/resume. Jobs persist under `.runtime/jobs`; one planner coordinator owns SDK mutations and state writes; independent Allsolve source/layout jobs run concurrently within the shared core quota, with batch status polling and verified field harvesting.
- Default is source 1 at dataset XYZ, 90.9691 dB, listener mic1, cap 1, all six placements. The minimum is `ceiling_b`: 66.5966 â†’ 56.2412 dB, 10.3555 dB reduction, after all seven layouts. Actual cloud IDs and full results are in `default_point_result.json` and `point_website_validation.json`.
- Moved-source live test: source 1 X +0.2 m, cap 0, project `IAeg6z_rpMEQNfnDNg`, simulation `jhulmZfEM45jP_YPlk`. Source-level and listener changes reuse this verified field. Two-source and simultaneous two-panel live cases also pass.
- Existing 3D study `experiments/room3d`, project `poAAljkgyCczG-Khjn`, has three-mesh receiver refinement and source-off checks. Preserve its completed jobs. The original 2D model and earlier quiet-area/budget API remain for historical/saved-job compatibility only.

## Physical scope and next work

The model uses the dEchorate 5.705 Ã— 5.965 Ã— 2.355 m room dimensions, 125 Hz, rigid boundaries, omnidirectional spheres and illustrative volumetric damping 0.5 in six finite 0.4 mÂ³ air regions. It reconstructs the measured room dimensions; it is not a textured scan. No continuous placement, room-wide optimum, broadband, calibrated product or dB(A) claim is valid. Uncalibrated normalized dB levels must be labeled as such.

Calibrate source directivity, room boundaries and treatment loss against measured dEchorate RIRs before quantitative measured noise/product claims. Refine relevant optimizer configurations before tight design decisions; the earlier receiver refinement does not certify all new source configurations or arbitrary listeners. Add suitable higher-frequency meshes and eventually transient band-limited pressure time series before claiming room impulse responses.

Preserve job IDs, assumptions, source/mesh provenance, cached-field verification, interactive UI and recovery. Record new SDK findings in `SDK_FEEDBACK.md`. Prefer retaining completed Allsolve jobs over mutating solved physics sets.

## Cloud deployment and parallel execution

- Public site: https://roomvalue.santerihukari.com/, Cloudflare Worker `roomvalue`; any visitor may launch validated simulations. The Worker uses private VPC service `roomvalue-python` through tunnel `roomvalue-pc` to the authenticated loopback bridge on port 8004, which forwards only current website API routes to port 8002. Port 8003 belongs to another application; leave it alone.
- `start-cloud.ps1` starts and verifies the PC services and QUIC connector. Keep PC awake; no automatic Windows startup has been configured. Worker assets and a clearly labeled verified snapshot remain available offline, but POSTs fail and run controls disable while the PC is unavailable.
- `cloudflare/wrangler.jsonc` contains deployment IDs and routes. Origin/tunnel secrets stay under ignored `.runtime/cloudflare`, and the Worker origin secret is stored as a Cloudflare secret. Allsolve credentials remain in the server-only root `.env`. Never print any credential contents.
- Parallel scheduling uses verified 4-core/64 GB runtimes per immutable source/layout simulation. It subtracts account running and reserved cores plus conservative local in-flight core accounting. `Job.refresh_statuses` polls actual cloud statuses collectively. Exact layout minimization and cached-field scientific checks remain unchanged. Result `parallel_execution` distinguishes actual RUNNING peak from queued/in-flight counts and records IDs/observations. Cached requests start no cloud jobs.
