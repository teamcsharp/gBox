"""Launch a build and capture the first screens - no round needed for the font probe.

Waits for the host to be idle before launching (a display still tearing down produced
`dolphin exited 134: qt.qpa.xcb: could not connect to display :102` in round 56), captures early frames, and restores the
rotation in `finally` in the documented order.
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4gc-fontprobe"
TAG = sys.argv[2] if len(sys.argv) > 2 else "font"
FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 10
LAB = f"{HOME}/gBox_alt/re4-lab"
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"},
        "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}}


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read()[:300].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:200]}


def sessions():
    _, body = api("GET", "/api/sessions")
    return body if isinstance(body, list) else (body.get("sessions") or []) if isinstance(body, dict) else []


def running(game_id=None):
    return [row for row in sessions() if row.get("state") == "running"
            and (game_id is None or row.get("game_id") == game_id)]


def jobs_running():
    _, body = api("GET", "/api/jobs?limit=8")
    rows = body if isinstance(body, list) else (body.get("jobs") or []) if isinstance(body, dict) else []
    return [row for row in rows if row.get("state") == "running"]


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def pause_and_wait():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(30):
        time.sleep(4)
        if not running() and not jobs_running():
            return True
    return False


def restore():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


session = None
try:
    print("MARK host idle:", pause_and_wait(), flush=True)
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={BUILD}", {})
    job = body.get("id") if isinstance(body, dict) else None
    print("MARK launch", status, job, flush=True)
    for _ in range(36):
        time.sleep(5)
        for row in running(GC):
            session = row.get("session_id") or row.get("id")
        if session:
            break
    print("MARK session", session, flush=True)
    if not session and job:
        status, detail = api("GET", f"/api/jobs/{job}")
        print("MARK launch failed:", str(detail.get("error"))[:200], flush=True)
    from io import BytesIO

    from PIL import Image
    for step in range(FRAMES):
        time.sleep(10)
        if not session:
            break
        raw = frame(session)
        if not raw:
            continue
        path = f"{LAB}/{TAG}_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        grey = Image.open(BytesIO(raw)).convert("L")
        print("MARK %s_%02d mean %.1f -> %s" % (TAG, step, statistics.fmean(list(grey.getdata())), path), flush=True)
finally:
    restore()
