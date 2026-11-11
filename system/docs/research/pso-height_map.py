"""Per-cell floor heights from the collision mesh, so pathing can tell a ledge from the ground below it.

`pso_walk.cells` already respects a step-up tolerance between neighbouring cells, so its graph is height-aware. The failure is in `nav_fast`: it
snaps the start and goal to the nearest cell **by x,z alone**, so an enemy standing on lower ground gets snapped to the cliff-top cell directly
above it and every route leads to the edge.

This rasterises the collision triangles into a cell -> height table. Validation is built in: the cell under the player must read approximately
the player's own y, which is a value the game supplies independently.

Output: routes/forest<N>-heights.json  (cell "x,z" -> height)
"""
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import psomap, pso_walk                                  # noqa: E402

import session as S                                                # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel")
OUT_DIR = Path(r"D:\gBox\pso-ds\routes")
CELL = 10.0
PLAYER = 0x8050EA10


def heights(collision, floor=1):
    tris = psomap.collision(collision)
    table = {}
    for (a, b, c, flags, _normal) in tris:
        xs = (a[0], b[0], c[0])
        zs = (a[2], b[2], c[2])
        ys = (a[1], b[1], c[1])
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        cx0, cx1 = int(math.floor(min_x / CELL)), int(math.floor(max_x / CELL))
        cz0, cz1 = int(math.floor(min_z / CELL)), int(math.floor(max_z / CELL))
        for cx in range(cx0, cx1 + 1):
            for cz in range(cz0, cz1 + 1):
                centre_x, centre_z = (cx + 0.5) * CELL, (cz + 0.5) * CELL
                if not (min_x - CELL <= centre_x <= max_x + CELL and min_z - CELL <= centre_z <= max_z + CELL):
                    continue
                # barycentric test in x/z: is the cell centre inside this triangle?
                denominator = (zs[1] - zs[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (zs[0] - zs[2])
                if abs(denominator) < 1e-6:
                    continue
                wa = ((zs[1] - zs[2]) * (centre_x - xs[2]) + (xs[2] - xs[1]) * (centre_z - zs[2])) / denominator
                wb = ((zs[2] - zs[0]) * (centre_x - xs[2]) + (xs[0] - xs[2]) * (centre_z - zs[2])) / denominator
                wc = 1.0 - wa - wb
                if wa < -0.05 or wb < -0.05 or wc < -0.05:
                    continue
                y = wa * ys[0] + wb * ys[1] + wc * ys[2]
                key = (cx, cz)
                if key not in table or y > table[key]:
                    table[key] = round(y, 2)
    return table


def main(floor=1):
    collision = pso_walk.cells
    rel = REL / f"map_forest{int(floor):02d}c.rel"
    if not rel.exists():
        print("missing", rel)
        return 2
    table = heights(rel.read_bytes(), floor)
    print(f"floor {floor}: {len(table)} cells with a height")
    # validation: the cell under the player should read close to the player's own y
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + 0x38, 12)
    px, py, pz = struct.unpack(">fff", blob)
    cell = (int(math.floor(px / CELL)), int(math.floor(pz / CELL)))
    under = table.get(cell)
    print(f"player at ({px:.1f},{py:.1f},{pz:.1f}) -> cell {cell} height {under}")
    if under is not None:
        print(f"validation: height differs from the player's y by {abs(under - py):.2f} units "
              f"({'PASS' if abs(under - py) < 3.0 else 'FAIL'})")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"forest{floor}-heights.json"
    out.write_text(json.dumps({f"{cx},{cz}": y for (cx, cz), y in table.items()}), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
