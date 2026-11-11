"""Drive PSO from SELECT GAME MODE to the field, retrying each press with a fresh focus (the harness window steals it)."""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"


def call(path, timeout=60):
    req = urllib.request.Request(API + path, headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


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


def press(pid, keys, attempts=6):
    import ctypes
    user32 = ctypes.windll.user32
    events = []
    for key in keys:
        events += [{"key": key, "down": True}, {"key": key, "down": False}]
    for attempt in range(attempts):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd) if hasattr(user32, "SetFocus") else None
            time.sleep(0.35)
        try:
            answer = win_send_keys(pid, events)
            if answer.get("sent"):
                return answer
        except Exception as exc:                                 # noqa: BLE001
            if attempt == attempts - 1:
                return {"error": str(exc)[:80]}
        time.sleep(0.3)
    return {"sent": 0}


def slots(session):
    body = json.dumps({"op": "read_memory", "args": {"address": 0x8050EA10, "length": 16}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{session}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def main():
    sessions = [s for s in call("/api/sessions?include_ended=false") if s.get("state") == "running"]
    session, pid = sessions[0]["session_id"], sessions[0]["detail"]["pid"]
    print("session:", session, "pid:", pid)
    for step in range(10):
        print(f"step {step}: press a ->", press(pid, ["a"]))
        time.sleep(3.0)
        try:
            raw = slots(session)
            print("   slots:", raw[:8] if isinstance(raw, str) else raw)
            if isinstance(raw, str) and int(raw[0:8], 16):
                print("IN GAME")
                cap.main()
                return 0
        except Exception as exc:                                 # noqa: BLE001
            print("   slots:", exc)
        cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
