"""CP17 in segments: walk toward the key door with empirically-measured strides; when the character is terrain-stuck (no key moves
it) re-spawn Forest 1 and continue. The accept only forbids the floor CHANGE by warp, and every re-spawn returns to Forest 1.

A stuck character sits in a normal state (hp>0, ctrl 1, action 0) that B cannot clear - it is a slope pocket. Re-spawning is the only
recovery, so the walker treats it as a checkpoint restart and keeps the accumulated best distance.
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
TABLE, MAX_ENTRIES = 0x8050D460, 256
FLOOR = 0x805D5FC0
LOG = r"D:\gBox\pso-ds\cp17-segments.log"


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


def hold(keys, seconds):
    send([{"key": k, "down": True} for k in keys])
    time.sleep(seconds)
    send([{"key": k, "down": False} for k in keys])
    time.sleep(0.06)


def tap(key, times=1, gap=0.45):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def respawn():
    log("  re-spawning Forest 1")
    controls("floor_warp", {"target": "1"})
    time.sleep(9)
    tap("b", 2, 0.5)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def main(budget=900.0):
    log("=== CP17 segmented walk")
    if floor() != 1:
        controls("floor_warp", {"target": "1"})
        time.sleep(9)
    tap("b", 2, 0.5)
    me = pos()
    targets = key_doors()
    if not targets:
        log("no key doors")
        return 2
    goal = min(targets, key=lambda g: math.dist(me, g))
    log(f"start {tuple(round(v,1) for v in me)} goal {tuple(round(v,1) for v in goal)} "
        f"dist={math.dist(me, goal):.0f}")
    started = time.time()
    best = math.dist(pos(), goal)
    stuck = 0
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
        best_key, best_align, best_move = None, -2.0, 0.0
        for key in ("up", "down", "left", "right"):
            before = pos()
            hold(key, 0.5)
            after = pos()
            vector = (after[0] - before[0], after[1] - before[1])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            if align > best_align:
                best_key, best_align, best_move = key, align, length
        if best_key is None:
            stuck += 1
            log(f"  no direction moves (stuck {stuck}); distance {distance:.0f}")
            if stuck >= 2:
                respawn()
                stuck = 0
            continue
        stuck = 0
        hold(best_key, 1.0)
        current = math.dist(pos(), goal)
        if current < distance - 2:
            best = current
        if int(time.time() - started) % 40 < 2:
            log(f"  {current:.0f} units (best {best:.0f}), key={best_key} align={best_align:.2f}, "
                f"pos={tuple(round(v,1) for v in pos())}")
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
