"""Continuous floor-series recorder: the evidence CP17 needs, captured automatically.

CP17's accept test is that the floor id changes by walking rather than by a warp command. The transition itself cannot be reconstructed after the
fact - it has to be observed as it happens - so this samples the floor id and the player's position on a short interval and writes a row whenever
either changes, plus a heartbeat row every few seconds.

Any transition that occurs while this runs is therefore timestamped with the position it happened at, which is exactly the accept evidence: a floor
change with the character on foot.
"""
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

FLOOR = 0x805D5FC0
PLAYER = 0x8050EA10
OUT = Path(r"D:\gBox\pso-ds\evidence\floor-series.jsonl")
LOG = r"D:\gBox\pso-ds\floor_series.log"
INTERVAL = 0.4


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def sample():
    floor = int.from_bytes(S.read_memory(FLOOR, 4), "big")
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    position = None
    if 0x80000000 <= pointer < 0x81800000:
        blob = S.read_memory(pointer + 0x38, 12)
        if len(blob) == 12:
            x, y, z = struct.unpack(">fff", blob)
            position = [round(x, 1), round(y, 1), round(z, 1)]
    return floor, position


log("=== floor series recorder")
OUT.parent.mkdir(parents=True, exist_ok=True)
last_floor = None
last_position = None
last_beat = 0.0
started = time.time()
with OUT.open("a", encoding="utf-8") as handle:
    while True:
        time.sleep(INTERVAL)
        try:
            floor, position = sample()
        except Exception as exc:                                  # noqa: BLE001
            time.sleep(2.0)
            continue
        now = time.time()
        if last_floor is not None and floor != last_floor:
            row = {"t": round(now, 2), "event": "FLOOR_CHANGE", "from": last_floor, "to": floor,
                   "at": position, "elapsed": round(now - started, 1)}
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            log(f"FLOOR CHANGE {last_floor} -> {floor} at {position}")
        elif position and last_position and (
                abs(position[0] - last_position[0]) > 25 or abs(position[1] - last_position[1]) > 12
                or abs(position[2] - last_position[2]) > 25):
            row = {"t": round(now, 2), "event": "jump", "floor": floor, "from": last_position, "to": position}
            handle.write(json.dumps(row) + "\n")
            handle.flush()
        elif now - last_beat > 10.0:
            handle.write(json.dumps({"t": round(now, 2), "event": "beat", "floor": floor,
                                     "at": position}) + "\n")
            handle.flush()
            last_beat = now
        last_floor = floor
        last_position = position
