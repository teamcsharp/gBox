"""Find the PSO menu/UI state byte: snapshot globals with the field active and again with the menu open, then diff.

Round 182 showed a menu freezes movement, and pressing A at a door opens one. Detecting it from RAM beats probing with B presses.
Regions chosen around the known UI/boot globals (BOOT_SCREEN 0x80516303) and the player/party area.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "75cf966f35164149-4ec5d512e3484b02"
PID = 36964
REGIONS = [(0x8050D000, 0x2000), (0x80516000, 0x4000), (0x80519000, 0x2000)]


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


def snapshot():
    return {base: read(base, size) for base, size in REGIONS}


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


def press(key, times=1, gap=0.6):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(times):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
        try:
            win_send_keys(PID, [{"key": key, "down": True}, {"key": key, "down": False}])
        except Exception as exc:                                 # noqa: BLE001
            print("press failed:", exc)
        time.sleep(gap)


def main():
    press("b", 3, 0.5)                                          # make sure the field is active
    time.sleep(0.5)
    field = snapshot()
    print("field snapshot taken; BOOT_SCREEN =", hex(read(0x80516303, 1)[0]))
    press("start", 1, 1.2)                                      # open the menu
    menu = snapshot()
    print("menu snapshot taken; BOOT_SCREEN =", hex(read(0x80516303, 1)[0]))
    changed = []
    for base, size in REGIONS:
        a, b = field[base], menu[base]
        for offset in range(min(len(a), len(b))):
            if a[offset] != b[offset]:
                changed.append((base + offset, a[offset], b[offset]))
    print(f"bytes that changed between field and menu: {len(changed)}")
    for address, before, after in changed[:60]:
        print(f"   {address:#010x}: {before:#04x} -> {after:#04x}")
    press("b", 3, 0.5)                                          # close again
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
