"""Watch for warp entities appearing: the area warp only exists once its room loads.

CP17 needs the floor to change by walking, and the recorded coordinate (133,-48) does nothing when stepped on - the entity table held **no warp
class at all** there. So the exit has to be located where the game actually spawns it, which happens only when its room streams in. This scans
the entity table every couple of seconds and records any warp class the moment it appears, with its position and distance to the player.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
OUT = Path(r"D:\gBox\pso-ds\warp-sightings.jsonl")
LOG = r"D:\gBox\pso-ds\warp_watch.log"
SEEN = set()


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


log("=== watching for warp entities")
while True:
    point = ME.read_pos()
    floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
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
        key = (name, round(x), round(z))
        if key in SEEN:
            continue
        SEEN.add(key)
        distance = math.dist(point, (x, z)) if point else None
        record = {"t": round(time.time(), 2), "class": name, "floor": floor,
                  "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
                  "player": [round(point[0]), round(point[1])] if point else None,
                  "distance": round(distance) if distance is not None else None}
        with OUT.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        log(f"WARP SIGHTED: {name} at ({x:.0f},{y:.0f},{z:.0f}) floor {floor}, "
            f"{record['distance']} units from the player")
    time.sleep(2.0)
