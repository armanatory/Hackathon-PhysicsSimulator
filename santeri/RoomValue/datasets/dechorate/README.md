# dEchorate measured 3D reference subset

This bounded fixture supplies real measured room impulse responses, calibrated
room geometry, and exact source/receiver heights for RoomValue's first 3D model.
The controlled laboratory is useful for verifying import, geometry, and later
time-domain work. It is not a measured school or cafeteria, and importing it
does not establish agreement between the FEM model and measurements.

The calibrated inner dimensions are **5.705 × 5.965 × 2.355 m**, from the
annotation HDF5 and each SOFA's `RoomCornerB`. The article rounds the nominal room
to 6 × 6 × 2.4 m. We use source `src1`, the directional Avanton MIXCUBE, and
microphones `mic1` and `mic26` at their calibrated absolute Cartesian XYZ
positions. The original measurements for all ten microphones in arrays 1 and 6
are retained. Each SOFA contains five measured one-second FIRs at 48 kHz.

The two measured conditions are `011111` (reflective ceiling and four walls,
absorbent carpet floor) and `000000` (all surfaces in absorbent mode). The six
digits follow **floor, ceiling, west, south, east, north**, with 0 absorbent and 1
reflective. Neither selected condition includes furniture. Thus the reflective
condition is not a completely rigid room. The published material descriptions
are recorded in the manifest, but do not provide a measured complex impedance
for commercial panels.

## Reproduce

From the workspace, with `numpy` and `h5py` installed:

```powershell
& 'F:\H4H quanscient\.venv\Scripts\python.exe' 'F:\H4H quanscient\RoomValue\datasets\dechorate\fetch_dataset.py'
```

This fetches four small SOFA files and one 30 kB annotation file, verifies their
pinned SHA256 checksums, and regenerates `manifest.json` plus two convenience
CSVs. Add `--offline` to regenerate from existing local downloads. URLs, exact
checksums, original FIR shapes, coordinate checks, and diagnostics are captured
in the manifest. Only this directory is written, and its size stays below 8 MiB.

The CSVs hold `mic1` and `mic26` at 4 kHz after a centered 241-tap Kaiser-window
1 kHz low-pass filter and decimation. They are compact convenience derivatives
for plotting. Filtering can ring before an arrival and at record edges; retain
the unchanged SOFA measurements for validation. FIR amplitudes are not
calibrated pressure in pascals. The fullband T20 values are screening diagnostics
without octave filtering or noise compensation, and are not ISO-validated room
acoustic parameters.

## Coordinate and metadata caveats

- **`ReceiverPosition` in these dEchorate SOFAs is already absolute**. Its values
  match `microphones` in `dEchorate_annotations.h5`. Do not add `ListenerPosition`
  or rotate by `ListenerView`; that would move the microphones incorrectly.
- The origin is the lower southwest corner, with Z upward: west/east are
  x=0/Lx, south/north y=0/Ly, floor/ceiling z=0/Lz. The author code verifies the
  corresponding image-source directions.
- `RoomDescription` contains a stale `room_code:020002` furnished-room string
  even in the selected files. Room state follows the filename, matching `Title`,
  and the article's state table. `RoomTemperature` and `RoomVolume` are zero
  placeholders; use the article's 24 °C, 80% RH, 346.98 m/s and derived volume.
- Source `src1` is directional. A solver point monopole is an illustrative
  source approximation until its radiation and excitation are matched.
- Absorber and reflective states have material descriptions, but this subset
  does not contain calibrated complex boundary impedance. Solver damping,
  treatment effectiveness, and prices must remain labeled assumptions.

## Why this dataset

| Dataset | Strength | Limitation for this first setup |
| --- | --- | --- |
| dEchorate | Calibrated 3D geometry, echo annotations, measured surface configurations, and small independently downloadable SOFA files; MIT notice in files | Laboratory fixture; source directivity and impedance still need matching |
| ACE corpus | Measured RIRs in seven rooms including room dimensions and approximate source/microphone positions | Registration required; smallest single-channel archive is 417 MB; coordinates are approximate; CC BY-ND 4.0 |
| BRUDEX | Measured RIRs for 36 distributed microphones, 12 sources and three reverberation conditions | Signal-processing/hearing-aid focus, rather than matched numerical boundaries; CC BY-NC 4.0 |

[BRAS](https://doi.org/10.14279/depositonce-6726.3) is a useful follow-on benchmark
for a seminar-room simulation with boundary and directivity information. The
[TU/e derivative data description](https://research.tue.nl/en/datasets/comparing-room-acoustics-simulation-tools-dataset-for-reproducing/)
also identifies simplified CR2/CR4 room models, material data, and source/receiver
XYZ positions. This is a more demanding next calibration case.

## Primary sources and attribution

- [dEchorate article](https://arxiv.org/html/2104.13168), especially sections 2.1,
  2.2 and material Table 8; DOI: 10.1186/s13636-021-00229-0.
- [Original dataset record](https://zenodo.org/records/4626590), DOI:
  10.5281/zenodo.4626590. The full original corpus is not downloaded here.
- [SOFA small-file repository](https://www.sofaconventions.org/data/database/dechorate/).
- [Author constants](https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/__init__.py)
  and [coordinate construction](https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/main_geometry_from_echo_calibration.py).
- [Author SOFA builder](https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/main_build_sofa_database.py)
  writes absolute microphone positions and the MIT notice into SOFA files.
- [ACE corpus, Imperial College London](https://www.imperial.ac.uk/speech-audio-processing/projects/ace-challenge/).
- [BRUDEX article](https://arxiv.org/html/2306.08484) and
  [dataset DOI](https://doi.org/10.5281/zenodo.7986447).

Di Carlo, D.; Tandeitnik, P.; Foy, C.; Bertin, N.; Deleforge, A.; Gannot, S.
“dEchorate: a calibrated room impulse response dataset for echo-aware signal
processing,” EURASIP Journal on Audio, Speech, and Music Processing, 2021.

The downloaded SOFA files explicitly carry **MIT**, copyright © 2019 Diego Di
Carlo. The full notice is preserved in `LICENSE.dataset.txt` and `manifest.json`.
