# Liquid discriminator optimizer

This case searches a dielectric ridge grating for the largest **absolute reflectance difference at one common wavelength** between two specified liquid indices:

```text
score = max over sampled lambda |R_A(lambda) - R_B(lambda)|
```

R is a power fraction. The search uses real Allsolve geometry, meshes, and harmonic EM jobs. The independent TE RCWA implementation in `reference.py` verifies the selected readout; its output is never substituted for cloud results. A completed cloud job alone is insufficient: the finalist must pass the fixed checks below. The completed run below provides numerical optimization evidence; experimental performance and fabrication remain unvalidated.

## Completed run evidence

Job `5caa299a62fb450da3c57baa1eec3e36` completed on 2026-10-03 at 15:39 Helsinki time with `synthetic=false` and winner `validated=true`. The [saved report](../../casesdata/liquid_discriminator/jobs/5caa299a62fb450da3c57baa1eec3e36/report.json), adjacent `state.json`, and [Allsolve project](https://allsolve.quanscient.com/#/projects/lz4cS2ePQRJW0zw-ZR/model) retain raw outputs, mesh checks, source hashes, and cloud IDs. Inputs used the defaults below with a 256-core cap.

All 616 solve points completed across 10 batches: 528 search, 84 dense, two fine, and two clearance points. The search had 18 valid paired candidates out of 24. Candidate 6 had a larger coarse score, but 39 of its 42 dense points failed the fixed energy, cross-polarization, or coherent/local-flux checks, excluding it from finalist selection. Candidate 3 passed every finalist check, including downloaded mesh geometry matching the request.

| Verified candidate 3 | Value |
| --- | --- |
| Period / fill factor / ridge height | 540.408914 nm / 0.602723375 / 199.798994 nm |
| Ridge width / gap / film thickness | 325.717085 nm / 214.691830 nm / 100 nm |
| Common wavelength | 900 nm |
| Fine R, Water n = 1.33 | 0.2996690282 |
| Fine R, Glycerol–water n = 1.38 | 0.4607810144 |
| Fine absolute contrast | 0.1611119861 power fraction |
| Largest fine energy residual magnitude | 0.0002995014 |

| Measured finalist difference | Value | Fixed limit |
| --- | --- | --- |
| Fine versus search R, maximum over liquids | 0.0006822202 | 0.01 |
| Fine versus search contrast | 0.0012717418 | 0.01 |
| Clearance 1000 versus 1500 nm R, maximum | 0.0012520489 | 0.005 |
| Fine R versus independent TE RCWA, maximum | 0.0004733004 | 0.015 |
| RCWA order 9 versus 13 R, maximum | 0.0000208694 | 0.002 |

This is the best validated sampled design for this request. Its selected wavelength lies at the 900 nm band edge; the run establishes neither a global optimum nor performance outside the searched band. Search/dense curves remain on the search mesh; the fine and clearance evidence each covers the selected wavelength for both liquids.

## Start

From `F:\H4H quanscient\MetaSense`:

```powershell
.\start-local.ps1
```

Open the [local app](http://127.0.0.1:5174/), set the inputs, and select **Optimize with Allsolve**. The button starts a durable backend worker. Inputs remain fixed while its job is queued, running, or verifying; reopening the app restores the latest saved job. Credentials remain server-side in the private root `.env` or inherited environment.

The API contract is:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/optimization/config` | Availability, default request, supported limits, model |
| `POST /api/optimization/jobs` | Start an optimization; return its job envelope |
| `GET /api/optimization/jobs/latest` | Latest saved job, or JSON `null` |
| `GET /api/optimization/jobs/{id}` | Current job, report, progress, and public cloud IDs |

The backend starts `runner.py run --job-dir <saved-job-folder>`. Job requests, state, report, point outputs, and cloud IDs are retained under `casesdata/liquid_discriminator/jobs/<id>/`; private worker and failure logs are not exposed through the API. A distinct request is rejected while another optimization is active; an identical active request reuses its job.

## Inputs and geometry

| Input | Default |
| --- | --- |
| Liquid A | Water label, constant real n = 1.33 |
| Liquid B | Glycerol–water label, constant real n = 1.38 |
| Period p | 450–550 nm |
| Fill factor w/p | 0.30–0.70 |
| Ridge height h | 80–220 nm |
| Continuous film | Fixed 100 nm per search; editable 50–250 nm |
| Minimum width, gap, and ridge height | 50 nm; editable 20–100 nm |
| Vacuum wavelengths | 900–1100 nm, 11 paired samples |
| Search candidates / seed | 24 / 42 |
| Parallel core cap | 64, bounded to 4–256 and available organization quota |

The model has rectangular Si₃N₄ ridges extending along y on a continuous Si₃N₄ film and fused-silica substrate. Liquid fills the ridge gaps. The structure repeats along x; the invariant-y computational period is 100 nm. Normal TE illumination has E_y along the ridges and propagates +z from liquid toward glass. Exterior clearance is initially 1000 nm on each side.

Material indices use the real wavelength-dependent Sellmeier models attributed to [Luke et al., 2015, Si₃N₄](https://doi.org/10.1364/OL.40.004823) and [Malitson, 1965, fused silica](https://doi.org/10.1364/JOSA.55.001205). Absorption is omitted. Liquid labels do not assign a glycerol concentration, temperature, dispersion, or measured optical constant; their explicit constant n values define the comparison.

The backend allows candidate counts 1–128, wavelength samples 3–41, and wavelength endpoints within 800–1600 nm. Supported geometric domains are p = 100–1000 nm, fill = 0.05–0.95, and h = 20–800 nm. The complete bounds must satisfy minimum ridge/gap/height constraints and `p_max × max(n_A, n_B, 1.46) <= 0.9 × lambda_min`, giving a 10% margin below the exterior diffraction cutoff.

## Cloud method and result display

The optimizer samples period, fill factor, and height with a seeded Latin hypercube. Locked `SPECIFIC_VALUES` rows keep geometry × liquid × wavelength values paired; they do not form an unintended Cartesian product. Geometry overrides produce tetrahedral meshes. Each downloaded physical mesh is checked against the requested period, width, height, film, and exterior extents before solving. The 1 nm CAD region-selection tolerance is smaller than every allowed feature; the coordinate check tolerance is 0.001 nm. Each batch contains at most `floor(core_cap / cores_per_child)` solve points. Search and dense stages use 3-core fast-start children; fine and clearance verification use 4 cores / 64 GB. Allsolve queues children against shared organization capacity.

The custom formulation solves harmonic Maxwell FEM with second-order H(curl) electric fields, explicit zero-phase periodic multiplier order 2, and matched-index absorbing admittance boundaries. Incident forcing is a polarized plane-wave boundary term. Harmonic 2 is sine, harmonic 3 is cosine, and peak phasors use `E_cos - i E_sin` with `exp(+i omega t)`. Generated FORMULATIONS and SOLVE sections are disabled so the custom formulation and solve run once. See [Allsolve EM waves](https://allsolve.quanscient.com/documentation/using-allsolve/physics/em-waves) and [SDK reference](https://allsolve.quanscient.com/documentation/reference/allsolve-sdk).

Coherent zeroth-order forward/backward amplitudes come from surface-averaged tangential E/H in homogeneous exterior media. R/T are normalized by forward incident power with the appropriate exterior impedances. Total Poynting flux, local power decomposition, cross polarization, material ratios, and incoming-wave contamination provide additional checks.

Only candidates with complete valid paired spectra are ranked. The top two search candidates receive 21 local wavelength samples on the search mesh. The selected common wavelength is then solved for both liquids on a finer mesh and with clearance increased from 1000 to 1500 nm. The UI labels search/dense curves as search-mesh spectra; separate fine-readout markers represent the actual verified wavelength. A two-point liquid verification is not a fine-mesh wavelength sweep. This is a best-of-N search, with no global-optimum guarantee.

## Fixed acceptance gates

All required outputs must be finite, powers nonnegative, incident power positive, and submitted geometry/material/wavelength metadata consistent with the returned solve. Thresholds are fixed, rather than fitted to the observed winner.

| Check | Requirement |
| --- | --- |
| Lossless energy balance | `abs(1 - R - T) <= 0.02` |
| Incident normalization | Error from specified incident power ratio 1 ≤ 0.02 |
| Exit backward power / incident power | ≤ 0.001 |
| Cross-polarized power / incident power | ≤ `1e-4` |
| Material-index ratio consistency | Error from 1 ≤ `1e-8` |
| Coherent versus local net flux | Difference / incident power ≤ 0.005 |
| Wavelength/frequency consistency | Returned ratio consistent with 1 |
| Fine versus search R at selected wavelength | Absolute change ≤ 0.01 for each liquid |
| Fine versus search contrast | Absolute change ≤ 0.01 |
| 1000 versus 1500 nm clearance R | Absolute change ≤ 0.005 for each liquid |
| Fine Allsolve R versus independent TE RCWA R | Absolute error ≤ 0.015 for each liquid |
| RCWA order 9 versus 13 convergence | Absolute R change ≤ 0.002 |

The report's `best_design.verification` records the measured differences, limits, and pass status. Failure preserves the outputs and cloud IDs and leaves the design unvalidated. Mesh and boundary evidence must come from the actual job; local formula tests do not establish cloud convergence.

Local checks run without cloud solves:

```powershell
.\.venv\Scripts\python.exe -m pytest .\simulations\liquid_discriminator -q --basetemp .\.runtime\liquid-tests
```

This ideal infinite periodic, lossless model does not establish fabrication tolerances, finite-aperture behavior, surface roughness, angular/polarization errors, detector noise, concentration calibration, or experimental detection limits. Those require separate measured inputs and validation.
