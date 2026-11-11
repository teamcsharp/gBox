"""Heal at the Pioneer 2 hospital: walk to the medical door (193.5, -93.5), enter, find the nurse, and interact.

Town movement is flat and enemy-free, so the empirical stride walker (measure each key, use the one that closes) is enough. Inside,
the nurse NPC is read from the entity table and approached.
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
MED_DOOR = (193.5, -93.5)
LOG = r"D:\gBox\pso-ds\hospital.log"


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
        out.append((name, x, z))
    return out


def pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def hp():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    return int.from_bytes(read(actor + 0x32C, 2), "big"), int.from_bytes(read(actor + 0x2B8, 2), "big")


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
    time.sleep(0.05)


def tap(key, times=1, gap=0.5):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def walk_to(goal, budget=300.0, tolerance=8.0):
    started = time.time()
    while time.time() - started < budget:
        me = pos()
        if math.dist(me, goal) <= tolerance:
            return True
        bearing = unit(goal[0] - me[0], goal[1] - me[1])
        best = None
        for key in ("up", "down", "left", "right"):
            before = pos()
            hold(key, 0.45)
            after = pos()
            vector = (after[0] - before[0], after[1] - before[1])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            if best is None or align > best[1]:
                best = (key, align, length)
        if best is None:
            tap("b", 1, 0.4)
            continue
        hold(best[0], 0.9)
    return math.dist(pos(), goal) <= tolerance


def main():
    log(f"=== hospital trip; hp={hp()} pos={tuple(round(v,1) for v in pos())}")
    if not entities("TObjCityDoor"):
        controls("floor_warp", {"target": "0"})
        time.sleep(10)
    tap("b", 2, 0.5)
    log(f"town pos={tuple(round(v,1) for v in pos())}")
    reached = walk_to(MED_DOOR)
    log(f"at the medical door: reached={reached} pos={tuple(round(v,1) for v in pos())} hp={hp()}")
    cap.main()
    if reached:
        tap("a", 1, 1.0)
        hold("up", 1.2)
        log(f"inside? pos={tuple(round(v,1) for v in pos())} hp={hp()}")
        cap.main()
        nurses = entities("TObjNpcNurse")
        log(f"nurses: {[ (n[0], round(n[1]), round(n[2])) for n in nurses ]}")
        for _name, x, z in nurses:
            walk_to((x, z), budget=90.0, tolerance=6.0)
            tap("a", 3, 0.8)
            log(f"  at nurse: pos={tuple(round(v,1) for v in pos())} hp={hp()}")
            cap.main()
            if hp() and hp()[0] >= hp()[1]:
                break
    log(f"final hp={hp()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
