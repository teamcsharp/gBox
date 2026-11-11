"""Points of interest: the permanent map of what has actually been seen, accumulated across every session.

The live learner proved this is the only way to find exits: Forest 2's set files hold no warp, yet the entity table listed
`TObjWarpBossMulti` at (155.4,-500.8) and `TOKeyGenericSw` at (-110.2,-460.3) the moment the floor was loaded.

This scans the entity table, classifies what it finds and merges new sightings into `learned/points-of-interest.json`, keyed by floor and
class, keeping every distinct position. Run it any time (or alongside the learner) to grow the map: warps, switches, doors, capsules,
containers and enemy spawns all accumulate.
"""
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
FLOOR = 0x805D5FC0
OUT = Path(r"D:\gBox\pso-ds\learned\points-of-interest.json")
MERGE_RADIUS = 12.0

KINDS = {
    "warp": ("TObjWarp", "TObjAreaWarp", "TObjMapWarp", "TObjGoalWarp", "TObjCityMainWarp", "TObjCityAreaWarp"),
    "switch": ("TOSwitch", "TLazerFenceSw", "TOKeyGenericSw", "TObjSwitch"),
    "door": ("TObjDoor",),
    "capsule": ("TOCapsule",),
    "container": ("TObjContainer",),
    "item": ("TItem",),
    "enemy": ("TObjEne", "TEne", "TObjBoss"),
    "npc": ("TObjNpc", "TObjNPC"),
    "telepipe": ("TObjTelepipe", "TObjHeal"),
}


def classify(name):
    for kind, prefixes in KINDS.items():
        if any(name.startswith(prefix) for prefix in prefixes):
            return kind
    return "other"


def floor_now():
    try:
        return int.from_bytes(S.read_memory(FLOOR, 4), "big")
    except Exception:                                            # noqa: BLE001
        return 0


def entities():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
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
            found.append({"class": name, "x": round(x, 1), "y": round(y, 1), "z": round(z, 1)})
        except Exception:                                        # noqa: BLE001
            continue
    return found


def load():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}


def main():
    data = load()
    floor = floor_now()
    key = str(floor)
    bucket = data.setdefault(key, {})
    added = 0
    seen = 0
    for entity in entities():
        kind = classify(entity["class"])
        if kind == "other":
            continue
        seen += 1
        rows = bucket.setdefault(kind, [])
        point = (entity["x"], entity["z"])
        if any(row["class"] == entity["class"] and math.dist((row["x"], row["z"]), point) <= MERGE_RADIUS
               for row in rows):
            continue
        rows.append({**entity, "t": round(time.time(), 1)})
        added += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"floor {floor}: {seen} entities classified, {added} new points of interest")
    for kind, rows in sorted(bucket.items()):
        print(f"  {kind:<10} {len(rows):3d}  " + ", ".join(
            f"{row['class']}({row['x']:.0f},{row['z']:.0f})" for row in rows[:4]))
    for kind in ("warp", "switch"):
        for row in bucket.get(kind, []):
            print(f"  !! {kind.upper()}: {row['class']} at ({row['x']:.1f},{row['z']:.1f}) floor {floor}")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
