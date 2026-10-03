---
name: allsolve-domain-acoustics
description: >-
  Acoustic, elastic wave, and piezoelectric device modelling in Allsolve. Use when
  modelling transducers, resonators, ultrasonic devices, acoustic-structure coupling,
  PML placement, FBAR, PMUT, piezocomposite, BAW, piezoelectric, or any elastic/acoustic
  wave simulation. Covers architecture patterns, analysis type selection, physics
  coupling, and design tuning.
disable-model-invocation: true
---

# Allsolve acoustic and piezoelectric device modelling

## Choosing the analysis type

| Device class | Analysis type | Reason |
|---|---|---|
| Thin-film bulk resonator (FBAR/BAW) | **Harmonic** | Impedance vs frequency; no time ringdown needed |
| Piezocomposite / bulk transducer | **Transient** | Broadband wavelet → FFT for Tx sensitivity |
| MEMS membrane (PMUT) | **Harmonic** or **Eigenmode** | Harmonic for impedance sweep; eigenmode for resonant frequency |
| Frequency sweep (any resonator) | **Harmonic + variable override on freq** | Cheap per-point solve |
| Natural frequency / mode shape | **Eigenmode** | Cheapest for resonance location |

Rule of thumb: if you need spectral bandwidth or time-domain ring-down, use transient. If you need impedance at discrete frequencies, use harmonic. If you only need the resonant frequency, eigenmode is cheapest.

## Unit cell architecture (periodic devices)

Infinite periodic arrays (transducer arrays, metamaterials) are modelled as a **quarter- or half-unit cell** with symmetry BCs:

```
Symmetry on all lateral faces → infinite periodic array
```

Cell width calculation:
- **1-3 composite**: `cell_w = pillar_w / 2 + kerf_w / 2` (half pillar + half kerf)
- **Square array (PMUT)**: `cell_w = pitch / 2` (quarter cell)

This exploits the in-plane periodicity while keeping DOF count low.

## Standard layer stack pattern

Most acoustic transducers share this z-axis structure:

```
z_max  ┌──────────────────┐  ← Absorbing boundary (PML)
       │    Load medium    │  (water / air)
       ├──────────────────┤  ← Output surface (pressure measurement)
       │    Active layers  │  (piezo + electrodes + matching)
       ├──────────────────┤  ← Excitation surface (electrode)
       │    Backing        │  (absorbing or clamped)
z_min  └──────────────────┘  ← Absorbing boundary (PML) or clamp
```

Key sizing:
- Load medium thickness: **1 wavelength** at centre frequency
- Matching layer: **λ/4** in matching material (starting point for tuning)
- Backing: thick enough that PML absorbs reflections

## Physics coupling pattern

For piezoelectric devices, three physics types couple:

```python
physics_set = project.get_default_physics_set()
ew = physics_set.add_physics(allsolve.Physics.ElasticWaves(target=vol_solid))
aw = physics_set.add_physics(allsolve.Physics.AcousticWaves(target=vol_fluid))
es = physics_set.add_physics(allsolve.Physics.Electrostatics(target=vol_piezo))
```

Coupling interactions:
- **Piezoelectric**: `ElasticWavesPiezoelectricity` on the piezo region (ONE interaction only)
- **Acoustic-structure**: `AcousticWavesAcousticStructureForElasticWaves`

For non-piezoelectric elastic-acoustic problems, omit Electrostatics.

## Boundary conditions by role

| Role | Interaction | Notes |
|---|---|---|
| Lateral symmetry | `ElasticWavesSymmetry` | On all lateral faces of unit cell |
| Absorbing (elastic) | `ElasticWavesPml` (BOX type) | On backing bottom |
| Absorbing (acoustic) | `AcousticWavesPml` (BOX type) | On fluid top |
| Substrate clamp | `ElasticWavesClamp` | Alternative to PML for rigid backing |
| Ground electrode | `ElectrostaticsConstraint("0")` | On one electrode face |
| Drive electrode | `ElectrostaticsLump` with wavelet | On other electrode face |

**PML tips:**
- Use BOX type for rectilinear domains — far more accurate than default AML. Set explicitly:
  ```python
  allsolve.Interaction.AcousticWavesPml(
      name="PML top",
      target=regions.pml_surface,
      acoustic_waves_pml_type=allsolve.AcousticWavesPmlType.BOX,
  )
  ```
