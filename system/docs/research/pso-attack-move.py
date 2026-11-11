"""Attack while stepping toward the enemy: hold the direction that closes as you swing, so the character turns into the swing.

The room-fight loop failed with the Bm5Wolf 45/45 even when it stood a few units away and clearly visible in the screenshot: the
character was facing away from it, and a pure A press attacks where you already face. Holding the direction key while tapping A makes
the character step/turn toward the enemy, and a boosted ATP hit kills a 45 HP wolf.
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
LOG = r"D:\gBox\pso-ds\attack_move.log"


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
        x, y, z = struct.unpack(">fff", read(pointer + 0x38, 12))
        out.append({"class": name, "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "hp_max": int.from_bytes(read(pointer + HP_MAX, 2), "big"), "x": x, "y": y, "z": z})
    return out


def read_pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, _y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return x, z


def hp():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    return int.from_bytes(read(actor + HP, 2), "big"), int.from_bytes(read(actor + HP_MAX, 2), "big")


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
    time.sleep(0.03)


def unit(dx, dz):
    length = math.hypot(dx, dz)
    return (dx / length, dz / length) if length > 1e-6 else (0.0, 0.0)


def closing_key(goal):
    me = read_pos()
    bearing = unit(goal[0] - me[0], goal[1] - me[1])
    best = None
    for key in ("up", "down", "left", "right"):
        before = read_pos()
        hold(key, 0.22)
        after = read_pos()
        vector = (after[0] - before[0], after[1] - before[1])
        length = math.hypot(*vector)
        if length < 0.5:
            continue
        align = (vector[0] / length) * bearing[0] + (vector[1] / length) * bearing[1]
        if best is None or align > best[1]:
            best = (key, align)
    return best


def attack_while_stepping(key, swings=3):
    """Hold the direction and swing: the character turns into the swing and closes distance at the same time."""
    events = [{"key": key, "down": True}]
    send(events)
    time.sleep(0.18)
    for _ in range(swings):
        send([{"key": "a", "down": True}])
        time.sleep(0.06)
        send([{"key": "a", "down": False}])
        time.sleep(0.34)
    send([{"key": key, "down": False}])
    time.sleep(0.05)


def main(budget=180.0):
    log(f"=== attack-while-stepping; player {tuple(round(v,1) for v in read_pos())} hp={hp()} "
        f"enemies={[(e['class'], e['hp']) for e in enemies()]}")
    started = time.time()
    while time.time() - started < budget:
        mobs = [e for e in enemies() if e["hp"] > 0]
        if not mobs:
            log("room clear")
            cap.main()
            return 0
        me = read_pos()
        target = min(mobs, key=lambda e: math.dist(me, (e["x"], e["z"])))
        distance = math.dist(me, (target["x"], target["z"]))
        facing = closing_key((target["x"], target["z"]))
        if not facing:
            log("no direction moves; pressing B")
            send([{"key": "b", "down": True}, {"key": "b", "down": False}])
            time.sleep(0.4)
            continue
        key, align = facing
        log(f"  wolf at {distance:.0f} units, key={key} align={align:.2f}, hp={target['hp']}/{target['hp_max']}")
        attack_while_stepping(key, swings=3)
        now = [(e["class"], e["hp"]) for e in enemies()]
        log(f"    after swings: {now} player_hp={hp()}")
        if any(e["hp"] <= 0 for e in enemies()) or not enemies():
            log("a kill landed")
            cap.main()
            return 0
        if int(time.time() - started) % 40 < 2:
            cap.main()
    log(f"budget spent: {[(e['class'], e['hp']) for e in enemies()]} player_hp={hp()}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
