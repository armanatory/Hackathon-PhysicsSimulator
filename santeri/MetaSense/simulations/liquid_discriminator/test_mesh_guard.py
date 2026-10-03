"""Offline mesh provenance checks; no cloud calls."""
from pathlib import Path
import struct
import tempfile
import unittest

try:
    from .mesh_guard import validate_mesh
except ImportError:
    from mesh_guard import validate_mesh


POINT = {"period_nm": 540.4089141457843, "fill_factor": 0.6027233748960321,
         "ridge_height_nm": 199.7989935940513, "film_thickness_nm": 100.0}


def nodes(point=POINT):
    p, f, h = point["period_nm"], point["fill_factor"], point["ridge_height_nm"]
    t = point["film_thickness_nm"]
    return [(x * 1e-9, y * 1e-9, z * 1e-9)
            for x in (0, p * (1 - f) / 2, p * (1 + f) / 2, p)
            for y in (0, 100) for z in (-h - 1000, -h, 0, t, t + 1000)]


def msh(binary=False, endian="<", size=8, parametric=False, point=POINT):
    xyz = nodes(point)
    count = len(xyz)
    if not binary:
        text = "$MeshFormat\n4.1 0 8\n$EndMeshFormat\n$Nodes\n"
        text += f"1 {count} 1 {count}\n3 1 0 {count}\n"
        text += " ".join(map(str, range(1, count + 1))) + "\n"
        text += "\n".join(" ".join(map(repr, row)) for row in xyz)
        return (text + "\n$EndNodes\n").encode()
    fmt = "Q" if size == 8 else "I"
    out = b"$MeshFormat\n4.1 1 " + str(size).encode() + b"\n"
    out += struct.pack(endian + "i", 1) + b"\n$EndMeshFormat\n$Nodes\n"
    out += struct.pack(endian + "4" + fmt, 1, count, 1, count)
    out += struct.pack(endian + "3i" + fmt, 3, 1, int(parametric), count)
    out += struct.pack(endian + str(count) + fmt, *range(1, count + 1))
    for row in xyz:
        out += struct.pack(endian + "3d", *row)
        if parametric:
            out += struct.pack(endian + "3d", 0.1, 0.2, 0.3)
    return out + b"\n$EndNodes\n"


class MeshGuardTests(unittest.TestCase):
    def check_bytes(self, data, point=POINT):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mesh.msh"
            path.write_bytes(data)
            return validate_mesh(path, point, 1000)

    def test_ascii_and_windows_newlines(self):
        for data in (msh(), msh().replace(b"\n", b"\r\n")):
            result = self.check_bytes(data)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["node_count"], 40)
            self.assertAlmostEqual(result["bounds_nm"][1][0], POINT["period_nm"])

    def test_binary_endianness_size_and_parametric_coordinates(self):
        for endian in ("<", ">"):
            for size in (4, 8):
                for parametric in (False, True):
                    result = self.check_bytes(msh(True, endian, size, parametric))
                    self.assertTrue(result["passed"], result)
                    self.assertEqual(result["msh_format"], "binary")

    def test_wrong_candidate_is_rejected(self):
        wrong = {**POINT, "period_nm": 452.66427832690783,
                 "fill_factor": 0.38721318143935046,
                 "ridge_height_nm": 179.23363929466643}
        result = self.check_bytes(msh(True, point=wrong))
        self.assertFalse(result["passed"])
        self.assertTrue(any("xmax" in e for e in result["errors"]))
        self.assertTrue(any("zmin" in e for e in result["errors"]))
        self.assertTrue(self.check_bytes(msh(True, point=wrong), wrong)["passed"])

    def test_missing_internal_interface_is_rejected(self):
        # Outer dimensions agree, but the submitted fill is different.
        result = self.check_bytes(msh(), {**POINT, "fill_factor": 0.4})
        self.assertFalse(result["passed"])
        for actual, expected in zip(result["bounds_nm"], result["expected_bounds_nm"]):
            for a, e in zip(actual, expected):
                self.assertAlmostEqual(a, e, places=9)
        self.assertFalse(result["interfaces_nm"]["x_ridge_left"]["passed"])

    def test_corrupt_or_unsupported_mesh_is_rejected(self):
        for data in (b"", msh(True)[:-20], msh().replace(b"4.1 0", b"2.2 0"),
                     msh().replace(b"1 40 1 40", b"1 41 1 40"),
                     msh().replace(b"0.0", b"nan", 1)):
            result = self.check_bytes(data)
            self.assertFalse(result["passed"], result)
            self.assertTrue(result["error"])


if __name__ == "__main__":
    unittest.main()
