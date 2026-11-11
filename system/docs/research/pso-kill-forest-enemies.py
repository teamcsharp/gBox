"""Kill Forest 1's remaining enemies with the lock-on loop so the door walk is not interrupted by hitstun."""
import json
import math
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
PID = 37032
TABLE, MAX_ENTRIES, HP, HP_MAX = 0x8050D460, 256, 0x32C, 0x2B8


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
        out.append({"id": index, "class": name, "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "hp_max": int.from_bytes(read(pointer + HP_MAX, 2), "big"), "x": x, "z": z})
    return out


def player():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    return struct.unpack(">fff", read(actor + 0x38, 12))


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


def tap(key, times=1, gap=0.3):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(times):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
        try:
            win_send_keys(PID, [{"key": key, "down": True}, {"key": key, "down": False}])
        except Exception:                                        # noqa: BLE001
            pass
        time.sleep(gap)


def hold(key, seconds):
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = gbox_hwnd()
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
    try:
        win_send_keys(PID, [{"key": key, "down": True}])
        time.sleep(seconds)
        win_send_keys(PID, [{"key": key, "down": False}])
    except Exception:                                            # noqa: BLE001
        pass
    time.sleep(0.06)


def main():
    for attempt in range(30):
        mobs = [m for m in enemies() if m["hp"] > 0]
        me = player()
        if not mobs:
            print("no enemies left")
            break
        target = min(mobs, key=lambda m: math.dist((me[0], me[2]), (m["x"], m["z"])))
        distance = math.dist((me[0], me[2]), (target["x"], target["z"]))
        print(f"attempt {attempt}: {len(mobs)} enemies; target at {distance:.0f} units hp={target['hp']}/{target['hp_max']}")
        if distance > 20:
            tap("l", 1, 0.3)
            hold("up", 1.0)
        else:
            tap("a", 4, 0.3)
    print("final:", [(m["class"], m["hp"], m["hp_max"]) for m in enemies()])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
