"""Print only coordinate bounds from the downloaded Gmsh v4.1 binary mesh."""

from pathlib import Path
from struct import unpack_from

data = Path(__file__).with_name("room_250hz.msh").read_bytes()
offset = data.index(b"$Nodes\n") + len(b"$Nodes\n")
block_count, node_count, *_ = unpack_from("<QQQQ", data, offset)
offset += 32
points = []
for _ in range(block_count):
    dim, _tag, parametric, count = unpack_from("<iiiQ", data, offset)
    offset += 20 + 8 * count
    for _ in range(count):
        points.append(unpack_from("<ddd", data, offset))
        offset += 24
    if parametric:
        offset += 8 * dim * count

print("nodes", len(points), "expected", node_count)
print("bounds", [(min(p[i] for p in points), max(p[i] for p in points)) for i in range(3)])
