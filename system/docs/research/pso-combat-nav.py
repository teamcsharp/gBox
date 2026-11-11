"""Combat that paths to the enemy instead of holding a direction.

`attack_while_stepping` swings while holding a direction chosen by four probes, which fails whenever terrain blocks the straight line: the probes
measure no movement, the direction is unusable, and the loop swings in place while the enemy sits 16 units away.

This uses what is already measured to work: `nav_fast.plan` routes across the free-cell grid and `run2` walks it at 27 units/s. For each swing round
it plans to the enemy, walks up to two legs, and only then swings - so an obstacle is routed around rather than pushed against.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import nav_fast as NAV                                             # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
MELEE = 5.0


def nearest_enemy(point, limit=60.0):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne", "TBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist(point, (x, z))
        if distance <= limit and (best is None or distance < best[0]):
            best = (distance, {"class": name, "x": x, "z": z, "hp": hp})
    return best


def close_in():
    """Plan and walk toward the nearest enemy until inside melee range. Returns the enemy or None."""
    for attempt in range(4):
        point = ME.read_pos()
        if point is None:
            return None
        entry = nearest_enemy(point)
        if entry is None:
            return None
        gap, enemy = entry
        if gap <= MELEE:
            return enemy
        route, raw, simple = NAV.plan(point, (enemy["x"], enemy["z"]))
        if not route:
            return enemy
        for waypoint in route[1:3]:
            RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=6.0, budget=12.0)
            if not pso_input.allowed():
                return None
        point = ME.read_pos()
        if point and math.dist(point, (enemy["x"], enemy["z"])) <= MELEE:
            return enemy
    return None


if __name__ == "__main__":
    print("== pathfinding combat test")
    entry = nearest_enemy(ME.read_pos())
    print("nearest enemy:", entry)
    enemy = close_in()
    print("closed in:", enemy)
    for swing in range(6):
        pso_input.hold("a", 0.3)
        time.sleep(0.8)
        now = nearest_enemy(ME.read_pos())
        print(f"  swing {swing + 1}: nearest {now}")
        if now is None or (enemy and now[1]["hp"] < enemy["hp"]):
            print("  DAMAGE LANDED" if now else "  enemy gone")
            break
