"""Fetch a bounded, reproducible dEchorate subset and export 3D metadata.

Run with Python containing numpy and h5py. The original SOFA measurements
remain unchanged. Only this directory is written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import urllib.request

import h5py
import numpy as np


BASE_URL = "https://www.sofaconventions.org/data/database/dechorate/"
FILES = {
    "dEchorate_annotations.h5": "1c2810a2dc3870c75276a4b954c36b884e31b291483190634b2030040061317e",
    "dEchorate_room011111_src1_arr1_mics1-5.sofa": "ec8a4f2305b4b170e7ec9b5dab4f51695d861b462125e3119e2a33fd20813fa1",
    "dEchorate_room011111_src1_arr6_mics26-30.sofa": "a6298fad1510ed7bd13ac19773a3e0ebf85d1334f7a3df6679e13fa44c93f109",
    "dEchorate_room000000_src1_arr1_mics1-5.sofa": "26a76bbafb80af0dc29a6838ae9d8fdc4846249c8a4e60a2ef87d13b87496b07",
    "dEchorate_room000000_src1_arr6_mics26-30.sofa": "46f7f20f2e54561f5d606ea7307b6eab64cbfd73e5cb14a164184253203d4c1e",
}
SURFACE_ORDER = ["floor", "ceiling", "west", "south", "east", "north"]
MIC_GROUPS = {1: list(range(1, 6)), 6: list(range(26, 31))}
SELECTED_MIC_IDS = [1, 26]
MAX_BYTES = 8 * 1024 * 1024


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(value):
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8")
    return str(value)


def download(directory: Path) -> list[dict]:
    records = []
    for name, expected in FILES.items():
        path = directory / name
        if not path.exists():
            request = urllib.request.Request(
                BASE_URL + name, headers={"User-Agent": "RoomValue-acoustic-benchmark/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise RuntimeError(f"Unexpectedly large dataset file: {name}")
            digest = hashlib.sha256(raw).hexdigest()
            if expected and digest != expected:
                raise RuntimeError(f"SHA256 mismatch: {name}")
            path.write_bytes(raw)
        digest = sha256(path)
        if expected and digest != expected:
            raise RuntimeError(f"SHA256 mismatch: {name}; remove the changed local file and retry")
        records.append({"name": name, "url": BASE_URL + name, "bytes": path.stat().st_size, "sha256": digest})
    return records


def diagnostics(ir: np.ndarray, fs: float, distance: float) -> dict:
    """Screening diagnostics on the original measured FIR, without calibration."""
    energy = np.cumsum(np.square(ir[::-1]))[::-1]
    peak = int(np.argmax(np.abs(ir)))
    direct_time = distance / 346.98
    start = max(0, int((direct_time - 0.002) * fs))
    end = min(ir.size, int((direct_time + 0.003) * fs) + 1)
    direct_peak = start + int(np.argmax(np.abs(ir[start:end])))
    edc = 10 * np.log10(np.maximum(energy / max(float(energy[0]), 1e-300), 1e-300))
    indices = np.flatnonzero((edc <= -5) & (edc >= -25))
    t20 = None
    r2 = None
    if indices.size > 30:
        t = indices / fs
        y = edc[indices]
        slope, intercept = np.polyfit(t, y, 1)
        fit = slope * t + intercept
        denominator = float(np.sum((y - np.mean(y)) ** 2))
        r2 = 1 - float(np.sum((y - fit) ** 2)) / denominator if denominator else None
        t20 = float(-60 / slope) if slope < 0 else None
    return {
        "finite": bool(np.isfinite(ir).all()),
        "peak_time_s": peak / fs,
        "geometry_direct_arrival_s": direct_time,
        "measured_peak_near_direct_arrival_s": direct_peak / fs,
        "fullband_t20_screening_s": t20,
        "fullband_t20_fit_r_squared": r2,
        "diagnostic_scope": "Original measured FIR. T20 is a fullband screening fit to -5 to -25 dB reverse energy; no octave filtering, noise compensation, ISO validation, or FEM calibration.",
    }


def export_csv(directory: Path, code: str, traces: dict[int, np.ndarray], fs: float) -> dict:
    """Convenience output: phase-compensated low-pass FIR, then decimation."""
    factor = 12
    if fs != 48000:
        raise RuntimeError("Expected 48 kHz original sampling rate")
    taps = 241
    cutoff_hz = 1000.0
    n = np.arange(taps) - (taps - 1) / 2
    kernel = 2 * cutoff_hz / fs * np.sinc(2 * cutoff_hz / fs * n) * np.kaiser(taps, 8.6)
    kernel /= np.sum(kernel)
    filtered = {mic: np.convolve(ir, kernel, mode="same")[::factor] for mic, ir in traces.items()}
    filename = f"measured_room{code}_src1_mic1_mic26_4khz.csv"
    path = directory / filename
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["time_s", "mic1_fir_amplitude", "mic26_fir_amplitude"])
        for i in range(len(filtered[1])):
            writer.writerow([f"{i / (fs / factor):.6f}", f"{filtered[1][i]:.9g}", f"{filtered[26][i]:.9g}"])
    return {
        "file": filename,
        "sha256": sha256(path),
        "sampling_rate_hz": fs / factor,
        "samples": len(filtered[1]),
        "filter": {"type": "241-tap Kaiser-window FIR lowpass, centered convolution before decimation", "cutoff_hz": cutoff_hz, "kaiser_beta": 8.6, "decimation_factor": factor},
        "scope": "Convenience band-limited derivative; centered filtering can ring before arrivals and affects record edges. Use unchanged SOFA for measured validation. FIR amplitudes are not calibrated sound pressure in pascals.",
    }


def build_manifest(directory: Path, files: list[dict]) -> dict:
    with h5py.File(directory / "dEchorate_annotations.h5", "r") as annotations:
        room_size = np.asarray(annotations["room_size"])
        source_position = np.asarray(annotations["sources_directional_position"])[:, 0]
        microphones = np.asarray(annotations["microphones"])
    receiver = lambda mic: {"id": f"mic{mic}", "position_m": microphones[:, mic - 1].tolist()}
    measurements = []
    all_traces = {}
    license_text = None
    for code in ["011111", "000000"]:
        traces = {}
        for array in [1, 6]:
            ids = MIC_GROUPS[array]
            name = f"dEchorate_room{code}_src1_arr{array}_mics{ids[0]}-{ids[-1]}.sofa"
            with h5py.File(directory / name, "r") as sofa:
                title = decode(sofa.attrs["Title"])
                if title != name.removesuffix(".sofa"):
                    raise RuntimeError(f"Filename and SOFA title disagree: {name}")
                np.testing.assert_allclose(np.asarray(sofa["RoomCornerB"])[0], room_size, atol=1e-8)
                np.testing.assert_allclose(np.asarray(sofa["SourcePosition"])[0], source_position, atol=1e-8)
                positions = np.asarray(sofa["ReceiverPosition"])[:, :, 0]
                np.testing.assert_allclose(positions.T, microphones[:, np.array(ids) - 1], atol=1e-8)
                ir = np.asarray(sofa["Data.IR"])
                fs = float(np.asarray(sofa["Data.SamplingRate"])[0])
                license_value = decode(sofa.attrs["License"])
                if "MIT License" not in license_value:
                    raise RuntimeError(f"Unexpected license in {name}")
                license_text = license_value
                selected_mic = ids[0]
                selected_trace = ir[0, 0, :]
                traces[selected_mic] = selected_trace
                distance = float(np.linalg.norm(microphones[:, selected_mic - 1] - source_position))
                measurements.append({
                    "room_code": code,
                    "file": name,
                    "source_id": "src1",
                    "receiver_ids": [f"mic{mic}" for mic in ids],
                    "sampling_rate_hz": fs,
                    "shape": list(ir.shape),
                    "shape_axes": ["measurement", "receiver", "sample"],
                    "duration_s": ir.shape[-1] / fs,
                    "source_description": decode(sofa.attrs["SourceDescription"]),
                    "receiver_coordinates": "Already absolute Cartesian XYZ in metres; checked against annotations. Do not add ListenerPosition or rotate by ListenerView.",
                    "sofa_room_description_verbatim": decode(sofa.attrs.get("RoomDescription", "")),
                    "sofa_room_temperature_placeholder": np.asarray(sofa["RoomTemperature"]).tolist(),
                    "sofa_room_volume_placeholder": np.asarray(sofa["RoomVolume"]).tolist(),
                    "selected_receiver_diagnostics": {f"mic{selected_mic}": diagnostics(selected_trace, fs, distance)},
                })
        all_traces[code] = export_csv(directory, code, traces, fs)
    return {
        "schema_version": 1,
        "dataset": "dEchorate bounded measured 3D reference subset",
        "dataset_doi": "10.5281/zenodo.4626590",
        "paper_doi": "10.1186/s13636-021-00229-0",
        "room": {
            "size_m": room_size.tolist(),
            "nominal_publication_size_m": [6.0, 6.0, 2.4],
            "volume_m3": float(np.prod(room_size)),
            "speed_of_sound_m_s": 346.98,
            "temperature_c": 24.0,
            "relative_humidity_percent": 80.0,
            "coordinate_frame": "Absolute calibrated Cartesian XYZ; origin [0,0,0], +Z upward; west x=0, east x=Lx, south y=0, north y=Ly, floor z=0, ceiling z=Lz.",
            "geometry_provenance": "Calibrated inner room bounds from annotation HDF5 and each SOFA RoomCornerB, rather than rounded nominal dimensions in the article.",
            "environment_provenance": "Publication section 2.2 and repository constants; SOFA RoomTemperature and RoomVolume are zero placeholders.",
        },
        "source": {
            "id": "src1",
            "position_m": source_position.tolist(),
            "directivity": "Directional Avanton MIXCUBE; a point monopole FEM source is an illustrative approximation, not matched source directivity or power.",
        },
        "receivers": [receiver(mic) for mic in SELECTED_MIC_IDS],
        "all_receivers": [receiver(mic) for ids in MIC_GROUPS.values() for mic in ids],
        "room_states": {
            code: {
                "surface_order": SURFACE_ORDER,
                "surface_state": {surface: "reflective" if int(bit) else "absorbent" for surface, bit in zip(SURFACE_ORDER, code)},
                "furnished": False,
            } for code in ["011111", "000000"]
        },
        "surface_material_descriptions": {
            "floor_absorbent": "Hairy carpet",
            "wall_and_ceiling_absorbent": "Glass wool mats covered with porous tin (article Table 8)",
            "wall_and_ceiling_reflective": "Formica panels, 20 mm thick; plaster also identified for walls (article Table 8)",
            "impedance_status": "No calibrated frequency-dependent complex surface impedance is supplied in this subset. Material descriptions and binary states cannot be interpreted as measured commercial treatment performance.",
        },
        "measurements": measurements,
        "csv_exports": all_traces,
        "files": files,
        "license": {"spdx": "MIT", "source": "License attribute in every downloaded SOFA file", "text": license_text, "notice_file": "LICENSE.dataset.txt"},
        "primary_sources": {
            "paper": "https://arxiv.org/html/2104.13168",
            "dataset_record": "https://zenodo.org/records/4626590",
            "small_file_repository": BASE_URL,
            "calibrated_constants": "https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/__init__.py",
            "coordinate_construction": "https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/main_geometry_from_echo_calibration.py",
            "sofa_builder": "https://raw.githubusercontent.com/Chutlhu/dEchorate/master/dechorate/main_build_sofa_database.py",
        },
        "caveats": [
            "A controlled cuboid acoustics laboratory is a validation fixture, not a measured cafeteria or school dataset.",
            "ReceiverPosition is absolute in these files despite usual SOFA listener-relative semantics; cross-checked against calibrated annotations.",
            "SOFA RoomDescription contains an inconsistent room_code:020002 furnished-room description in selected files. Infer surface state from verified filename/title plus the article state table, not this stale attribute.",
            "SOFA RoomTemperature and RoomVolume contain zero placeholders. Use publication environment and derived volume.",
            "The floor is absorbent carpet in both 011111 and 000000; do not call 011111 an entirely rigid or entirely untreated room.",
            "Source src1 is directional, while an uncalibrated monopole solver source has different radiation and level.",
            "All solver boundary impedance, volumetric damping, and commercial product costs remain explicit assumptions pending measurement; this dataset import does not calibrate FEM.",
            "The one-second RIRs and screening fits do not establish broadband cafeteria noise reduction or speech intelligibility.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Verify and regenerate metadata from local files only")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    if args.offline:
        missing = [name for name in FILES if not (directory / name).is_file()]
        if missing:
            raise RuntimeError("Missing local files: " + ", ".join(missing))
    files = download(directory)
    manifest = build_manifest(directory, files)
    (directory / "LICENSE.dataset.txt").write_text(manifest["license"]["text"] + "\n", encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    total = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
    if total > MAX_BYTES:
        raise RuntimeError(f"Subset directory exceeds 8 MiB budget: {total} bytes")
    print(json.dumps({"files": len(files), "directory_bytes": total, "room": manifest["room"]["size_m"], "receivers": manifest["receivers"], "manifest": str(directory / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
