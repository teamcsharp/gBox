"""CP17 integrated loop: fight anything that blocks, then resume the walk along the collision route.

Forest 1 keeps producing Boomas, and each one locks the character in melee. This alternates: if a living enemy is within melee
range, face-and-strike it (ATP 999 one-shots a Booma); otherwise steer along the route with pso_kbwalk.steer_walk. It watches
pso_ram.floor throughout and tries the key door when it arrives.
"""
import json
import math
import struct
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox import pso_kbwalk, pso_walk                              # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
FLOOR = 0x805D5FC0
REL = Path(r"D:\gBox\pso-ds\rel\map_forest01c.rel")
LOG = r"D:\gBox\pso-ds\cp17-loop.log"


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


def floor():
    return int.from_bytes(read(FLOOR, 4), "big")


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def entities(prefix):
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
        if not name.startswith(prefix):
            continue
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        row = {"index": index, "class": name, "x": x, "z": z}
        if prefix == "TObjEne":
            row["hp"] = int.from_bytes(read(pointer + HP, 2), "big")
            row["hp_max"] = int.from_bytes(read(pointer + HP_MAX, 2), "big")
        out.append(row)
    return out


def read_pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


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
        time.sleep(0.05)
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}


def hold(keys, seconds):
    if isinstance(keys, str):
        keys = [keys]
    keys = list(keys)
    if not keys:
        return
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.03)


def tap(key, times=1, gap=0.2):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def signed_angle(a, b):
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def face_and_strike(target, attempts=8):
    for _ in range(attempts):
        me = read_pos()
        before = me
        hold("up", 0.3)
        after = read_pos()
        forward = unit(after[0] - before[0], after[1] - before[1])
        bearing = unit(target["x"] - after[0], target["z"] - after[1])
        distance = math.dist(after, (target["x"], target["z"]))
        if forward == (0.0, 0.0):
            tap("b", 1, 0.2)
            continue
        angle = signed_angle(forward, bearing)
        if abs(angle) <= 35 and distance <= 15:
            tap("a", 3, 0.2)
            return True
        if abs(angle) <= 35:
            hold("up", 0.5)
        else:
            hold("left" if angle > 0 else "right", min(0.35, 0.08 + abs(angle) / 260.0))
    return False


def main(budget=840.0):
    log("=== CP17 fight-and-walk loop")
    collision = REL.read_bytes()
    me = read_pos()
    doors = [d for d in entities("TObjDoor") if d["class"].startswith("TObjDoorKey")]
    if not doors:
        log("no key doors")
        return 2
    goal = min(((d["x"], d["z"]) for d in doors), key=lambda g: math.dist(me, g))
    log(f"goal {tuple(round(v,0) for v in goal)} dist={math.dist(me, goal):.0f}")
    started = time.time()
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        me = read_pos()
        distance = math.dist(me, goal)
        if distance <= 10:
            log("at the door; interacting")
            tap("a", 1, 0.8)
            for step in range(4):
                hold("up", 0.9)
                now = floor()
                log(f"  push {step}: floor={now}")
                if now != 1:
                    log(f"FLOOR CHANGED BY WALKING: {now}")
                    cap.main()
                    return 0
            log("no floor change at the door")
            return 2
        mobs = [m for m in entities("TObjEne") if m.get("hp", 0) > 0]
        near = [m for m in mobs if math.dist(me, (m["x"], m["z"])) <= 25]
        if near:
            target = min(near, key=lambda m: math.dist(me, (m["x"], m["z"])))
            log(f"  fighting {target['class']} at {math.dist(me, (target['x'], target['z'])):.0f} units "
                f"hp={target['hp']}/{target['hp_max']}")
            face_and_strike(target)
            continue
        route = pso_walk.path(collision, me, goal)
        if not route:
            log("  no route")
            return 2
        try:
            pso_kbwalk.steer_walk(read_pos, hold, route[0], tolerance=6.0, max_steps=6)
        except RuntimeError as exc:
            log(f"  steer failed: {exc}")
            tap("b", 2, 0.3)
        if int(time.time() - started) % 60 < 3:
            log(f"  walking: {math.dist(read_pos(), goal):.0f} units, pos={tuple(round(v,1) for v in read_pos())}")
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
