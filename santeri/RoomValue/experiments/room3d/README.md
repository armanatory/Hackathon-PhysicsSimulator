# RoomValue 3D measured-geometry experiment

This experiment uses the calibrated **5.705 × 5.965 × 2.355 m** dEchorate room and measured source/receiver coordinates in a genuine three-dimensional Allsolve Acoustic Waves model. The room has a floor, ceiling and four walls, and a volumetric tetrahedral mesh. The existing web app's separate 2D feasibility experiment remains available.

Dataset files, provenance, license, coordinate interpretation and measured recordings are in [`../../datasets/dechorate/README.md`](../../datasets/dechorate/README.md). dEchorate is a controlled laboratory room for validating the modeling pipeline. A real cafeteria model will need a measured floor plan, occupancy/source scenario and surface properties.

## Model

- Frequency: **125 Hz**, harmonic acoustic pressure, quadratic finite elements.
- Air density: assumed **1.2 kg/m³**. Sound speed: dataset value **346.98 m/s**.
- Source: 0.08 m radius sphere with a **1 Pa `sn(1)` pressure constraint** on its surface, centered at dataset source `src1`: `(1.89407487, 4.52190448, 1.44818390)` m.
- Receiver `mic1`: `(0.80316092, 3.83141445, 1.04391528)` m.
- Receiver `mic26`: `(3.08212703, 3.42108318, 1.49048013)` m.
- Untreated exterior boundaries: natural rigid reflecting acoustic walls, floor and ceiling. These approximate geometry; the measured room's carpet floor and other surface absorption have **not** been calibrated into the FEM boundary model.
- East wall candidate: box from `(5.505, 2.0, 0.65)` m, size `(0.2, 2.0, 1.0)` m.
- Ceiling candidate: box from `(2.0, 2.0, 2.155)` m, size `(2.0, 1.0, 0.2)` m.
- Both treatment regions have **2 m² face area and 0.4 m³ volume**, homogeneous air properties, and illustrative Allsolve volumetric damping value **0.5** when that candidate is active. This parameter is not a measured absorption coefficient, NRC, impedance or commercial panel property.

All candidate partitions exist in every mesh. Only the selected candidate has damping. Separate named physics sets keep the source, receiver coordinates and mesh fixed while comparing baseline, east wall and ceiling. Another set drives the source with zero pressure for the source-off check. Completed simulations are reused on a subsequent command; new mesh levels create new simulations without destroying earlier results.

The measured speaker is directional; the normalized spherical emitter is an approximation. Dataset impulse responses are stored as measurements and are not presented as output of this harmonic simulation. A 125 Hz pressure comparison does not establish broadband cafeteria noise reduction, reverberation time, speech intelligibility or product performance.

## Run and inspect

From this directory, in PowerShell:

```powershell
& 'F:\H4H quanscient\.venv\Scripts\python.exe' .\run_room3d.py
& 'F:\H4H quanscient\.venv\Scripts\python.exe' .\render_report.py
```

Credentials are read server-side from the workspace `.env`; they are never placed in the dataset, frontend, model configuration or report. Required packages are in `requirements.txt`.

`--coarse-only` harvests or runs the first mesh level. `--prepare-only` creates the geometry, material, meshes and named physics sets without launching a mesh or simulation. The default runs/harvests the 0.32 m and 0.24 m levels, and adds a 0.18 m level if their pressure differences exceed the screening tolerance. Higher-resolution simulations use a 4 core / 64 GB node. Existing failed jobs are preserved; a fine-mesh job that failed on the initial 10 GB node has one separately named 64 GB replacement. The driver checks shared core availability before launching work.

The saved `model_config.json` is an exported geometry/material/initial-mesh definition; the driver regenerates it from `config()` rather than reading manual JSON edits. The local `state.json` records project, physics-set, mesh and simulation IDs for resuming the same project. Its model fingerprint also includes source expression, receiver coordinates, frequency, damping, field order and dataset checksum. Changes to those inputs require a separate experiment directory to preserve useful results.

