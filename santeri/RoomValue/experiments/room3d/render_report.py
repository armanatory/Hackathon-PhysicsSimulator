"""Render the measured room geometry and original reference impulse responses.

This file does not contact Allsolve or generate acoustic fields. Geometry comes
from the dataset manifest and the saved model configuration. Recorded SOFA FIRs
are separate validation references, with their original, uncalibrated units.
An optional downloaded VTKHDF pressure field is sampled using its tetrahedral
finite-element shape functions; masked gaps are never extrapolated.
"""
from __future__ import annotations

import argparse
import json
from itertools import product
from pathlib import Path

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


HERE = Path(__file__).resolve().parent
DATASET = HERE.parents[1] / "datasets" / "dechorate" / "manifest.json"
COLORS = {"source": "#d14e40", "mic1": "#007f93", "mic26": "#6e4ba6",
          "east_wall": "#db9b23", "ceiling": "#377cca"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def xyz(values):
    if isinstance(values, dict):
        values = [values[axis] for axis in ("x", "y", "z")]
    values = np.asarray(values, dtype=float)
    if values.shape != (3,) or not np.isfinite(values).all():
        raise ValueError(f"Expected three finite Cartesian coordinates: {values}")
    return values


def box_faces(origin, size):
    origin, size = xyz(origin), xyz(size)
    vertices = np.array([origin + size * np.array(bits) for bits in product((0, 1), repeat=3)])
    indices = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
               (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    return [vertices[list(face)] for face in indices]


def treatment_boxes(model, room_size):
    geometries = {g["name"]: g for g in model["geometries"]}
    room = geometries["room"]
    if room["type"] != "box" or not np.allclose(xyz(room["position"]), 0):
        raise ValueError("Renderer expects the room at the manifest Cartesian origin")
    if not np.allclose(xyz(room["size"]), room_size):
        raise ValueError("Saved model room bounds disagree with the dataset manifest")
    treatments = {}
    for name in ("east_wall", "ceiling"):
        geometry = geometries[name]
        if geometry["type"] != "box" or geometry.get("alignment") != "corner":
            raise ValueError(f"Expected a corner-aligned 3D treatment box: {name}")
        position, size = xyz(geometry["position"]), xyz(geometry["size"])
        if np.any(position < 0) or np.any(size <= 0) or np.any(position + size > room_size + 1e-8):
            raise ValueError(f"Treatment {name} lies outside the measured room")
        treatments[name] = {"position": position, "size": size, "volume": float(size.prod())}
    if not np.isclose(treatments["east_wall"]["volume"], treatments["ceiling"]["volume"]):
        raise ValueError("Treatments must have equal volume for the comparison illustration")
    return treatments


def render_geometry(dataset, model, results, output):
    size = xyz(dataset["room"]["size_m"])
    treatments = treatment_boxes(model, size)
    source = xyz(dataset["source"]["position_m"])
    receivers = {r["id"]: xyz(r["position_m"]) for r in dataset["receivers"]}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig = plt.figure(figsize=(13, 8.2), facecolor="white")
    ax = fig.add_axes((0.015, 0.11, 0.68, 0.79), projection="3d")
    ax.set_proj_type("ortho")
    faces = box_faces(np.zeros(3), size)
    ax.add_collection3d(Poly3DCollection(faces, facecolors="#cbd7df", edgecolors="#708493",
                                       linewidths=1, alpha=0.035))
    ax.add_collection3d(Poly3DCollection([faces[4]], facecolors="#dde7ec", edgecolors="none", alpha=0.35))
    handles = []
    for name, spec in treatments.items():
        color = COLORS[name]
        ax.add_collection3d(Poly3DCollection(box_faces(spec["position"], spec["size"]),
                                           facecolors=color, edgecolors=color, alpha=0.50, linewidths=1.0))
        label = "East wall treatment" if name == "east_wall" else "Ceiling treatment"
        handles.append(Patch(facecolor=color, edgecolor=color, alpha=0.65, label=label))
    points = [(dataset["source"]["id"], source, COLORS["source"], "*", 240)]
    points.extend((rid, point, COLORS.get(rid, "#27676a"), "o", 90) for rid, point in receivers.items())
    for name, point, color, marker, marker_size in points:
        ax.scatter(*point, color=color, marker=marker, s=marker_size, edgecolors="white", linewidths=0.8,
                   depthshade=False, zorder=8)
        ax.plot([point[0], point[0]], [point[1], point[1]], [0, point[2]], linestyle=(0, (3, 3)),
                color=color, linewidth=1.15, alpha=0.8)
        ax.scatter(point[0], point[1], 0, color=color, marker="+", s=30, depthshade=False)
        ax.text(point[0] + 0.08, point[1] + 0.07, point[2] + 0.11, name, color=color,
                fontsize=11, fontweight="bold", zorder=9)
        handles.append(Line2D([], [], color=color, marker=marker, linestyle="none", markersize=11,
                              label=f"{name} · height {point[2]:.3f} m"))
    ax.set_xlim(0, size[0]); ax.set_ylim(0, size[1]); ax.set_zlim(0, size[2])
    # Matplotlib normalizes its aspect array in place; preserve physical bounds.
    ax.set_box_aspect(size.copy())
    ax.set_xlabel("X · west → east (m)", labelpad=12)
    ax.set_ylabel("Y · south → north (m)", labelpad=12)
    ax.set_zlabel("Z · height (m)", labelpad=8)
    ax.set_xticks(np.arange(0, size[0] + 0.01, 1))
    ax.set_yticks(np.arange(0, size[1] + 0.01, 1))
    ax.set_zticks([0, 0.5, 1.0, 1.5, 2.0])
    ax.tick_params(labelsize=9, pad=1)
    ax.view_init(elev=25, azim=-53)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.fill = False
        axis._axinfo["grid"].update(color="#dbe1e5", linewidth=0.55)
    fig.suptitle("dEchorate measured room · true 3D simulation setup", x=0.49, y=0.965,
                 fontsize=19, fontweight="bold", color="#203443")
    fig.text(0.055, 0.915, f"Calibrated bounds {size[0]:.3f} × {size[1]:.3f} × {size[2]:.3f} m  ·  "
             f"volume {float(size.prod()):.2f} m³", fontsize=12, color="#4b606e")
    ax_info = fig.add_axes((0.715, 0.125, 0.275, 0.72))
    ax_info.axis("off")
    ax_info.legend(handles=handles, loc="upper left", frameon=False, fontsize=11,
                   borderaxespad=0, labelspacing=1.0, handletextpad=0.7)
    coordinates = "Measured coordinates (m)\n\n           X       Y       Z\n"
    for name, point, *_ in points:
        coordinates += f"{name:6s} {point[0]:7.3f} {point[1]:7.3f} {point[2]:7.3f}\n"
    ax_info.text(0, 0.57, coordinates, va="top", family="DejaVu Sans Mono", fontsize=9.5, color="#203443")
    volume = treatments["east_wall"]["volume"]
    ax_info.text(0, 0.37, f"Equal treatment volumes: {volume:.2f} m³ each\n"
                 f"East wall: {' × '.join(f'{x:g}' for x in treatments['east_wall']['size'])} m\n"
                 f"Ceiling: {' × '.join(f'{x:g}' for x in treatments['ceiling']['size'])} m\n\n"
                 "Colored boxes are independent candidate\nplacements of a volumetric loss proxy.\n"
                 "Their damping is uncalibrated.\n\n"
                 "Room, source and microphone positions\ncome from calibrated dataset geometry.\n"
                 "The laboratory is a validation fixture.",
                 va="top", fontsize=10.5, linespacing=1.5, color="#4b606e")
    if results:
        status = f"Allsolve {results['frequency_hz']:g} Hz harmonic model · 3D tetrahedral mesh"
    else:
        status = "Geometry preparation · cloud solver results are not displayed in this view"
    fig.text(0.055, 0.045, status, fontsize=10, color="#4b606e")
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)


def render_measurements(dataset, folder, output):
    selected = [r["id"] for r in dataset["receivers"]]
    records = {rid: [] for rid in selected}
    for measurement in dataset["measurements"]:
        path = folder / measurement["file"]
        if not path.exists():
            continue
        ids = measurement["receiver_ids"]
        with h5py.File(path, "r") as sofa:
            rate = float(np.asarray(sofa["Data.SamplingRate"]).ravel()[0])
            if rate <= 0 or not np.isfinite(rate):
                raise ValueError(f"Invalid SOFA sample rate: {path}")
            ir = sofa["Data.IR"]
            if ir.ndim != 3 or ir.shape[0] != 1 or ir.shape[1] != len(ids):
                raise ValueError(f"Unexpected original SOFA IR axes: {path}")
            delays = np.asarray(sofa["Data.Delay"])
            if np.any(delays != 0):
                raise ValueError("Nonzero SOFA delays require an explicit delay convention before plotting")
            for rid in selected:
                if rid in ids:
                    values = np.asarray(ir[0, ids.index(rid), :int(rate * 0.1) + 1], dtype=float)
                    if not np.isfinite(values).all():
                        raise ValueError(f"Nonfinite original measured IR: {path}")
                    records[rid].append((measurement["room_code"], np.arange(len(values)) / rate, values))
    if not any(records.values()):
        return False
    fig, axes = plt.subplots(len(selected), 1, figsize=(12, 7), sharex=True, squeeze=False)
    for rid, axis in zip(selected, axes.ravel()):
        for room_code, times, values in records[rid]:
            if room_code == "011111":
                label, color = "011111 · carpet floor, reflective walls/ceiling", "#4477aa"
            elif room_code == "000000":
                label, color = "000000 · all six surfaces absorbent", "#cc6677"
            else:
                label, color = room_code, None
            axis.plot(times, values, linewidth=0.65, alpha=0.82, label=label, color=color)
        axis.set_title(f"{rid} · measured source {dataset['source']['id']}", loc="left", fontsize=12)
        axis.set_ylabel("recorded IR amplitude\n(dataset units)", fontsize=10)
        axis.grid(color="#e1e7eb", linewidth=0.6)
        axis.set_xlim(0, 0.1)
        axis.ticklabel_format(axis="y", style="sci", scilimits=(-2, 2))
        axis.legend(loc="upper right", fontsize=9, frameon=True)
    axes[-1, 0].set_xlabel("Time from recorded impulse origin (s)")
    fig.suptitle("Original measured room impulse responses · first 100 ms", fontsize=16, fontweight="bold")
    fig.text(0.1, 0.025, "48 kHz SOFA recordings · uncalibrated amplitude · separate from the harmonic FEM model",
             fontsize=10, color="#4b606e")
    fig.tight_layout(rect=(0, 0.055, 1, 0.94))
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)
    return True


