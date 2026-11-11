"""Play Forest 1: walk the path, engage the nearest enemy, and keep moving.

Uses the live RAM reads (position, enemies) for decisions and the proven input path for action, so every step is grounded in the game
state rather than a blind key script:
  * no enemy within ENGAGE_RANGE -> walk forward in short strides along the path
  * an enemy inside ENGAGE_RANGE -> close to melee range, then attack-while-stepping (hold the closing direction and swing, which lands
    the hit because the character turns into the swing)
Captures at checkpoints so the run can be reviewed.
"""
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import boot_game as B                                              # noqa: E402
import game_input as G                                             # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, HP = 0x8050D460, 256, 0x32C
FLOOR = 0x805D5FC0
ENGAGE_RANGE = 45.0


def player():
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    if not pointer:
        return None
    blob = S.read_memory(pointer + 0x38, 12)
    if len(blob) != 12:
        return None
    x, y, z = struct.unpack(">fff", blob)
    hp = struct.unpack(">H", S.read_memory(pointer + HP, 2))[0]
    return {"x": x, "y": y, "z": z, "hp": hp, "pointer": pointer}


def enemies():
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = S.read_memory(name_pointer, 24).split(b"\x00")[0].decode("ascii", "replace")
        if not name.startswith("TObjEne"):
            continue
        blob = S.read_memory(pointer + 0x38, 12)
        if len(blob) != 12:
            continue
        x, y, z = struct.unpack(">fff", blob)
        hp = struct.unpack(">H", S.read_memory(pointer + HP, 2))[0]
        out.append({"class": name, "x": x, "z": z, "hp": hp})
    return [e for e in out if e["hp"] > 0]


def hold(key, seconds):
    G.send([{"key": key, "down": True}])
    time.sleep(seconds)
    G.send([{"key": key, "down": False}])
    time.sleep(0.05)


def tap(key, gap=0.28):
    G.send([{"key": key, "down": True}, {"key": key, "down": False}])
    time.sleep(gap)


def closing_key(goal):
    me = player()
    bearing = (goal[0] - me["x"], goal[1] - me["z"])
    norm = math.hypot(*bearing) or 1.0
    bearing = (bearing[0] / norm, bearing[1] / norm)
    best = None
    for key in ("up", "down", "left", "right"):
        before = player()
        hold(key, 0.22)
        after = player()
        vector = (after["x"] - before["x"], after["z"] - before["z"])
        length = math.hypot(*vector)
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if best is None or align > best[1]:
            best = (key, align)
    return best


def attack_while_stepping(goal, swings=4):
    facing = closing_key(goal)
    if not facing:
        return False
    key = facing[0]
    G.send([{"key": key, "down": True}])
    time.sleep(0.15)
    for _ in range(swings):
        G.send([{"key": "a", "down": True}])
        time.sleep(0.06)
        G.send([{"key": "a", "down": False}])
        time.sleep(0.30)
    G.send([{"key": key, "down": False}])
    return True


def main(rounds=12):
    print("floor:", int.from_bytes(S.read_memory(FLOOR, 4), "big"))
    for index in range(rounds):
        me = player()
        if not me:
            print("no player")
            return 2
        mobs = enemies()
        print(f"round {index}: pos=({me['x']:.0f},{me['z']:.0f}) hp={me['hp']} enemies={[(e['class'], e['hp']) for e in mobs]}",
              flush=True)
        if mobs:
            target = min(mobs, key=lambda e: math.dist((me["x"], me["z"]), (e["x"], e["z"])))
            gap = math.dist((me["x"], me["z"]), (target["x"], target["z"]))
            if gap <= ENGAGE_RANGE:
                if gap > 9:
                    facing = closing_key((target["x"], target["z"]))
                    if facing:
                        hold(facing[0], min(1.4, 0.25 + gap / 45.0))
                else:
                    attack_while_stepping((target["x"], target["z"]))
                    after = enemies()
                    print(f"  attacked {target['class']} at {gap:.0f}; enemies now {[(e['class'], e['hp']) for e in after]}",
                          flush=True)
                continue
        hold("up", 1.1)
        if index % 3 == 2:
            B.shot(f"play-{index}")
    B.shot("play-final")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 12))
