"""Read the actual MSH nodes before trusting a geometric sweep's metadata.

The SDK returns a distinct physical mesh file for each geometric override. A
successful mesh job does not itself establish that those bytes match the intended
geometry. This check uses SI node coordinates; Gmsh's entity bounding boxes can
use a different scale and are deliberately not used.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
import struct


def _node_coordinates(data: bytes) -> tuple[list[list[float]], int, str]:
    """Parse the Nodes section of ASCII or binary Gmsh MSH 4.1."""
    match = re.search(rb"\$MeshFormat\r?\n", data)
    if match is None:
        raise ValueError("Missing Gmsh MeshFormat section")
    header_start = match.end()
    header_end = data.index(b"\n", header_start)
    version, binary, size = data[header_start:header_end].split()
    if version != b"4.1" or binary not in (b"0", b"1"):
        raise ValueError("Expected ASCII or binary Gmsh MSH 4.1")
    size = int(size)
    if size not in (4, 8):
        raise ValueError("Unsupported Gmsh size_t size")
    node_match = re.search(rb"\$Nodes\r?\n", data[header_end:])
    if node_match is None:
        raise ValueError("Missing Gmsh Nodes section")
    position = header_end + node_match.end()
    axes: list[list[float]] = [[], [], []]
    actual_count = 0

    if binary == b"0":
        end = data.index(b"$EndNodes", position)
        tokens = iter(data[position:end].split())
        blocks, count, _, _ = (int(next(tokens)) for _ in range(4))
        for _ in range(blocks):
            dim, _, param, n = (int(next(tokens)) for _ in range(4))
            if dim not in range(4) or param not in (0, 1) or n < 0:
                raise ValueError("Invalid Gmsh node block")
            for _ in range(n):
                int(next(tokens))  # Node tags precede all coordinates.
            for _ in range(n):
                for axis in axes:
                    axis.append(float(next(tokens)))
                for _ in range(dim * param):
                    float(next(tokens))
            actual_count += n
        if next(tokens, None) is not None:
            raise ValueError("Unexpected extra data in Gmsh Nodes section")
        kind = "ascii"
    else:
        endian_marker = data[header_end + 1:header_end + 5]
        if endian_marker == struct.pack("<i", 1):
            endian = "<"
        elif endian_marker == struct.pack(">i", 1):
            endian = ">"
        else:
            raise ValueError("Invalid Gmsh binary endianness marker")
        size_format = "Q" if size == 8 else "I"

        def read(fmt: str) -> tuple:
            nonlocal position
            result = struct.unpack_from(endian + fmt, data, position)
            position += struct.calcsize(endian + fmt)
            return result

        blocks, count, _, _ = read("4" + size_format)
        for _ in range(blocks):
            dim, _, param = read("3i")
            n = read(size_format)[0]
            if dim not in range(4) or param not in (0, 1) or n > count:
                raise ValueError("Invalid Gmsh node block")
            position += n * size  # Node tags.
            for _ in range(n):
                xyz = read("3d")
                for axis, value in zip(axes, xyz):
                    axis.append(value)
                position += dim * param * 8
            actual_count += n
        if data[position:].lstrip(b"\r\n").split(b"\n", 1)[0] != b"$EndNodes":
            raise ValueError("Gmsh Nodes section ended unexpectedly")
        kind = "binary"
    if actual_count != count or count == 0:
        raise ValueError("Gmsh node count mismatch or empty mesh")
    if not all(math.isfinite(value) for axis in axes for value in axis):
        raise ValueError("Gmsh node coordinates must be finite")
    return axes, count, kind


def validate_mesh(path: str | Path, point: dict, clearance_nm: float,
                  tolerance_nm: float = 0.001) -> dict:
    """Compare actual nodes with the liquid grating's submitted geometry.

    ``point`` needs period_nm, fill_factor, ridge_height_nm and
    film_thickness_nm. period_y_nm defaults to the fixed 100 nm unit cell.
    The default 0.001 nm is a CAD roundoff allowance, not a simulation accuracy
    tolerance. A failed check must prevent launching the corresponding solve.
    """
    result = {"passed": False, "path": str(path), "tolerance_nm": tolerance_nm,
              "bounds_nm": None, "expected_bounds_nm": None,
              "interfaces_nm": {}, "errors": [], "error": None}
    try:
        if not math.isfinite(tolerance_nm) or tolerance_nm <= 0:
            raise ValueError("Mesh geometry tolerance must be positive and finite")
        period = float(point["period_nm"])
        fill = float(point["fill_factor"])
        height = float(point["ridge_height_nm"])
        film = float(point["film_thickness_nm"])
        period_y = float(point.get("period_y_nm", 100.0))
        clearance = float(clearance_nm)
        if not all(math.isfinite(v) and v > 0
                   for v in (period, height, film, period_y, clearance)) or not 0 < fill < 1:
            raise ValueError("Mesh geometry dimensions must be finite and positive")
        data = Path(path).read_bytes()
        result["sha256"] = hashlib.sha256(data).hexdigest()
        axes_si, count, kind = _node_coordinates(data)
        axes = [[v * 1e9 for v in axis] for axis in axes_si]
        bounds = [[min(axis) for axis in axes], [max(axis) for axis in axes]]
        expected = [[0.0, 0.0, -height - clearance],
                    [period, period_y, film + clearance]]
        result.update(bounds_nm=bounds, expected_bounds_nm=expected,
                      node_count=count, msh_format=kind)
        for side in range(2):
            for axis, label in enumerate(("x", "y", "z")):
                delta = bounds[side][axis] - expected[side][axis]
                if abs(delta) > tolerance_nm:
                    result["errors"].append(
                        f"{label}{'min' if side == 0 else 'max'} differs by {delta:.12g} nm")
        features = {"x_ridge_left": (0, period * (1 - fill) / 2),
                    "x_ridge_right": (0, period * (1 + fill) / 2),
                    "z_ridge_top": (2, -height),
                    "z_film_top": (2, 0.0), "z_film_bottom": (2, film)}
        for name, (axis, value) in features.items():
            nearest = min(axes[axis], key=lambda item: abs(item - value))
            delta = nearest - value
            result["interfaces_nm"][name] = {
                "expected": value, "nearest_node_coordinate": nearest,
                "difference": delta, "passed": abs(delta) <= tolerance_nm}
            if abs(delta) > tolerance_nm:
                result["errors"].append(f"{name} lacks an interface node within tolerance ({delta:.12g} nm)")
        result["passed"] = not result["errors"]
        result["error"] = "; ".join(result["errors"]) or None
    except (OSError, ValueError, KeyError, StopIteration, struct.error, OverflowError) as error:
        result["errors"].append(str(error) or "Truncated Gmsh Nodes section")
        result["error"] = "; ".join(result["errors"])
    return result
