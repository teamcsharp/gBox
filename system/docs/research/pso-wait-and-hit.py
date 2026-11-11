"""Let the Booma come, then hit it: idle until an enemy is adjacent, then spin-and-swing.

Boomas chase the player, so standing still brings the fight to the character - which is what a 10 HP Lv 1 needs, since chasing a
mobile enemy with discrete holds never closed inside 6 units. ATP is boosted, so one connecting hit on a 60 HP Booma kills it.
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
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8
LOG = r"D:\gBox\pso-ds\wait_and_hit.log"


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
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"class": name, "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "hp_max": int.from_bytes(read(pointer + HP_MAX, 2), "big"), "x": x, "z": z})
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


def tap(key, times=1, gap=0.25):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])
    time.sleep(0.03)


def main(budget=420.0):
    log("=== wait-and-hit")
    started = time.time()
    while time.time() - started < budget:
        mobs = [m for m in enemies() if m["hp"] > 0]
        if not mobs:
            log("no enemies left")
            return 0
        me = pos()
        target = min(mobs, key=lambda m: math.dist(me, (m["x"], m["z"])))
        distance = math.dist(me, (target["x"], target["z"]))
        if distance <= 14:
            for _ in range(3):
                hold("left", 0.16)
                tap("a", 2, 0.22)
            log(f"swung at {distance:.0f} units, hp={target['hp']}/{target['hp_max']}")
            if target["hp"] <= 0:
                log("a kill landed")
                cap.main()
                return 0
        else:
            time.sleep(1.2)                                      # let the Booma close
        if int(time.time() - started) % 45 < 2:
            log(f"  waiting: nearest {distance:.0f} units, hp={target['hp']}/{target['hp_max']}, "
                f"pos={tuple(round(v,1) for v in me)}")
            cap.main()
    log(f"budget spent; enemies {[(e['hp'], e['hp_max']) for e in enemies()]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
