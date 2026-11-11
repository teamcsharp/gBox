"""CP17 fastest walker: empirical strides (measure each key now, use the one that closes) + fight-on-stall + pad clear.

The calibrated walker drifts because its key->world table rotates with the camera; the empirical stride measures the movement it is
about to repeat, moves ~16 units per stride, and needs no table. Its failures were stalls: a Booma in contact or a menu. This handles
both - fight an adjacent enemy (boosted ATP kills a Booma in one hit) or press B - and clears the arrival pad at the start.
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
LOG = r"D:\gBox\pso-ds\cp17-fast.log"


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


def fight_if_adjacent():
    me = read_pos()
    near = [m for m in entities("TObjEne") if math.dist(me, (m["x"], m["z"])) <= 16]
    if not near:
        return False
    for _ in range(5):
        hold("left", 0.16)
        tap("a", 2, 0.2)
    return True


def main(budget=720.0):
    log("=== CP17 fast empirical walk")
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
    best = math.dist(me, goal)
    stride = 0
    while time.time() - started < budget:
        if floor() != 1:
            log(f"FLOOR CHANGED: {floor()}")
            cap.main()
            return 0
        me = read_pos()
        distance = math.dist(me, goal)
        if distance <= 9:
            log("at the key door")
            for attempt in range(3):
                tap("a", 1, 0.6)
                before = read_pos()
                hold("up", 1.1)
                after = read_pos()
                log(f"  attempt {attempt}: moved {math.dist(before, after):.0f}")
                if floor() != 1:
                    log(f"FLOOR CHANGED: {floor()}")
                    cap.main()
                    return 0
            cap.main()
            return 2
        bearing = unit(goal[0] - me[0], goal[1] - me[1])
        options = []
        for key in ("up", "down", "left", "right"):
            before = read_pos()
            hold(key, 0.4)
            after = read_pos()
            vector = (after[0] - before[0], after[1] - before[1])
            length = math.hypot(*vector)
            if length < 1.5:
                continue
            align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
            options.append((align, key, length))
        if not options:
            if fight_if_adjacent():
                log("  fought an adjacent enemy")
            else:
                tap("b", 1, 0.3)
            continue
        options.sort(reverse=True)
        align, key, _length = options[0]
        hold(key, 0.6 if distance > 30 else 0.35)
        stride += 1
        if distance < best - 1:
            best = distance
        if stride % 10 == 0:
            log(f"  stride {stride}: {math.dist(read_pos(), goal):.0f} units (best {best:.0f}), "
                f"key={key} align={align:.2f}, pos={tuple(round(v,1) for v in read_pos())}")
            cap.main()
    log(f"budget spent; {math.dist(read_pos(), goal):.0f} units from the key door")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
