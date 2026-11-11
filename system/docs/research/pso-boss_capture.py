"""Capture the boss fight: the boss's HP and the player's HP as a time series.

CP18's evidence is the Dragon encounter recorded while it happens, so this samples the boss (by class) and the player every half second and writes
a row whenever either HP changes, plus a heartbeat. Both are read from the actor table, which carries HP at +0x32C for every actor.

The bot fights with survival enabled, so the player's HP may not drop - the boss's HP curve is the part that proves the fight happened and
progressed.
"""
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
OUT = Path(r"D:\gBox\pso-ds\evidence\cp18-boss-series.jsonl")
LOG = r"D:\gBox\pso-ds\boss_capture.log"
INTERVAL = 0.5


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player_hp():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + HP, 2)
    maximum = S.read_memory(pointer + 0x2B8, 2)
    return struct.unpack(">H", blob)[0], struct.unpack(">H", maximum)[0]


def bosses():
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
            if not (name.startswith("TBoss") or name.startswith("TObjBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        out.append({"class": name, "hp": hp, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
    return out


log("=== boss capture")
OUT.parent.mkdir(parents=True, exist_ok=True)
last_signature = None
last_beat = 0.0
with OUT.open("a", encoding="utf-8") as handle:
    while True:
        time.sleep(INTERVAL)
        try:
            found = bosses()
            hp, hp_max = player_hp()
        except Exception:                                        # noqa: BLE001
            time.sleep(1.0)
            continue
        now = time.time()
        signature = tuple((row["class"], row["hp"]) for row in found)
        if signature != last_signature:
            row = {"t": round(now, 2), "event": "boss_state", "player_hp": hp, "player_hp_max": hp_max,
                   "bosses": found}
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            if found:
                log(f"boss: {[(b['class'], b['hp']) for b in found]} | player {hp}/{hp_max}")
            last_signature = signature
        elif now - last_beat > 10.0:
            handle.write(json.dumps({"t": round(now, 2), "event": "beat", "player_hp": hp,
                                     "bosses": found}) + "\n")
            handle.flush()
            last_beat = now
