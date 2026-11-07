"""Play RE4 GameCube with the Sonic build and capture it.

`~/gBox_alt/gbox-cache/mods/78ab9efa2e310db4/re4gsonic1512/re4-d1.iso` is a patched disc built 2026-11-06 - the Sonic
player models already in place - so this is a launch and a look, not a rebuild. The GameCube bot is started with
`mode=playbook` (the document's advice: `mode=auto` falls back silently to vision), and the rotation is restored in a
`finally` in the documented order.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
BUILD = "re4gsonic_real"
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
        return exc.code, {"detail": exc.read()[:200].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:150]}


def sessions():
    _, body = api("GET", "/api/sessions")
    return body if isinstance(body, list) else (body.get("sessions") or []) if isinstance(body, dict) else []


def running(game_id=None):
    return [row for row in sessions() if row.get("state") == "running"
            and (game_id is None or row.get("game_id") == game_id)]


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def pause():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(20):
        time.sleep(3)
        if not running():
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
    print("MARK paused:", pause(), flush=True)
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={BUILD}", {})
    for _ in range(40):
        time.sleep(5)
        for row in running(GC):
            session = row.get("session_id") or row.get("id")
            break
        if session:
            break
    print("MARK session", session, flush=True)
    if not session:
        raise SystemExit("no GameCube session")
    time.sleep(40)                                  # Dolphin boot
    status, started = api("POST", "/api/jobs", {"tool": "autoplay", "require_worker": session.split("-")[0],
                                                "input": {"session_id": session, "op": "start", "mode": "playbook"}})
    print("MARK autoplay", status, json.dumps(started)[:220], flush=True)
    from io import BytesIO

    from PIL import Image
    for step in range(12):
        time.sleep(12)
        raw = frame(session)
        if not raw:
            continue
        path = f"{LAB}/sonic_run_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        grey = Image.open(BytesIO(raw)).convert("L")
        import statistics
        print("MARK frame %02d mean %.1f -> %s" % (step, statistics.fmean(list(grey.getdata())), path), flush=True)
    print("MARK autoplay status:", json.dumps(api("POST", "/api/jobs", {"tool": "autoplay", "input": {
        "session_id": session, "op": "status"}})[1])[:300], flush=True)
finally:
    if session:
        api("POST", "/api/jobs", {"tool": "autoplay", "input": {"session_id": session, "op": "stop"}})
    restore()
