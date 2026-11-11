"""CP18 accepting run: chase the Dragon by its RAM position and attack until its HP from RAM reaches 0.

Reads the entity table (0x8050D460), finds TBoss1Dragon, steers with the probe-and-turn controller toward its position, attacks in
range, and logs HP every cycle. survival is on, so a Lv 1 death does not end the run. The accept condition is the HP read hitting 0.
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
LOG = r"D:\gBox\pso-ds\dragon-hp.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))


def cstring(address, limit=40):
    raw = read(address, limit)
    return raw.split(b"\x00")[0].decode("ascii", "replace") if raw else ""


def boss():
    raw = read(TABLE, MAX_ENTRIES * 4)
    best = None
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        name_pointer = int.from_bytes(read(pointer, 4), "big")
        if not (0x80000000 <= name_pointer < 0x81800000):
            continue
        name = cstring(name_pointer)
        if not name.startswith("TBoss1Dragon") or "Colli" in name:
            continue
        hp = int.from_bytes(read(pointer + HP, 2), "big")
        hp_max = int.from_bytes(read(pointer + HP_MAX, 2), "big")
        x, _y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        best = {"hp": hp, "hp_max": hp_max, "x": x, "z": z}
    return best


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
            time.sleep(0.06)
        try:
            answer = win_send_keys(PID, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.06)
    return {"sent": 0}


def hold(key, seconds):
    press([{"key": key, "down": True}])
    time.sleep(seconds)
    press([{"key": key, "down": False}])
    time.sleep(0.04)


def tap(key, times=1, gap=0.25):
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
    log("CP18 run: chasing the Dragon by RAM position (survival on)")
    while time.time() - started < budget:
        boss_now = boss()
        if boss_now is None:
            log("no Dragon entity - checking again")
            time.sleep(2)
            continue
        if boss_now["hp"] <= 0:
            log(f"DRAGON DEFEATED: hp={boss_now['hp']}/{boss_now['hp_max']} (RAM read)")
            cap.main()
            return 0
        me = player()
        if me is None:
            time.sleep(1)
            continue
        distance = math.dist(me, (boss_now["x"], boss_now["z"]))
        if distance <= 45:
            tap("a", 4, 0.3)                                   # in range: strike
            log(f"attack at {distance:.0f} units; boss hp={boss_now['hp']}/{boss_now['hp_max']}")
        else:
            before = me
            hold("up", 0.5)
            after = player()
            forward = unit(after[0] - before[0], after[1] - before[1])
            bearing = unit(boss_now["x"] - after[0], boss_now["z"] - after[1])
            if forward == (0.0, 0.0):
                hold("left", 0.3)
                continue
            angle = signed_angle(forward, bearing)
            if abs(angle) <= 30:
                hold("up", 0.7)
            else:
                hold("left" if angle > 0 else "right", min(0.5, 0.1 + abs(angle) / 220.0))
            log(f"chase: {distance:.0f} units, angle {angle:.0f}, boss hp={boss_now['hp']}/{boss_now['hp_max']}")
        if int(time.time() - started) % 30 < 3:
            cap.main()
    log("budget spent")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
