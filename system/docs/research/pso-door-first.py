"""Door-first CP17 controller built on the door state flags (+0x18C).

Rules from the operator:
  * a door whose state is not 0 (2 = cleared, 240 = special) is open -> walk through it;
  * a closed door means the room's enemies must die first -> fight them, then re-read the flags;
  * record every state transition so the bot knows what unlocked what.

Loop: read doors -> if a usable door is near, go through it -> otherwise head for the nearest closed door, clear the room's enemies
(attack-while-stepping), re-read, repeat; the key door ends the run when the floor changes.
"""
import json
import math
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
import pso_doors                                                   # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\door_first.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.2)
    return b""


def controls(op, fields, timeout=90):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:120]}


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def enemies():
    raw = read(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name.startswith("TObjEne"):
            continue
        x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"class": name, "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "x": x, "y": y, "z": z})
    return [e for e in out if e["hp"] > 0]


def read_pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def player_hp():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    return int.from_bytes(read(actor + HP, 2), "big"), int.from_bytes(read(actor + HP_MAX, 2), "big")


def gbox_hwnd():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.strip() == "gBox":
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def send(events):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.04)
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.03)


def tap(key, times=1, gap=0.3):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def closing_key(goal):
    me = read_pos()
    bearing = unit(goal[0] - me[0], goal[1] - me[1])
    best = None
    for key in ("up", "down", "left", "right"):
        before = read_pos()
        hold(key, 0.22)
        after = read_pos()
        vector = (after[0] - before[0], after[1] - before[1])
        length = math.hypot(*vector)
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if best is None or align > best[1]:
            best = (key, align)
    return best


def step_toward(goal, stop=8.0, budget=60.0):
    started = time.time()
    while time.time() - started < budget:
        me = read_pos()
        if math.dist(me, goal) <= stop:
            return True
        facing = closing_key(goal)
        if not facing:
            tap("b", 1, 0.3)
            continue
        hold(facing[0], 0.35 if math.dist(read_pos(), goal) > 25 else 0.25)
    return math.dist(read_pos(), goal) <= stop


def attack_while_stepping(goal, swings=3):
    facing = closing_key(goal)
    if not facing:
        return False
    key = facing[0]
    send([{"key": key, "down": True}])
    time.sleep(0.18)
    for _ in range(swings):
        send([{"key": "a", "down": True}])
        time.sleep(0.06)
        send([{"key": "a", "down": False}])
        time.sleep(0.34)
    send([{"key": key, "down": False}])
    return True


def main(budget=900.0):
    history = pso_doors.History()
    doors = pso_doors.read(read)
    history.update(doors, cause="start")
    usable = [d for d in doors if pso_doors.usable(d)]
    closed = [d for d in doors if pso_doors.needs_clearing(d)]
    log(f"=== door-first; {len(doors)} doors, {len(usable)} usable, {len(closed)} closed; "
        f"hp={player_hp()} pos={tuple(round(v,1) for v in read_pos())}")
    for door in doors:
        log(f"  {door['class']:<16} ({door['x']:7.1f},{door['z']:7.1f}) state={door['state']}")
    started = time.time()
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED: {floor()}")
            cap.main()
            return 0
        me = read_pos()
        doors = pso_doors.read(read)
        changes = history.update(doors, cause="poll")
        for change in changes:
            log(f"  DOOR CHANGE {change['door']} ({change['class']}) {change['from']} -> {change['to']} "
                f"{'UNLOCKED' if change['unlocked'] else ''}")
        usable = [d for d in doors if pso_doors.usable(d)]
        near = pso_doors.nearest(usable, me, limit=90)
        if near:
            distance = math.dist(me, (near["x"], near["z"]))
            log(f"  heading for open door {near['index']} at ({near['x']:.0f},{near['z']:.0f}) "
                f"dist={distance:.0f} state={near['state']}")
            step_toward((near["x"], near["z"]), stop=7.0, budget=70.0)
            before = read_pos()
            for _ in range(6):
                facing = closing_key((near["x"], near["z"]))
                if facing:
                    hold(facing[0], 1.4)
            after = read_pos()
            log(f"    pushed: {tuple(round(v,1) for v in before)} -> {tuple(round(v,1) for v in after)}")
            if floor() != 1:
                log(f"FLOOR CHANGED: {floor()}")
                cap.main()
                return 0
            continue
        # no open door within reach: clear the room of the nearest closed door
        target = pso_doors.nearest(closed, me)
        if target is None:
            log("  no closed doors; heading to the key door")
            key = pso_doors.nearest(doors, me, predicate=lambda d: d["is_key"])
            if key:
                step_toward((key["x"], key["z"]), stop=7.0, budget=90.0)
            continue
        mobs = enemies()
        if mobs:
            target_enemy = min(mobs, key=lambda e: math.dist(me, (e["x"], e["z"])))
            distance = math.dist(me, (target_enemy["x"], target_enemy["z"]))
            if distance > 12:
                step_toward((target_enemy["x"], target_enemy["z"]), stop=9.0, budget=45.0)
            else:
                attack_while_stepping((target_enemy["x"], target_enemy["z"]))
                log(f"  attacked {target_enemy['class']} at {distance:.0f} units; "
                    f"enemies now {[(e['class'], e['hp']) for e in enemies()]}")
                cap.main()
        else:
            log(f"  no enemies but door {target['index']} still closed; approaching it")
            step_toward((target["x"], target["z"]), stop=7.0, budget=45.0)
            tap("a", 1, 0.5)
        if int(time.time() - started) % 120 < 2:
            cap.main()
    log(f"budget spent; hp={player_hp()} pos={tuple(round(v,1) for v in read_pos())}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
