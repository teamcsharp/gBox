"""Fight in Forest 1 through the focus+win_send_keys path: advance, attack, re-centre, capturing as it goes."""
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


def call(path, timeout=30):
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


def send(pid, keys, attempts=4):
    import ctypes
    user32 = ctypes.windll.user32
    events = []
    for key in keys:
        events += [{"key": key, "down": True}, {"key": key, "down": False}]
    for _ in range(attempts):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.25)
        try:
            answer = win_send_keys(pid, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.25)
    return {"sent": 0}


def main():
    sessions = [s for s in call("/api/sessions?include_ended=false") if s.get("state") == "running"]
    session, pid = sessions[0]["session_id"], sessions[0]["detail"]["pid"]
    print("session:", session, "pid:", pid)
    cap.main()
    for step in range(30):
        send(pid, ["a"])                                  # attack
        time.sleep(0.35)
        if step % 5 == 0:
            send(pid, ["up"])                              # advance a little
            time.sleep(0.5)
        if step % 10 == 0:
            send(pid, ["l"])                               # re-centre camera (GC L trigger)
        if step % 6 == 0:
            cap.main()
            print("step", step, flush=True)
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
