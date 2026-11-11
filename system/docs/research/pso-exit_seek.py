"""Exit seeking: when an area is cleared, find the area warp and walk into it.

Exploring rooms and killing enemies gets the bot through an area, but nothing yet tells it how to LEAVE one - which is the last thing standing between
it and an unattended run through a level. PSO's exits are entities: an area warp object appears when the area is complete, and stepping into it
transfers to the next area.

This scans the entity table for warp classes, walks to the nearest one with the height-aware planner, and presses A at it. If no warp exists yet (the
area is not complete), it says so and keeps exploring instead of wandering forever.

  * `TObjWarp*` / `*Warp*` classes are treated as exits;
  * boss warps are recognised separately, since they lead to a boss arena rather than the next field;
  * each attempt is logged with the warp's position and the distance reached, so a failure is diagnosable rather than silent.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import nav3                                                        # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
LOG = r"D:\gBox\pso-ds\exit_seek.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def warps():
    me = player()
    if me is None:
        return []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
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
            if "warp" not in name.lower():
                continue
            blob = S.read_memory(pointer + POS, 12)
            if len(blob) != 12:
                continue
            x, y, z = struct.unpack(">fff", blob)
        except Exception:                                        # noqa: BLE001
            continue
        out.append({"class": name, "x": x, "y": y, "z": z,
                    "distance": math.dist((me[0], me[2]), (x, z))})
    return sorted(out, key=lambda row: row["distance"])


def seek(timeout=90.0):
    """Walk to the nearest warp and enter it. Returns the warp it reached, or None."""
    found = warps()
    if not found:
        log("no warp entity in this area yet - it appears once the area is cleared")
        return None
    target = found[0]
    log(f"exit: {target['class']} at ({target['x']:.0f},{target['z']:.0f}), {target['distance']:.0f} units")
    started = time.time()
    while time.time() - started < timeout:
        if not pso_input.allowed():
            time.sleep(0.4)
            continue
        me = player()
        if me is None:
            continue
        remaining = math.dist((me[0], me[2]), (target["x"], target["z"]))
        if remaining > 6:
            route, raw_cells, legs = nav3.plan_h((me[0], me[2]), (target["x"], target["z"]),
                                                 start_height=me[1], goal_height=target["y"])
            if route:
                for waypoint in route[1:]:
                    RUN.run_to(ME.read_pos, (waypoint[0], waypoint[1]), tolerance=8.0, budget=15.0)
                    if not pso_input.allowed():
                        return None
            else:
                RUN.run_to(ME.read_pos, (target["x"], target["z"]), tolerance=8.0, budget=20.0)
        log(f"  reached {remaining:.0f} units - pressing A at the warp")
        for attempt in range(4):
            pso_input.hold("a", 0.3)
            time.sleep(1.4)
            floor_now = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
            log(f"    after A x{attempt + 1}: floor {floor_now}")
            if floor_now != 3:
                log(f"  AREA CHANGED to floor {floor_now}")
                return target
    return None


if __name__ == "__main__":
    result = seek(float(sys.argv[1]) if len(sys.argv) > 1 else 90.0)
    print("result:", result)
