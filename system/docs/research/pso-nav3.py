"""Height-aware pathing: snap start/goal to a cell at the right HEIGHT, not just the nearest (x, z).

Measured: the enemy sat at y=7 while the player stood at y=11.5, and `nav_fast` snapped goals to the nearest cell by (x, z) alone - so an enemy on
lower ground was snapped to the cliff-top cell above it and every route led to the edge instead of down.

The per-cell height table (validated to 0.16 units against the player's own y) fixes that: the snap cost now includes a height term, so a goal
pointed at the enemy prefers a cell at the enemy's level.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav_fast as NAV                                             # noqa: E402

HEIGHTS = Path(r"D:\gBox\pso-ds\routes\forest1-heights.json")
CELL = 10.0
HEIGHT_WEIGHT = 3.0


def load_heights(floor=1):
    path = Path(rf"D:\gBox\pso-ds\routes\forest{floor}-heights.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}
    table = {}
    for key, value in raw.items():
        x, z = key.split(",")
        table[(int(x), int(z))] = float(value)
    return table


def snap(free, point, height=None, table=None):
    """The free cell nearest to `point`, biased toward cells at `height` when one is given."""
    goal_x, goal_z = point[0], point[1]
    if height is None or not table:
        return min(free, key=lambda cell: math.dist(NAV.centre(cell), (goal_x, goal_z)))
    best = None
    for cell in free:
        flat = math.dist(NAV.centre(cell), (goal_x, goal_z))
        cell_height = table.get(cell)
        penalty = 0.0 if cell_height is None else abs(cell_height - height) * HEIGHT_WEIGHT
        score = flat + penalty
        if best is None or score < best[0]:
            best = (score, cell)
    return best[1]


def plan_h(start, goal, start_height=None, goal_height=None, floor=1):
    """A route whose endpoints are snapped at the right height. Returns (route, raw_count, simple_count)."""
    free = NAV.cells(floor)
    table = load_heights(floor)
    start_cell = snap(free, start, start_height, table)
    goal_cell = snap(free, goal, goal_height, table)
    raw = NAV.bfs(free, NAV.centre(start_cell), NAV.centre(goal_cell))
    if not raw:
        return [], 0, 0
    simple = NAV.string_pull(free, raw)
    return simple, len(raw), len(simple)


if __name__ == "__main__":
    import struct

    import session as S

    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    blob = S.read_memory(pointer + 0x38, 12)
    px, py, pz = struct.unpack(">fff", blob)
    print(f"player ({px:.1f},{py:.1f},{pz:.1f})")

    TABLE, MAX_ENTRIES = 0x8050D460, 256
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    target = None
    for index in range(MAX_ENTRIES):
        p = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= p < 0x81800000):
            continue
        try:
            np = int.from_bytes(S.read_memory(p, 4), "big")
            name = S.read_memory(np, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne")):
                continue
            b = S.read_memory(p + 0x38, 12)
            ex, ey, ez = struct.unpack(">fff", b)
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((px, pz), (ex, ez))
        if target is None or distance < target[0]:
            target = (distance, name, ex, ey, ez)
    if target is None:
        raise SystemExit("no enemy")
    distance, name, ex, ey, ez = target
    print(f"nearest {name} at ({ex:.1f},{ey:.1f},{ez:.1f}), {distance:.1f} units, height diff {ey - py:+.1f}")
    route, raw_count, simple = plan_h((px, pz), (ex, ez), start_height=py, goal_height=ey)
    print(f"height-aware plan: {raw_count} cells -> {simple} legs")
    for waypoint in route[:5]:
        print(f"  ({waypoint[0]:.0f},{waypoint[1]:.0f})")
