# RoomValue: minimize noise at a chosen 3D point

Local website: <http://127.0.0.1:5175/>. API: <http://127.0.0.1:8002/docs>. Run `powershell -ExecutionPolicy Bypass -File .\start-local.ps1` from this folder to restart missing services. Allsolve credentials stay on the local server.

The website uses a real 3D Allsolve model of the dEchorate laboratory room. Choose up to three sound sources, edit their XYZ positions and source levels in dB, select one listening point, and enter the maximum number of available panels. Enable or exclude six wall/ceiling candidate positions. The optimizer minimizes the simulated sound pressure level at the listening point across every allowed subset from zero through the panel limit. Exact ties prefer fewer panels. There is no budget or cost constraint in this mode.

## Room and dataset

The [dEchorate subset](datasets/dechorate/README.md) supplies the calibrated **5.705 Ãƒâ€” 5.965 Ãƒâ€” 2.355 m** laboratory room dimensions and source/microphone coordinates. The local subset includes four original measured 48 kHz SOFA impulse-response files, coordinate annotations, MIT attribution, pinned checksums and compact exports. The model reconstructs this room geometry from the dataset dimensions; it is not an arbitrary cafeteria model or a textured scan.

The initial [3D experiment](experiments/room3d/README.md), project `poAAljkgyCczG-Khjn`, remains unchanged. Its untreated/east-wall/ceiling/source-off cases and three-mesh receiver refinement check are retained. The website's independent [placement project](https://allsolve.quanscient.com/#/projects/wplkBNw5wTUbgLDuPI/model) uses quadratic tetrahedral acoustic fields at **125 Hz** and six finite damping regions.

## Decibels and objective

The displayed normalized sound pressure level is `20 log10(p_RMS / 20 microPa)`, using the [NIST sound-pressure reference](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-8). Each source input specifies the RMS pressure level at its 0.08 m spherical emitter boundary. A source level of 90.9691 dB corresponds to the existing 1 Pa peak basis. Changing a source level by 10 dB changes its pressure by a factor of sqrt(10). Independent source powers are summed before conversion to dB.

These are normalized model levels, with assumed omnidirectional sources, rigid room boundaries and illustrative panel damping. They are not calibrated measured noise, A-weighted dB(A), or commercial panel performance. Source directionality and room/treatment loss must be fitted to measured data before making those claims.

Panel placement can alter room resonances, so more panels need not lower pressure at a particular point. The optimizer evaluates all permitted counts, including the untreated room, and chooses the minimum listener RMS pressure. Its optimum applies to the six fixed candidate locations, entered source configuration, one listener and modeled frequency. It does not optimize continuous panel coordinates or whole-room/broadband quietness.

## Real solves and reuse

[`experiments/optimizer3d.py`](experiments/optimizer3d.py) creates a separate immutable Allsolve harmonic solve for every source/layout combination. Multiple panels are solved together; reductions from individual panels are not added. Full complex FEM fields are downloaded, checked against independently exported cloud point probes, and cached with checksums. Quadratic tetrahedral interpolation samples the requested listener inside the solved room without nearest-node approximation or extrapolation.

Changing source levels, listener XYZ, allowed placements or the panel limit reuses matching completed fields. Moving a source creates an isolated geometry/cache under `experiments/room3d_optimizer/scenarios/`, with only the active source spheres at the requested positions. It creates and verifies a new 3D mesh and missing source/layout solves. Returning to dataset positions reuses the original project. Source spheres must be inside the room and separated from each other, the listener and allowed panel volumes.

API jobs persist under `.runtime/jobs`; interrupted searches can resume. Current endpoints are `GET /api/room3d/catalog`, `POST /api/room3d/minimize`, `GET /api/room3d/minimize/latest`, `GET /api/jobs/{id}` and `POST /api/jobs/{id}/resume`. The CLI defaults to point minimization; `--legacy-area` retains the earlier area-target mode for saved jobs.

## Verified current example

For source 1 at its dataset position and 90.9691 dB boundary level, listener mic1 at XYZ **[0.80316092, 3.83141445, 1.04391528] m**, and at most one panel:

