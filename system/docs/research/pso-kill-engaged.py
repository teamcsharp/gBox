"""Kill the Booma the character is engaged with: burst attacks, then read its HP and the player's HP back."""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
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
        out.append({"index": index, "class": name,
                    "hp": int.from_bytes(read(pointer + HP, 2), "big"),
                    "hp_max": int.from_bytes(read(pointer + HP_MAX, 2), "big"),
                    "x": x, "z": z})
    return out


def player():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    hp = int.from_bytes(read(actor + 0x32C, 2), "big")
    return x, y, z, hp


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


def main():
    print("player:", tuple(round(v, 1) for v in player()), "| enemies:", [(e["class"], e["hp"], e["hp_max"]) for e in enemies()])
    for burst in range(10):
        tap("a", 3, 0.35)
        me = player()
        mobs = enemies()
        print(f"burst {burst}: player hp={me[3]} pos=({me[0]:.0f},{me[2]:.0f}) "
              f"enemies={[(e['hp'], e['hp_max']) for e in mobs]}")
        if not mobs:
            print("all enemies gone")
            break
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
