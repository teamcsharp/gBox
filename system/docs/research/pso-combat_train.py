"""Combat training: reload the area to respawn enemies, fight them, record what worked.

The operator asked to spawn enemies repeatedly and master combat until it is learned. The plane's `floor_spawn` spawns ITEMS, not enemies, but
`floor_warp` to the same floor **reloads the area**, which respawns its enemies - so a loop of warp -> fight -> warp gives unlimited fights.

Forest 1 is the training ground because it has a room graph and a collision map, so movement and distance are honest measurements rather than
dead reckoning.

Per round it records: how many enemies appeared, how long each fight took, how many hits landed, how much damage each hit did, and whether the
kill came from melee or a technique. The point is to produce numbers that say which action actually kills, rather than an impression that the bot
is fighting.

Usage: python combat_train.py [rounds]
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import map_bot as MB                                               # noqa: E402
import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
RECORD = Path(r"D:\gBox\pso-ds\combat-training.jsonl")
LOG = r"D:\gBox\pso-ds\combat_train.log"
TRAIN_FLOOR = "1"
MELEE = 6.0


def log(line, event=None):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")
    if event:
        with RECORD.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"t": round(time.time(), 2), **event}) + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def enemies(limit=80.0):
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
            if not name.startswith(("TObjEne", "TEne", "TBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit and hp > 0:
            out.append({"pointer": pointer, "class": name, "x": x, "y": y, "z": z,
                        "hp": hp, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def reload_area():
    try:
        reply = S.controls("floor_warp", {"target": TRAIN_FLOOR}, timeout=90)
        return bool(isinstance(reply, dict) and reply.get("ok"))
    except Exception as exc:                                      # noqa: BLE001
        log(f"  reload refused: {str(exc)[:90]}")
        return False


def one_fight(target, budget=20.0):
    """Fight one enemy. Returns (killed, hits, damage, seconds, method)."""
    started = time.time()
    hits = 0
    damage = 0
    method = None
    initial = target["hp"]
    while time.time() - started < budget:
        if not pso_input.allowed():
            time.sleep(0.3)
            continue
        now = [row for row in enemies() if row["pointer"] == target["pointer"]]
        if not now:
            return True, hits, damage, time.time() - started, method or "gone"
        current = now[0]
        if current["hp"] < initial - damage:
            damage = initial - current["hp"]
            hits += 1
        gap = math.dist((player()[0], player()[2]), (current["x"], current["z"]))
        if gap > MELEE:
            pso_input.hold("b", 0.25)
            method = method or "technique"
        else:
            MB.attack_while_stepping((current["x"], current["z"]), swings=3)
            method = method or "melee"
        time.sleep(0.35)
    return False, hits, damage, time.time() - started, method or "timeout"


def main(rounds=6):
    log(f"=== combat training on floor {TRAIN_FLOOR}, {rounds} rounds")
    for round_index in range(rounds):
        if not reload_area():
            time.sleep(3)
            continue
        time.sleep(7)                                             # let the area load
        found = enemies()
        log(f"round {round_index + 1}: {len(found)} enemies after reload")
        killed = 0
        for target in found[:4]:
            if not pso_input.allowed():
                time.sleep(0.5)
                continue
            ok, hits, damage, seconds, method = one_fight(target)
            killed += 1 if ok else 0
            log(f"  {target['class']} hp {target['hp']} -> {'dead' if ok else 'alive'} "
                f"in {seconds:.1f}s, {hits} damaging actions, {damage} damage, {method}",
                {"round": round_index + 1, "class": target["class"], "hp": target["hp"],
                 "killed": ok, "seconds": round(seconds, 1), "hits": hits,
                 "damage": damage, "method": method})
        log(f"round {round_index + 1} done: {killed} kills", {"round": round_index + 1, "kills": killed})


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    main(count)