- All seven layouts (untreated and six single-panel positions) were evaluated.
- Untreated listener level: **66.5966 dB**, or 0.04274273 Pa RMS.
- Selected layout: **Ceiling Ã‚Â· east**, slot `ceiling_b`, at corner **[3, 2, 2.155] m**, size **[2, 1, 0.2] m**.
- Optimized listener level: **56.2412 dB**, or 0.01297445 Pa RMS; modeled reduction **10.3555 dB**.
- Untreated cloud simulation: `ROY0ZBA4DLHEv3KqPe`; selected simulation: `n74505QJ9nlwFN4Mi_`.
- Original optimizer mesh: 332,020 tetrahedra, volume 80.141415375 mÃ‚Â³, maximum edge 0.363132 m, quadratic interpolation.

`experiments/room3d_optimizer/default_point_result.json` records the full result. `point_website_validation.json` records seven explicit live API checks: the default search, a moved-source new geometry, dB scaling with cache reuse, listener movement with field reuse, two independent sources, all four subsets of two ceiling candidates, and restored defaults. The moved-source project is `IAeg6z_rpMEQNfnDNg`, with actual source solve `jhulmZfEM45jP_YPlk`.

Offline validation uses 57 optimizer tests, 21 API tests, 9 bridge tests and 25 Worker tests. The frontend build validates TypeScript and production bundling. Live checks are explicit and separate from unit-test discovery.

## Retained experiments and further work

The earlier 3D quiet-area mode remains at `POST /api/room3d/optimize` for saved jobs and scientific history. It searches for the fewest affordable objects that satisfy sampled area targets. This is separate from the current website objective. Legacy 2D comparison and `VERIFIED_COMPARISON.json` remain feasibility experiments only.

The first 3D study's receiver mesh refinement does not certify every optimizer location, source configuration and damped layout. Before quantitative design use, refine each relevant scenario, calibrate source directivity and boundary/treatment loss against measured dEchorate impulse responses, and add suitable meshes at additional frequencies. A transient band-limited simulation is required before reporting room impulse responses or decay metrics.

[SDK_FEEDBACK.md](SDK_FEEDBACK.md) records concrete Allsolve SDK findings. This work stays within RoomValue and does not modify teammate projects or the shared Hackathon-PhysicsSimulator repository.

## Cloud site and parallel search

The public site is https://roomvalue.santerihukari.com/. Cloudflare serves the website and connects privately to this PC; Python submits the FEM solves to Allsolve and verifies/caches their results. Any visitor can launch a run when the PC is connected. A clearly labeled saved example remains viewable offline. See [Cloudflare setup](cloudflare/README.md) and run `start-cloud.ps1` after restarting the PC.

The planner enumerates independent source Ã— panel-layout cases, starts missing simulations concurrently within shared core availability, and batch-polls their actual statuses. Each case uses four cores / 64 GB. The current request supports up to 192 basis cases (three sources Ã— 64 layouts). With six slots and a three-panel maximum, there are 42 layouts; two sources need 84 basis cases. Panel availability and feasible locations remain the search constraints; no budget has been introduced.

One coordinator keeps SDK mutations and cache writes safe. Verified completed fields are reused without another cloud run. Result `parallel_execution` records actual observed simultaneous RUNNING jobs, account quota, core allocation, cache counts and job/simulation IDs. The live website reports these counts rather than assuming that submitted or queued cases are already running.

The resumed live job `e4b02cec-6192-40e3-bd5e-93271c44dbb7` completed 84 basis cases / 42 layouts for two sources, listener [1, 5, 1.5] m and a three-panel cap. It observed 35 simultaneous RUNNING jobs (140 executing cores), started 66 fresh jobs and reused 17 verified fields plus one existing completed cloud run. The cloud phase ran from 12:29:45 to 12:32:42 UTC; download/validation followed. The minimum used ceiling_a, ceiling_b and east_b, 85.8594 to 60.6876 normalized dB. `parallel_website_validation.json` records public job observations and all result provenance; `cloudflare/deployment-validation.json` records online/offline production checks, with screenshot `cloudflare/hosted-planner.jpg`.
