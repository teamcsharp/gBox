"""Continuous learner: internalise everything observable while the game is played.

The operator asked for the bot to learn the map, the layout, the enemies and what they do, every time they play. This samples the game and
turns the raw stream into knowledge:

  every second   the player's position, floor, HP and TP;
  every 3 s      the entity table (class + position), which yields spawn points, deaths/pickups (a class disappearing) and the enemy mix;
  on change      HP drops are recorded as damage events at the player's position - the hazard map;
                 floor changes are recorded as teleporter discoveries;
                 the path is accumulated as a route, which learn_paths.py already consumes.

Output is append-only JSONL in D:\\gBox\\pso-ds\\learned\\live\\, one file per run, so a session can be replayed or folded into the maps
later. The learner only READS the game: it never sends input and never needs the operator lock.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

LEARNED = Path(r"D:\gBox\pso-ds\learned")
LIVE = LEARNED / "live"
TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
FLOOR = 0x805D5FC0
PLAYER_POINTER = 0x8050EA10
POSITION_SECONDS = 1.0
ENTITY_SECONDS = 3.0
LOG = r"D:\gBox\pso-ds\learn_live.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    try:
        pointer = int.from_bytes(S.read_memory(PLAYER_POINTER, 4), "big")
        if not pointer:
            return None
        position = S.read_memory(pointer + 0x38, 12)
        if len(position) != 12:
            return None
        x, y, z = struct.unpack(">fff", position)
        hp = struct.unpack(">H", S.read_memory(pointer + 0x32C, 2))[0]
        hpmax = struct.unpack(">H", S.read_memory(pointer + 0x2B8, 2))[0]
        tp = struct.unpack(">H", S.read_memory(pointer + 0x32E, 2))[0]
        tpmax = struct.unpack(">H", S.read_memory(pointer + 0x2BA, 2))[0]
        floor = int.from_bytes(S.read_memory(FLOOR, 4), "big")
        return {"x": x, "y": y, "z": z, "hp": hp, "hpmax": hpmax, "tp": tp, "tpmax": tpmax, "floor": floor}
    except Exception:                                            # noqa: BLE001
        return None


def entities():
    try:
        raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    except Exception:                                            # noqa: BLE001
        return []
    found = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 28).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith("T"):
                continue
            blob = S.read_memory(pointer + POS, 12)
            if len(blob) != 12:
                continue
            x, y, z = struct.unpack(">fff", blob)
            found.append({"i": index, "c": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
        except Exception:                                        # noqa: BLE001
            continue
    return found


def key(entity):
    return (entity["c"], round(entity["x"] / 8), round(entity["z"] / 8))


def main(max_minutes=60.0):
    LIVE.mkdir(parents=True, exist_ok=True)
    out = LIVE / f"live-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log(f"=== learning into {out.name}")
    started = time.time()
    last_position = 0.0
    last_entity = 0.0
    known = {}
    previous_player = None
    route = []
    damages = 0
    floors = {None}
    with out.open("a", encoding="utf-8") as handle:
        while time.time() - started < max_minutes * 60:
            now = time.time()
            if now - last_position >= POSITION_SECONDS:
                last_position = now
                me = player()
                if me is None:
                    time.sleep(0.5)
                    continue
                record = {"t": round(now, 3), "kind": "pos", **{k: round(v, 2) if isinstance(v, float) else v
                                                               for k, v in me.items()}}
                if previous_player is not None:
                    if previous_player["floor"] != me["floor"]:
                        record["kind"] = "floor_change"
                        record["from"] = previous_player["floor"]
                        record["at"] = [round(me["x"], 1), round(me["z"], 1)]
                        log(f"floor change {previous_player['floor']} -> {me['floor']} at "
                            f"({me['x']:.0f},{me['z']:.0f})")
                    if me["hp"] < previous_player["hp"]:
                        record["damage"] = previous_player["hp"] - me["hp"]
                        damages += 1
                if not route or math.dist((record["x"], record["z"]), tuple(route[-1])) >= 8.0:
                    route.append((round(record["x"], 1), round(record["z"], 1)))
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                previous_player = me
            if now - last_entity >= ENTITY_SECONDS:
                last_entity = now
                current = {key(e): e for e in entities()}
                appeared = [e for k, e in current.items() if k not in known]
                vanished = [e for k, e in known.items() if k not in current]
                if appeared or vanished:
                    handle.write(json.dumps({"t": round(now, 3), "kind": "entities",
                                             "appeared": appeared[:40], "vanished": vanished[:40]}) + "\n")
                    handle.flush()
                known = current
            time.sleep(0.2)
    summary = {"path_points": len(route), "damage_events": damages, "entities_known": len(known),
               "path": [[x, z] for x, z in route]}
    (LEARNED / f"{out.stem}-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(f"stop: {len(route)} path points, {damages} damage events, {len(known)} entities tracked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 60.0))