- `project.pml_num_layers = N` (4–6 typical) + `project.save()` before creating interactions
- PML is a SURFACE interaction, not a volume — one body of fluid is sufficient

## Excitation patterns

### Transient wavelet (broadband)

```python
allsolve.Interaction.ElectrostaticsLump(
    name="Drive", target=electrode_surface, namespace="drive",
    electrostatics_lump_voltage="V_amp * wavelet(freq, 1.2)",
)
```

`delay=1.2` puts the Ricker wavelet peak at 1.2 periods from t=0.

### Harmonic (single frequency)

For impedance sweeps, use `fundamental_frequency="freq"` in the simulation and sweep `freq` via variable overrides.

Port excitation pattern (script-level):
```python
port.lump.V = qs.port([2, 3])
form += port.lump.V - qs.makeharmonic([2, 3], qs.sn(1), 3)
```

## Transient simulation settings

- **Timestepper**: gen-alpha (`TimestepAlgorithm.GEN_ALPHA`) for 2nd-order wave equations
- **Duration**: 10–15 cycles (`n_cycles / freq`)
- **Steps per cycle**: 20–25 (`1 / (freq * ppc)`)
- **Always set `target_frequency`** for wave problems — omitting it causes poor convergence
- **Solver**: DIRECT for small unit cells; switch to ITERATIVE for >1M DOF

## Standard outputs (transient piezoelectric)

| Output | Expression | Use |
|---|---|---|
| Drive voltage | `drive.V` | FFT numerator for impedance |
| Drive charge | `drive.Q` | Integrate for current |
| Drive current | `dt(drive.Q)` | FFT denominator for impedance |
| Front pressure | `average(reg.front_face, p, 3)` | FFT for Tx sensitivity |
| Front velocity | `average(reg.front_face, dt(compz(u)), 3)` | Mechanical output |

Post-processing: see `allsolve-postprocessing` for FFT, windowing, and KPI extraction.

## Mesh sizing for wave problems

**Elements per wavelength** drives accuracy:

| Medium | Rule of thumb | Notes |
|---|---|---|
| Water (acoustic) | 6 elements / λ | Validated: <0.2% error vs Richardson |
| Solid (elastic) | 6–10 elements / λ_shear | Shear wavelength is shorter |
| Thin layers | thickness / 2.5 | ≥2 quadratic elements through |

For wave devices, consider setting `use_mesh_refiner=False` if the auto-refiner over-resolves thin layers — density should be driven by wavelength, not geometric features. Test with and without to compare DOF counts. See `allsolve-mesh` for general mesh sizing.

## Design tuning methodology

Two-stage parametric tuning for transducer design:

1. **Stage 1**: Sweep resonator thickness → interpolate to target centre frequency (thickness-mode resonance scales as `f ~ 1/t`)
2. **Stage 2**: With tuned thickness, sweep matching layer thickness → maximise bandwidth (start from λ/4 at fc)

Each stage uses the temporary project pattern (see `allsolve-variables-and-overrides` for sweep mechanics and `allsolve-postprocessing` for KPI extraction).

## Reference examples

- `pmut_array/pmut_array_demo.py` — PMUT array ultrasound emission with piezoelectric, elastic, and acoustic wave coupling.

## Gotchas

### Physics
- **ONE piezoelectric interaction, not two.** Do NOT add both `ElasticWavesPiezoelectricity` and a separate electrostatics piezo coupling.
- **`ElectrostaticsLump` requires `namespace`** — omitting it crashes the script generator.
- **Default source is a uniform piston** — do NOT add a window function unless specifically requested.
- **Acoustic-structure coupling is between physics types** — the interaction goes on the acoustic physics, not elastic.

### Mesh
- **Consider `use_mesh_refiner=False`** for wave devices if the auto-refiner over-resolves thin layers — compare DOF counts with and without.
- **Don't make global mesh size fine for thin features** — use per-region refinement. A fine global size explodes large bodies.

### Analysis
- **Harmonic devices (FBAR)**: impedance is computed directly from port V/I — no FFT needed.
- **Transient devices**: must run long enough for complete ringdown (10–15 cycles minimum). Incomplete ringdown → spectral leakage; use right-hand Hanning window.
- **Eigenmode is cheapest for finding resonant frequency** — no damping or sweep needed, one solve per mesh. Use when only frequency matters (not amplitude).
