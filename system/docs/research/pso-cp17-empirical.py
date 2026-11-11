"""Walk a direction empirically: for each stride, measure what each key actually does right now, then use the key that moved the
character closest to the target. No key->world table survives the camera turning with the character, but a measurement taken
immediately before the stride cannot be stale.

The earlier calibrated walker orbited: alignment readings of 0.9-1.0 while the distance never fell, because the four-key calibration
rotates with the character. This measures each candidate key's displacement in the same breath as the stride that follows it.
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
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\cp17-empirical.log"


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


def key_doors():
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
        if not name.startswith("TObjDoorKey"):
            continue
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append((x, z))
    return out


def pos():
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


def tap(key, times=1, gap=0.4):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.04)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def main(budget=780.0):
    log("=== CP17 empirical-direction walker")
    me = pos()
    targets = key_doors()
    if not targets:
        log("no key doors")
        return 2
    goal = min(targets, key=lambda g: math.dist(me, g))
    log(f"start {tuple(round(v,1) for v in me)} goal {tuple(round(v,1) for v in goal)} "
        f"dist={math.dist(me, goal):.0f} floor={floor()}")
    tap("b", 2, 0.5)                                             # the arrival pad blocks movement
    started = time.time()
    stride = 0
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED BY WALKING: {floor()}")
            cap.main()
            return 0
        me = pos()
        distance = math.dist(me, goal)
        if distance <= 9:
            log("at the door; interact once")
            tap("a", 1, 0.8)
            for step in range(5):
                hold("up", 0.9)
                now = floor()
                log(f"  push {step}: floor={now} pos={tuple(round(v,1) for v in pos())}")
                if now != 1:
                    log(f"FLOOR CHANGED BY WALKING: {now}")
                    cap.main()
                    return 0
            cap.main()
            return 2
        bearing = unit(goal[0] - me[0], goal[1] - me[1])
        # measure each key's displacement now
        best = None
        for key in ("up", "down", "left", "right"):
            before = pos()
            hold(key, 0.4)
            after = pos()
            vector = (after[0] - before[0], after[1] - before[1])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            if best is None or align > best[1]:
                best = (key, align, length)
            if align > 0.92 and length > 8:
                break
        if best is None:
            log("  no key moves the character; pressing B")
            tap("b", 1, 0.4)
            continue
        key, align, length = best
        stride += 1
        if align > 0.25:
            hold(key, 0.9)
        else:
            # nothing points at the goal: walk by to rotate the frame
            hold(key, 0.5)
        if stride % 6 == 0:
            log(f"  stride {stride}: {math.dist(pos(), goal):.0f} units, key={key} align={align:.2f} "
                f"moved={length:.0f}, pos={tuple(round(v,1) for v in pos())}")
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
