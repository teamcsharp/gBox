"""Finish the boss: cast techniques at the Dragon until it dies, recording the HP series.

The fight captured so far went 1191 -> 814 -> 727 -> 652 -> 468 -> 390 -> 202, then stalled when self-play's target lock declared the boss "down"
on a transient table absence and wandered off. The boss is still alive at 202 HP.

Techniques reach at least 26 units (measured), and the player is revived on death by the survival patch, so this closes the distance only if the
cast does nothing and otherwise simply casts until the HP reaches zero.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
SERIES = Path(r"D:\gBox\pso-ds\evidence\cp18-boss-series.jsonl")
LOG = r"D:\gBox\pso-ds\kill_boss.log"


def log(line, event=None):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if event:
        with SERIES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 2), **event}) + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def boss():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
    me = player()
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith("TBoss1"):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        if hp <= 0:
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if best is None or distance < best[0]:
            best = (distance, {"class": name, "pointer": pointer, "x": x, "y": y, "z": z, "hp": hp})
    return best


log("=== boss finisher")
for attempt in range(60):
    if not pso_input.allowed():
        time.sleep(0.5)
        continue
    entry = boss()
    if entry is None:
        log("no living boss entity - the fight is over")
        log("BOSS DEFEATED", {"event": "cp18_boss_defeated"})
        raise SystemExit(0)
    distance, target = entry
    log(f"dragon hp {target['hp']} at {distance:.0f} units")
    if distance > 60:
        RUN.run_to(ME.read_pos, (target["x"], target["z"]), tolerance=25.0, budget=15.0)
        continue
    pso_input.hold("b", 0.25)
    time.sleep(0.5)
    pso_input.hold("a", 0.25)
    time.sleep(0.5)
    after = boss()
    if after is None:
        log("BOSS DEFEATED", {"event": "cp18_boss_defeated"})
        raise SystemExit(0)
    if after[1]["hp"] < target["hp"]:
        log(f"  damage {target['hp']} -> {after[1]['hp']}", {"event": "boss_hit",
                                                             "before": target["hp"], "after": after[1]["hp"]})
log("gave up before the boss died")
raise SystemExit(2)