def read_cloud_field(path, room_size):
    """Read the observed Allsolve VTKHDF unstructured tetrahedral export."""
    with h5py.File(path, "r") as file:
        group = file["VTKHDF"]
        points = np.asarray(group["Points"], dtype=float)
        pressure = np.asarray(group["PointData/Pressure"], dtype=float)
        connectivity = np.asarray(group["Connectivity"], dtype=np.int64)
        offsets = np.asarray(group["Offsets"], dtype=np.int64)
        types = np.asarray(group["Types"], dtype=np.uint8)
    if points.ndim != 2 or points.shape[1] != 3 or pressure.shape != (len(points),):
        raise ValueError("Unexpected VTKHDF pressure/coordinate dimensions")
    if not np.isfinite(points).all() or not np.isfinite(pressure).all():
        raise ValueError("Nonfinite downloaded cloud field")
    bounds = np.column_stack((points.min(axis=0), points.max(axis=0)))
    if not np.allclose(bounds[:, 0], 0, atol=1e-7) or not np.allclose(bounds[:, 1], room_size, atol=1e-7):
        raise ValueError("Downloaded pressure field has different room bounds")
    counts = np.diff(offsets)
    if len(counts) != len(types) or offsets[0] != 0 or offsets[-1] != len(connectivity):
        raise ValueError("Invalid downloaded VTKHDF connectivity offsets")
    if np.all(types == 10) and np.all(counts == 4):
        order, node_count = 1, 4
    elif np.all(np.isin(types, [24, 71])) and np.all(counts == 10):
        order, node_count = 2, 10
    else:
        raise ValueError("Slice supports verified linear or 10-node quadratic tetrahedral exports only")
    cells = connectivity.reshape((-1, node_count))
    if np.any(cells < 0) or np.any(cells >= len(points)):
        raise ValueError("Downloaded VTKHDF cell refers to a missing point")
    vertices = points[cells[:, :4]]
    edges = vertices[:, 1:] - vertices[:, :1]
    inverse = np.linalg.inv(edges)
    if order == 2:
        edge_pairs = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
        midpoints = np.stack([(vertices[:, a] + vertices[:, b]) / 2 for a, b in edge_pairs], axis=1)
        if not np.allclose(points[cells[:, 4:]], midpoints, atol=1e-8, rtol=0):
            raise ValueError("Quadratic tetrahedral edge ordering or curved geometry is unsupported")
    return vertices, inverse, pressure[cells], order


