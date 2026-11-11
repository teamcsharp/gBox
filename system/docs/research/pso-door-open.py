"""Open the door at (253, 92) that stands between the character and the key door: approach, press A, push through, repeat."""
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
LOG = r"D:\gBox\pso-ds\door_open.log"


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


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def doors():
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
        if not name.startswith("TObjDoor"):
            continue
        x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"class": name, "x": x, "y": y, "z": z})
    return out


def pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, y, z


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


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.05)


def tap(key, times=1, gap=0.5):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def walk(goal, budget=120.0, tolerance=6.0):
    started = time.time()
    while time.time() - started < budget:
        me = pos()
        if math.dist((me[0], me[2]), goal) <= tolerance:
            return True
        bearing = unit(goal[0] - me[0], goal[1] - me[2])
        best = None
        for key in ("up", "down", "left", "right"):
            before = pos()
            hold(key, 0.4)
            after = pos()
            vector = (after[0] - before[0], after[2] - before[2])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            if best is None or align > best[1]:
                best = (key, align)
        if best is None:
            return False
        hold(best[0], 0.8)
    me = pos()
    return math.dist((me[0], me[2]), goal) <= tolerance


def main(budget=420.0):
    log(f"=== door opening; pos={tuple(round(v,1) for v in pos())}")
    started = time.time()
    while time.time() - started < budget:
        me = pos()
        candidates = sorted(doors(), key=lambda d: math.dist((me[0], me[2]), (d["x"], d["z"])))
        if not candidates:
            log("no doors in this area")
            return 2
        door = candidates[0]
        distance = math.dist((me[0], me[2]), (door["x"], door["z"]))
        log(f"nearest {door['class']} at ({door['x']:.0f},{door['z']:.0f}) dist={distance:.0f}")
        if distance > 25:
            walk((door["x"], door["z"]), budget=90.0)
            continue
        tap("a", 1, 0.8)
        before = pos()
        hold("up", 1.4)
        after = pos()
        log(f"  pushed: {tuple(round(v,1) for v in before)} -> {tuple(round(v,1) for v in after)} "
            f"(moved {math.dist((before[0],before[2]),(after[0],after[2])):.0f})")
        cap.main()
        if math.dist((before[0], before[2]), (after[0], after[2])) > 12:
            log("  passed through")
    log("budget spent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
