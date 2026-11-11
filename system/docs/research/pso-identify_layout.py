"""Identify which layout of an area is currently loaded, by asking which one contains the live world.

A floor has several layout variants (Cave 1 has six), and only one is loaded at a time. The loaded one is the only layout whose walkable cells contain
the character AND the doors standing around them - so this measures every candidate against both:

  * the player's cell must be free (a layout that calls the floor under the player a wall is not the one loaded);
  * the live doors' and containers' cells must mostly be free, since the level places objects on walkable ground.

The candidate with the highest agreement wins, and the margin is reported so a tie is visible rather than hidden.
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox import psomap, pso_walk                                  # noqa: E402

import session as S                                                # noqa: E402

REL = Path(r"D:\gBox\pso-ds\rel")
TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
PLAYER = 0x8050EA10
CELL = 10.0
PREFIX = sys.argv[1] if len(sys.argv) > 1 else "map_cave01"


def to_cell(x, z):
    return (int(math.floor(x / CELL)), int(math.floor(z / CELL)))


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def placements():
    """Positions of doors and containers in the live world - the level puts these on walkable ground."""
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
            if not name.startswith(("TODoor", "TObjDoor", "TObjContainer", "TOCapsule", "TObjWarp")):
                continue
            blob = S.read_memory(pointer + POS, 12)
            if len(blob) != 12:
                continue
            x, y, z = struct.unpack(">fff", blob)
        except Exception:                                        # noqa: BLE001
            continue
        out.append((name, x, z))
    return out


def score(collision_path, me, objects):
    floors, _walls = pso_walk.cells(collision_path.read_bytes())
    free = set(floors)
    player_free = to_cell(me[0], me[2]) in free
    on_free = sum(1 for (_name, x, z) in objects if to_cell(x, z) in free)
    return player_free, on_free, len(free)


def main():
    me = player()
    objects = placements()
    print(f"player {tuple(round(v, 1) for v in me)} | live doors/containers: {len(objects)}")
    candidates = sorted(REL.glob(f"{PREFIX}_*c.rel"))
    if not candidates:
        print(f"no {PREFIX}_*c.rel in {REL}")
        return 2
    results = []
    for path in candidates:
        player_free, on_free, free_count = score(path, me, objects)
        ratio = on_free / len(objects) if objects else 0.0
        results.append((player_free, ratio, on_free, free_count, path.name))
        print(f"  {path.name}: player on free cell={player_free}, "
              f"objects on free cells={on_free}/{len(objects)} ({ratio:.0%}), free cells={free_count}")
    results.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = results[0]
    if len(results) > 1:
        margin = best[1] - results[1][1]
        print(f"\nbest: {best[4]} (player free={best[0]}, objects {best[1]:.0%}); "
              f"margin over next: {margin:.0%}")
    else:
        print(f"\nbest: {best[4]}")
    (REL / "identified-layout.txt").write_text(best[4], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
