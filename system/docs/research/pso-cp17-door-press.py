"""CP17 with the stall-triggered door press: any TObjDoor/TObjDoorKey within 32 units gets turned-to, A-pressed and pushed.

Round 201 diagnosed the last wall: every route ends against TObjDoor (253,92) and the walker only ever pressed A at the key door. This
version handles every door it comes near - turn toward it with a short hold of the direction that moves that way, press A, push, and
require a >8-unit jump - then continues the empirical stride walk to the key door. A tag per door stops it re-pressing the same one.
"""
import json
import math
import struct
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\cp17-final2.log"


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
        out.append({"class": name, "x": x, "z": z})
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
        time.sleep(0.04)
    try:
        return win_send_keys(PID, events)
    except Exception:                                            # noqa: BLE001
        return {}


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.04)


def tap(key, times=1, gap=0.3):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def measure_keys():
    """[(align_key, key, length)] for the four directions right now."""
    options = []
    for key in ("up", "down", "left", "right"):
        before = read_pos()
        hold(key, 0.35)
        after = read_pos()
        vector = (after[0] - before[0], after[1] - before[1])
        length = math.hypot(*vector)
        options.append((key, vector, length))
    return options


def push_door(door, tried):
    me = read_pos()
    bearing = unit(door["x"] - me[0], door["z"] - me[1])
    options = measure_keys()
    best = None
    for key, vector, length in options:
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if best is None or align > best[1]:
            best = (key, align, length)
    log(f"  door {door['class']} ({door['x']:.0f},{door['z']:.0f}) dist={math.dist(me, (door['x'], door['z'])):.0f}"
        f" facing-key={best[0] if best else None} align={best[1]:.2f}" if best else "  no facing key")
    keys = []
    if best and best[1] > 0.1:
        keys.append(best[0])
    if best:
        keys.append(best[0])
    for key in (keys or ["up"]):
        hold(key, 0.3)                                            # turn toward the door
        tap("a", 1, 0.5)
        before = read_pos()
        hold(key, 1.1)                                            # push
        after = read_pos()
        moved = math.dist(before, after)
        log(f"    {key}: pressed A and pushed, moved {moved:.0f} -> {tuple(round(v,1) for v in after)} floor={floor()}")
        if moved > 8:
            tried.add((round(door["x"]), round(door["z"])))
            return True
    tried.add((round(door["x"]), round(door["z"])))
    return False


def main(budget=780.0):
    log("=== CP17 stall-triggered door press")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(10)
    controls("stat", {"name": "atp", "value": 999})
    tap("b", 2, 0.5)
    keys = entities("TObjDoorKey")
    if not keys:
        log("no key doors")
        return 2
    me = read_pos()
    goal = min(((d["x"], d["z"]) for d in keys), key=lambda g: math.dist(me, g))
    log(f"start {tuple(round(v,1) for v in me)} goal {tuple(round(v,0) for v in goal)}")
    started = time.time()
    tried = set()
    stride = 0
    best = math.dist(me, goal)
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED: {floor()}")
            cap.main()
            return 0
        me = read_pos()
        distance = math.dist(me, goal)
        if distance <= 9:
            log("at the key door; opening it")
            if push_door({"class": "TObjDoorKey", "x": goal[0], "z": goal[1]}, tried):
                log("  key door opened")
                if floor() != 1:
                    log(f"FLOOR CHANGED: {floor()}")
                    cap.main()
                    return 0
            cap.main()
            continue
        near = sorted((d for d in entities("TObjDoor") if math.dist(me, (d["x"], d["z"])) <= 32
                       and (round(d["x"]), round(d["z"])) not in tried),
                      key=lambda d: math.dist(me, (d["x"], d["z"])))
        if near:
            push_door(near[0], tried)
            continue
        bearing = unit(goal[0] - me[0], goal[1] - me[1])
        options = []
        for key, vector, length in measure_keys():
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            options.append((align, key, length))
        if not options:
            tap("b", 1, 0.3)
            continue
        options.sort(reverse=True)
        align, key, _length = options[0]
        hold(key, 0.6 if distance > 30 else 0.35)
        stride += 1
        if distance < best - 1:
            best = distance
        if stride % 10 == 0:
            log(f"  stride {stride}: {math.dist(read_pos(), goal):.0f} units (best {best:.0f}), key={key} "
                f"align={align:.2f}, pos={tuple(round(v,1) for v in read_pos())}")
            cap.main()
    log(f"budget spent; {math.dist(read_pos(), goal):.0f} units from the key door")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
