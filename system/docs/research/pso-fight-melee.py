"""Hunt the Boomas at melee range: chase until within ~8 units, then strike.

Round 181's lesson: the earlier loop struck at 15-25 units, which is out of a saber's reach - the Dragon died because its hitbox is
huge. The engage threshold is now 8 units, and the log prints the enemy HP every strike so a landing hit is visible.
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
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
LOG = r"D:\gBox\pso-ds\enemy-hunt.log"
ENGAGE = 8.0


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))
        except Exception as exc:                                 # noqa: BLE001 - port pressure under a tight loop
            last = exc
            time.sleep(0.15 + 0.1 * attempt)
    raise last


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
        blob = read(pointer + 0x38, 12)
        x, _y, z = struct.unpack(">fff", blob)
        out.append({"index": index, "class": name,
                    "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "hp_max": int.from_bytes(read(pointer + HP_MAX, 2), "big"),
                    "x": x, "z": z})
    return out


def player():
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


def press(events):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(2):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.05)
        try:
            answer = win_send_keys(PID, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.05)
    return {"sent": 0}


def hold(key, seconds):
    press([{"key": key, "down": True}])
    time.sleep(seconds)
    press([{"key": key, "down": False}])
    time.sleep(0.03)


def tap(key, times=1, gap=0.22):
    for _ in range(times):
        press([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def signed_angle(a, b):
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def main(budget=420.0):
    started = time.time()
    log(f"melee hunt start (engage <= {ENGAGE:.0f} units)")
    while time.time() - started < budget:
        mobs = [m for m in enemies() if m["hp"] > 0]
        if not mobs:
            log("all enemy entities gone")
            break
        me = player()
        if me is None:
            time.sleep(1)
            continue
        target = min(mobs, key=lambda m: math.dist(me, (m["x"], m["z"])))
        distance = math.dist(me, (target["x"], target["z"]))
        if distance <= ENGAGE:
            before_hp = target["hp"]
            tap("a", 3, 0.3)
            after = [m for m in enemies() if m["index"] == target["index"]]
            after_hp = after[0]["hp"] if after else 0
            log(f"strike at {distance:.0f}: hp {before_hp} -> {after_hp} ({len(mobs)} alive)")
            continue
        before = me
        hold("up", 0.45)
        after = player()
        forward = unit(after[0] - before[0], after[1] - before[1])
        bearing = unit(target["x"] - after[0], target["z"] - after[1])
        if forward == (0.0, 0.0):
            hold("left", 0.3)
            continue
        angle = signed_angle(forward, bearing)
        if abs(angle) <= 25:
            hold("up", 0.55)
        else:
            hold("left" if angle > 0 else "right", min(0.45, 0.08 + abs(angle) / 250.0))
        if int(time.time()) % 20 < 2:
            log(f"chase {distance:.0f} units, angle {angle:.0f}, hp={target['hp']}/{target['hp_max']}")
    log("hunt done")
    tap("start", 1, 1.4)
    cap.main()
    log("panel captured")
    tap("b", 2, 0.4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
