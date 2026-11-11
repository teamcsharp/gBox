"""Combat with height-aware pathing: route to the enemy's LEVEL, then fight on flat ground.

Every earlier fight failed because the goal was snapped by (x, z) alone: an enemy below the player was snapped to the cliff above it. With the
height table the route ends on the enemy's own level, which is where melee can connect.

Loop per enemy: plan at its height, walk the legs, and once within melee reach with the heights agreeing, swing in a normal-attack combo. The wiki
notes the Booma closes on you, so the last metres are often its own doing.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
MELEE = 6.0
HEIGHT_OK = 2.0


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def enemies(limit=60.0):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    me = player()
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit:
            out.append({"class": name, "x": x, "y": y, "z": z, "hp": hp, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def swing(times=3, gap=0.42):
    for _ in range(times):
        if not pso_input.allowed():
            return
        pso_input.hold("a", 0.22)
        time.sleep(gap)


def kill_next():
    me = player()
    found = enemies()
    if not found:
        print("no enemies in range")
        return None
    target = found[0]
    print(f"target {target['class']} hp {target['hp']} at ({target['x']:.0f},{target['y']:.0f},{target['z']:.0f}) "
          f"({target['distance']:.1f} units, height diff {target['y'] - me[1]:+.1f})")
    for attempt in range(6):
        me = player()
        target = next((row for row in enemies() if row["class"] == target["class"]), None)
        if target is None:
            print("  target gone")
            return "gone"
        gap = math.dist((me[0], me[2]), (target["x"], target["z"]))
        height_diff = abs(target["y"] - me[1])
        if gap > MELEE or height_diff > HEIGHT_OK:
            route, raw, simple = nav3.plan_h((me[0], me[2]), (target["x"], target["z"]),
                                             start_height=me[1], goal_height=target["y"])
            print(f"  attempt {attempt}: gap {gap:.1f}, height diff {height_diff:.1f} -> "
                  f"{raw} cells, {simple} legs")
            for waypoint in route[1:3] or route:
                RUN.run_to(lambda: (player()[0], player()[2]), (waypoint[0], waypoint[1]), tolerance=6.0, budget=12.0)
                if not pso_input.allowed():
                    return None
            continue
        print(f"  attempt {attempt}: in reach (gap {gap:.1f}, height {height_diff:.1f}) - swinging")
        swing(3)
        after = next((row for row in enemies() if row["class"] == target["class"]), None)
        if after is None or after["hp"] < target["hp"]:
            print(f"  DAMAGE: {target['hp']} -> {after['hp'] if after else 'dead'}")
            if after is None or after["hp"] == 0:
                return "killed"
    return "unfinished"


if __name__ == "__main__":
    print("== height-aware combat")
    print("result:", kill_next())
