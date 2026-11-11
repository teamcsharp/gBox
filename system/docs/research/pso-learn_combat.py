"""Learn combat from the operator's play: record the geometry of every successful hit.

The controller cannot be read, but the RESULT can: when an enemy's HP drops, the position, distance and height of the player at that instant are the
conditions under which the attack worked. Sampling at a high rate and diffing the entities' HP captures:

  * the distance at which hits land (the melee/reach envelope);
  * the height difference at which hits land;
  * the cadence between hits (combo rhythm and stun-lock timing);
  * the heading change between hits.

Written to `combat-demos.jsonl` per hit and summarised in `combat-learned.json` so the bot can use the operator's own numbers instead of guesses.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
OUT = Path(r"D:\gBox\pso-ds\combat-demos.jsonl")
SUMMARY = Path(r"D:\gBox\pso-ds\combat-learned.json")
LOG = r"D:\gBox\pso-ds\learn_combat.log"
INTERVAL = 0.12


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def snapshot():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = {}
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
        out[pointer] = {"pointer": pointer, "class": name, "x": x, "y": y, "z": z, "hp": hp}
    return out


log("=== learning combat from the operator's play")
previous = snapshot()
last_heading = None
last_drop = 0.0
hits = []
started = time.time()
while True:
    time.sleep(INTERVAL)
    me = player()
    if me is None:
        continue
    current = snapshot()
    now = time.time()
    for pointer, entity in current.items():
        before = previous.get(pointer)
        if before is None or before["hp"] <= 0:
            continue
        if entity["hp"] < before["hp"]:
            distance = math.dist((me[0], me[2]), (entity["x"], entity["z"]))
            heading = math.degrees(math.atan2(entity["z"] - me[2], entity["x"] - me[0]))
            record = {
                "t": round(now, 2), "class": entity["class"], "hp_before": before["hp"],
                "hp_after": entity["hp"], "damage": before["hp"] - entity["hp"],
                "distance": round(distance, 2), "height_diff": round(entity["y"] - me[1], 2),
                "bearing": round(heading, 1), "player": [round(me[0], 1), round(me[1], 1), round(me[2], 1)],
                "since_last_hit": round(now - last_drop, 2) if last_drop else None,
            }
            with OUT.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            hits.append(record)
            last_drop = now
            log(f"HIT {entity['class']}: -{record['damage']} hp ({before['hp']} -> {entity['hp']}) "
                f"at {distance:.1f} units, height {record['height_diff']:+.1f}, "
                f"cadence {record['since_last_hit']}")
            if len(hits) % 8 == 0:
                distances = sorted(hit["distance"] for hit in hits)
                cadences = [hit["since_last_hit"] for hit in hits if hit["since_last_hit"]]
                summary = {"hits": len(hits),
                           "distance_min": distances[0], "distance_median": distances[len(distances) // 2],
                           "distance_max": distances[-1],
                           "cadence_median": sorted(cadences)[len(cadences) // 2] if cadences else None,
                           "classes": sorted({hit["class"] for hit in hits})}
                SUMMARY.write_text(json.dumps(summary, indent=1), encoding="utf-8")
                log(f"  summary: {summary}")
    previous = current
