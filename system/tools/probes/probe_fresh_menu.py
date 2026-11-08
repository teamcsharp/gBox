"""Does a fresh save have THE MERCENARIES? Look at the menu instead of trusting either note.

Two statements disagree: gBox's session detail says *"RE4 Switch Mercenaries is available from a fresh save (no unlock needed)"*,
and the frame of a fresh save's main menu (round 83) showed NEW GAME / LOAD / LEADERBOARDS / HELP & OPTIONS / ACHIEVEMENTS with no
EXTRAS row. This presses START once and photographs the menu, with the save moved aside and put back in a `finally`.
"""
import json
import os
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
SWITCH = "270a15eb98dab4d7"
SAVE = (f"{HOME}/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/data/citron/"
        f"nand/user/save/0000000000000000/7027FDA9BE915B24FD085FC348A9C0BF/010099A00BC1E000/SAVEDATA000/savegame00.sav")
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


def rows(body, key):
    return body if isinstance(body, list) else (body.get(key) or []) if isinstance(body, dict) else []


def running():
    return [r for r in rows(api("GET", "/api/sessions")[1], "sessions") if r.get("state") == "running"]


def jobs_running():
    return [r for r in rows(api("GET", "/api/jobs?limit=8")[1], "jobs") if r.get("state") == "running"]


def stop_all():
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(20):
        time.sleep(3)
        if not running() and not jobs_running():
            return True
    return False


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def mean_of(raw):
    from io import BytesIO

    from PIL import Image
    return statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())) if raw else 0.0


def press(session, key):
    return api("POST", "/api/jobs", {"tool": "session_op", "require_worker": session.split("-")[0],
                                     "input": {"session_id": session, "op": "send_input",
                                               "args": {"events": [{"key": key, "down": True},
                                                                   {"key": key, "down": False}]}}})[0]


def restore_rotation():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    stop_all()


moved = None
try:
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    stop_all()
    subprocess.run(["bash", "-lc", "pkill -f citron-linux"], timeout=30)
    time.sleep(5)
    if os.path.isfile(SAVE):
        moved = f"{SAVE}.fresh-test-{int(time.time())}"
        shutil.move(SAVE, moved)
        print("MARK save moved aside", flush=True)
    api("POST", f"/api/games/{SWITCH}/launch?node=lilspark", {})
    session = None
    for _ in range(40):
        time.sleep(5)
        for row in running():
            if row.get("game_id") == SWITCH:
                session = row.get("session_id") or row.get("id")
        if session:
            break
    print("MARK session", session, flush=True)
    if not session:
        raise SystemExit("no session")
    for _ in range(24):
        time.sleep(8)
        raw = frame(session)
        if raw and mean_of(raw) > 15:
            break
    for step in range(3):
        press(session, "a")
        time.sleep(4)
        raw = frame(session)
        if raw:
            path = f"{LAB}/freshmenu_{step}.jpg"
            with open(path, "wb") as handle:
                handle.write(raw)
            print("MARK freshmenu_%d mean %.1f -> %s" % (step, mean_of(raw), path), flush=True)
finally:
    if moved and os.path.isfile(moved):
        shutil.move(moved, SAVE)
        print("MARK save restored", flush=True)
    restore_rotation()
