# MetaSense case thread instructions

Own this case in `F:\H4H quanscient\MetaSense`. Keep the work separate from `RoomValue`, `ExhaustLab`, `beer_cooling_app`, and the three-teammate `Hackathon-PhysicsSimulator` repository. Do not edit or push the shared repository as part of this case. Keep Allsolve keys server-side; read the already saved root `.env` or a private local environment file without printing secrets.

## User goal

Build a React + TypeScript + Vite / Python 3.11 + FastAPI app for inverse design of a dielectric metasurface protein sensor. Use streptavidin–biotin as the initial binding example. Keep `surrogate_demo` and `allsolve` modes explicit. Never infer optical properties from molecular coordinates or label synthetic outputs as experiments or Allsolve results. The user will provide more physics details and acceptance criteria.

## Current state

- UI: <http://127.0.0.1:5174/>; API: <http://127.0.0.1:8001/docs>. `start-local.ps1` restarts missing services.
- The Python 3.11 dependencies and frontend build were checked. The surrogate is a clearly labeled synthetic Lorentzian model. Allsolve mode deliberately returns HTTP 501; `backend/app/allsolve_adapter.py` has no real optical solve.
- `README.md` describes modules, current assumptions, and local run instructions.
- The real Allsolve normal-incidence slab benchmark is validated on coarse/fine meshes at 1000 nm: fine R=0.1490303333, T=0.8511445897 versus Fresnel 0.1479289941/0.8520710059. `simulations/slab_validation/results/report.json` includes fixed gates, raw outputs, cloud IDs, and source hashes. `GET /api/validation/slab` and the UI Optical validation panel expose it without launching jobs.
- Use the verified custom `source_readout.py`: order-2 electric field requires explicit periodic multiplier order 2. Generated default order 0 gave large lateral field jumps and failed R/T. Same-mesh order-2 runs and HDF audits confirm the repair. Both generated FORMULATIONS and SOLVE sections are disabled; the hook constructs and solves the whole formulation. Harmonic 2 is sine, 3 is cosine. Fine solve succeeded on 4 cores/64 GB after 3 cores/10 GB failed. Successful final solves retain null-pivot warnings; inspect constraints before extending the formulation. Do not overwrite or rerun completed jobs. See the benchmark README and `SDK_FEEDBACK.md`.
- User is researching a simpler detection task. Keep assay metadata unchanged until they choose it; the slab benchmark uses assumed constant n and is independent of biology.
- Current code treats streptavidin as the surface receptor and biotin as the analyte. Biotin is a small molecule, so this is not yet a protein-analyte sensor. If the app pitch is protein detection, explicitly evaluate immobilized biotin with streptavidin as the analyte; justify and document the assay orientation before changing the model.

## Next implementation priority

1. The **normal-incidence slab excitation and power readout are verified**. Preserve their evidence and reuse the source/boundary conventions. The SDK has no ready normalized metasurface R/T helper; the slab runner implements it. Its current vacuum, nonmagnetic, subwavelength, normal-incidence assumptions must be reconsidered for a different exterior, substrate, oblique incidence, or propagating diffraction orders.
2. Add a periodic dielectric pillar/unit-cell geometry with justified wavelength-dependent material permittivity or refractive index data, physically meaningful mesh resolution, and a convergence check. Validate any substrate/open-boundary changes and the resonance spectrum before enabling the sensor pipeline.
3. Represent receptor/analyte binding with an explicit assumed or measured effective adlayer thickness/index (or other justified perturbation). Keep the biological occupancy model separate from optical constants. Simulate bound and unbound spectra with a limited wavelength sweep, then define the detector observable and a noise/calibration model.
4. Enable `allsolve` only when real cloud jobs, field/power outputs, model provenance, and sanity checks are retrievable through the backend. Inverse-design ranking must use those outputs; never substitute the surrogate after a failed job.
5. Record concrete SDK friction and suggested fixes for judging.

Current official references: [EM Waves](https://allsolve.quanscient.com/documentation/using-allsolve/physics/em-waves), [materials](https://allsolve.quanscient.com/documentation/using-allsolve/materials/working-with-materials), and [Allsolve SDK](https://allsolve.quanscient.com/documentation/reference/allsolve-sdk).
