"""One clean strike: close until the enemy is within a few units, confirm the distance, then swing.

Every component has been measured separately - movement moves, focus can be held, assists are on - so this test removes the ambiguity from the
combination: it walks to the enemy, *prints the distance it achieved*, and only then attacks, reading the enemy's HP immediately afterwards. If the
distance is small and the HP does not move, the fault is in the attack itself; if the distance stays large, the fault is in the approach.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import pso_input                                                   # noqa: E402
import run2 as RUN                                                 # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C


def nearest():
    me = ME.read_pos()
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    best = None
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
            enemy_hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        if enemy_hp <= 0:
            continue
        distance = math.dist((me[0], me[1]), (x, z))
        if best is None or distance < best[0]:
            best = (round(distance, 1), name, enemy_hp, (x, z), y)
    return best


target = nearest()
if target is None:
    raise SystemExit("no enemy")
print(f"start: {target[1]} hp {target[2]} at {target[0]} units, heights {target[4]:.1f} vs {ME.read_pos()[1]:.1f}")
print("focused:", G.game_has_focus(), "| allowed:", pso_input.allowed())

for attempt in range(5):
    if not pso_input.allowed():
        print("  waiting for focus")
        time.sleep(0.5)
        continue
    current = nearest()
    if current is None:
        print("  enemy gone")
        raise SystemExit(0)
    distance, name, enemy_hp, position, enemy_y = current
    if distance > 4.0:
        RUN.run_to(ME.read_pos, position, tolerance=3.0, budget=8.0)
    now = nearest()
    gap = now[0] if now else 0.0
    print(f"  attempt {attempt + 1}: closed to {gap} units, enemy hp {now[2] if now else 0}")
    if gap <= 7.0:
        for swing in range(3):
            pso_input.hold("a", 0.24)
            time.sleep(0.32)
        after = nearest()
        print(f"    after 3 swings: {after[1] if after else 'gone'} hp {after[2] if after else 0} "
              f"at {after[0] if after else 0} units")
        if after is None or after[2] < enemy_hp:
            print("    DAMAGE LANDED")
            raise SystemExit(0)
print("no damage at close range - the attack itself is the fault")
raise SystemExit(1)