`VERIFIED_3D.json` contains actual cloud pressure components, amplitudes, job IDs, mesh metrics, source-off results, relative receiver changes and the refinement check. Values use `20 log10(|p_candidate| / |p_baseline|)`; a negative value means a lower pressure amplitude at that particular receiver and frequency. They are normalized amplitudes in Pa, not calibrated loudspeaker SPL.

Mesh verification uses the downloaded Gmsh file: XYZ bounds, positive-height 3D tetrahedra, positive element volumes, total volume versus the room, and actual edge sizes. Source/receiver coordinates and each active region are checked before solving. Successive mesh pressure differences have an explicit **0.5 dB** screening tolerance; the final check compares the two finest completed levels and preserves earlier differences. Consult the actual reported pass/fail result before treating a ranking as stable. A rigid rectangular room mode lies near 125 Hz, making this check particularly relevant.

The original field output is saved under `outputs/coarse_field` or `outputs/fine_field` as Allsolve VTKHDF. `room3d.png` shows the geometry and actual coordinates. `measured_ir.png` shows the original measured recordings. A pressure slice, when present, is sampled from an actual cloud field rather than an illustrative heat map.

## Further validation

Use the measured RIR direct-arrival timing as an initial coordinate/sound-speed check. Frequency-dependent wall impedance or a calibrated porous-region model, plus measured source directivity, are needed before comparing measured and FEM transfer functions quantitatively. Then run a band-limited transient excitation, check arrival times and decay, and increase bandwidth and duration as the mesh/compute budget permits. The current solve is harmonic and does not produce a simulated room impulse response.

Primary references: [dEchorate dataset](https://zenodo.org/records/4626590), [author repository](https://github.com/Chutlhu/dEchorate), [SOFA data mirror](https://www.sofaconventions.org/data/database/dechorate/), [Allsolve Acoustic Waves](https://allsolve.quanscient.com/documentation/using-allsolve/physics/acoustic-waves).

## Completed validation, 3 October 2026

All **ten** required cloud simulations succeeded: baseline and two placements on each of three meshes, plus one source-off control. One initial fine-mesh wall solve failed on the 10 GB runtime and is retained alongside its successful 64 GB replacement. The exact cause was not reported by Allsolve.

| Mesh | 3D tetrahedra | Largest edge | Minimum elements per wavelength |
| --- | ---: | ---: | ---: |
| Coarse | 68,355 | 0.53050 m | 5.23 |
| Fine | 159,387 | 0.40222 m | 6.90 |
| Refined | 274,035 | 0.29819 m | 9.31 |

Every mesh spans the calibrated XYZ bounds and sums to **80.141415375 m³**. Source-off receiver pressure is exactly zero. The maximum absolute receiver-amplitude change between the fine and refined meshes is **0.25001 dB**, passing the 0.5 dB screening tolerance. Relative candidate/baseline differences change by at most **0.45307 dB**. This is a finite refinement check rather than an exact continuum error bound.

These final 125 Hz changes come from the **illustrative loss proxy**, with the source and rigid-room assumptions above. They are not measured treatment effectiveness:

| Placement | mic1 relative pressure | mic26 relative pressure |
| --- | ---: | ---: |
| East wall | −6.87 dB | −2.13 dB |
| Ceiling | −18.42 dB | −17.89 dB |

The ceiling candidate gives the lower pressure at both receivers at this frequency, and its ranking survives every mesh level. Quantitative treatment recommendations still need calibrated boundary/source properties and wider frequency coverage.

The pressure preview now uses the **refined** cloud field. Its interpolated mic1 value, **0.06091509642 Pa**, matches the independent receiver output to numerical precision; the whole interior slice is covered. `figure_validation.json` records the field and mesh IDs and interpolation checks.