def evaluate_cell(query, vertices, inverse, nodal_pressure, order):
    last = (query - vertices[0]) @ inverse
    barycentric = np.column_stack((1 - last.sum(axis=1), last))
    inside = np.all((barycentric >= -1e-8) & (barycentric <= 1 + 1e-8), axis=1)
    weights = barycentric[inside]
    if order == 2:
        edge_pairs = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))
        weights = np.column_stack((weights * (2 * weights - 1),
                                   *[4 * weights[:, a] * weights[:, b] for a, b in edge_pairs]))
    return inside, weights @ nodal_pressure


def select_baseline_field(results, folder):
    """Choose the finest downloaded baseline with matching verified success."""
    if not results or results.get("dimension") != 3:
        return None
    for level in ("refined", "fine", "coarse"):
        run = results.get("runs", {}).get(f"{level}_baseline_125hz")
        if not run or run.get("status") != "SUCCESS":
            continue
        files = sorted((folder / f"{level}_field").glob("*.hdf"))
        if len(files) > 1:
            raise ValueError(f"Multiple {level} cloud field files found; require a single baseline export")
        if files:
            return level, files[0]
    return None


def render_pressure_slice(dataset, results, field, output, level):
    if not results or results.get("dimension") != 3:
        return False
    run_name = f"{level}_baseline_125hz"
    run = results.get("runs", {}).get(run_name)
    if not run or run.get("status") != "SUCCESS":
        return False
    size = xyz(dataset["room"]["size_m"])
    receivers = {r["id"]: xyz(r["position_m"]) for r in dataset["receivers"]}
    slice_receiver = dataset["receivers"][0]["id"]
    slice_height = receivers[slice_receiver][2]
    vertices, inverses, pressures, order = read_cloud_field(field, size)
    lower, upper = vertices.min(axis=1), vertices.max(axis=1)
    crossed = np.flatnonzero((lower[:, 2] <= slice_height) & (upper[:, 2] >= slice_height))
    xs = np.linspace(0, size[0], 301)
    ys = np.linspace(0, size[1], 315)
    raster = np.full((len(ys), len(xs)), np.nan)
    for cell in crossed:
        x0 = max(0, int(np.searchsorted(xs, lower[cell, 0], side="left")) - 1)
        x1 = min(len(xs), int(np.searchsorted(xs, upper[cell, 0], side="right")) + 1)
        y0 = max(0, int(np.searchsorted(ys, lower[cell, 1], side="left")) - 1)
        y1 = min(len(ys), int(np.searchsorted(ys, upper[cell, 1], side="right")) + 1)
        grid_x, grid_y = np.meshgrid(xs[x0:x1], ys[y0:y1])
        query = np.column_stack((grid_x.ravel(), grid_y.ravel(), np.full(grid_x.size, slice_height)))
        inside, values = evaluate_cell(query, vertices[cell], inverses[cell], pressures[cell], order)
        patch = raster[y0:y1, x0:x1].copy().ravel()
        patch[inside] = values
        raster[y0:y1, x0:x1] = patch.reshape(grid_x.shape)
    coverage = float(np.isfinite(raster[1:-1, 1:-1]).mean())
    if coverage < 0.999:
        raise ValueError(f"Downloaded tetrahedral field covers only {coverage:.1%} of the interior slice")
    # Check the interpolation against the independently exported cloud probe.
    probe = receivers[slice_receiver]
    candidate_cells = np.flatnonzero(np.all((lower <= probe + 1e-8) & (upper >= probe - 1e-8), axis=1))
    probe_value = None
    for cell in candidate_cells:
        inside, values = evaluate_cell(probe[None, :], vertices[cell], inverses[cell], pressures[cell], order)
        if inside[0]:
            probe_value = float(values[0])
            break
    expected_probe = run["pressures"][slice_receiver]["real_pa"]
    if probe_value is None or not np.isclose(probe_value, expected_probe, rtol=1e-5, atol=1e-7):
        raise ValueError(f"Field interpolation/probe mismatch: {probe_value} vs {expected_probe} Pa")
    fig, ax = plt.subplots(figsize=(10.2, 8.5))
    maximum = float(np.nanmax(np.abs(raster)))
    color_map = ax.pcolormesh(xs, ys, np.ma.masked_invalid(raster), shading="auto",
                             cmap="RdBu_r", vmin=-maximum, vmax=maximum, rasterized=True)
    colorbar = fig.colorbar(color_map, ax=ax, fraction=0.042, pad=0.03)
    colorbar.set_label("In-phase pressure (Pa)")
    source = xyz(dataset["source"]["position_m"])
    ax.scatter(source[0], source[1], marker="*", s=150, color="#202a32", edgecolor="white", linewidth=0.8,
               label=f"Source projection · z = {source[2]:.3f} m")
    for rid, point in receivers.items():
        ax.scatter(point[0], point[1], marker="o", s=75, color=COLORS.get(rid, "#202a32"), edgecolor="white",
                   linewidth=1.2, label=f"{rid} · z = {point[2]:.3f} m")
        ax.annotate(rid, point[:2], xytext=(8, 8), textcoords="offset points", fontweight="bold", color="#203443",
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8, "pad": 2})
    ax.set_aspect("equal")
    ax.set_xlim(0, size[0]); ax.set_ylim(0, size[1])
    ax.set_xlabel("X · west → east (m)"); ax.set_ylabel("Y · south → north (m)")
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    ax.set_title(f"Allsolve baseline · {results['frequency_hz']:g} Hz in-phase acoustic pressure\n"
                 f"Horizontal slice at {slice_receiver} height · z = {slice_height:.3f} m", fontsize=14, pad=16)
    interpolation = "quadratic" if order == 2 else "linear"
    fig.text(0.10, 0.035, f"Actual downloaded {level} mesh field; {interpolation} tetrahedral interpolation.\n"
             "1 Pa spherical source; idealized reflecting boundaries; uncalibrated material assumptions.",
             fontsize=9, color="#4b606e", linespacing=1.5)
    fig.tight_layout(rect=(0, 0.085, 1, 1))
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)
    return {"field_file": str(field), "mesh_level": level, "run_name": run_name,
            "simulation_id": run["simulation_id"],
            "mesh_id": results.get("meshes", {}).get(level, {}).get("mesh_id"),
            "tetrahedron_count": len(vertices), "height_m": float(slice_height),
            "field_probe_pa": probe_value, "independent_cloud_probe_pa": expected_probe,
            "slice_interior_coverage_fraction": coverage, "interpolation_order": order}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--model", type=Path, default=HERE / "model_config.json")
    parser.add_argument("--results", type=Path, default=HERE / "VERIFIED_3D.json")
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    dataset, model = read_json(args.dataset), read_json(args.model)
    results = read_json(args.results) if args.results.exists() else None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [args.output_dir / "room3d.png"]
    render_geometry(dataset, model, results, outputs[0])
    measured = args.output_dir / "measured_ir.png"
    if render_measurements(dataset, args.dataset.parent, measured):
        outputs.append(measured)
    selected_field = select_baseline_field(results, HERE / "outputs")
    field_check = None
    if selected_field:
        level, field = selected_field
        pressure = args.output_dir / "pressure_slice_mic1.png"
        field_check = render_pressure_slice(dataset, results, field, pressure, level)
        if field_check:
            outputs.append(pressure)
    validation = {"rendered": [str(path) for path in outputs], "field_validation": field_check}
    (args.output_dir / "figure_validation.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
