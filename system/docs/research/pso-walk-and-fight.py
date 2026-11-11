"""Walk with intent: hold a direction for real, then fight. The old driver tapped the stick (down+up in one batch = about two
frames), which is why its 15-minute recording covered 64 units and ten cells - the character stood and swung.

win_send_keys accepts a down event and an up event separately, so a hold is two calls with a sleep in between.
"""
import argparse
import json
import random
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402
from gbox.adapters import win_send_keys                            # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
LOG = r"D:\gBox\pso-ds\forest-drive.log"


def call(path, timeout=30):
    req = urllib.request.Request(API + path, headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def log(line: str) -> None:
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


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


def raw(pid, events, attempts=3):
    import ctypes
    user32 = ctypes.windll.user32
    for _ in range(attempts):
        hwnd = gbox_hwnd()
        if hwnd:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
        try:
            answer = win_send_keys(pid, events)
            if answer.get("sent"):
                return answer
        except Exception:                                        # noqa: BLE001
            time.sleep(0.15)
    return {"sent": 0}


def hold(pid, key, seconds):
    raw(pid, [{"key": key, "down": True}])
    time.sleep(seconds)
    raw(pid, [{"key": key, "down": False}])


def tap(pid, key):
    raw(pid, [{"key": key, "down": True}, {"key": key, "down": False}])


def position(session):
    body = json.dumps({"op": "read_memory", "args": {"address": 0x8050EA10, "length": 4}}).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{session}/rpc", data=body, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b'""')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--shot-every", type=float, default=60)
    args = ap.parse_args()
    sessions = [s for s in call("/api/sessions?include_ended=false") if s.get("state") == "running"]
    if not sessions:
        log("no running session")
        return 1
    session, pid = sessions[0]["session_id"], sessions[0]["detail"]["pid"]
    log(f"walk-and-fight driver on {session} pid {pid}")
    started = last_shot = time.time()
    laps = 0
    while time.time() - started < args.seconds:
        key = random.choice(["up", "up", "left", "right", "down"])
        seconds = random.uniform(0.6, 1.4)
        log(f"lap {laps}: hold {key} {seconds:.1f}s")
        hold(pid, key, seconds)
        tap(pid, "l")                                    # re-centre the camera behind the character
        for _ in range(random.randint(3, 6)):
            tap(pid, "a")
            time.sleep(0.4)
        laps += 1
        if time.time() - last_shot >= args.shot_every:
            cap.main()
            log(f"captured after lap {laps}")
            last_shot = time.time()
    log(f"stopped after {laps} laps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
