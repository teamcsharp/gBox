"""Does stopping the game at a menu stop the resume prompt coming back?

The hypothesis from round 90: the save is written when the session stops, and sessions stop while the game is mid-load, so every run
recreates the state that makes the next run start on "Cancel loading?". This tests it in four steps:

1. launch, answer the prompt with **Yes** (up, a) to reach a title screen;
2. wait until the picture is a menu (bright and changing);
3. stop the session *from there*;
4. launch again and look at the first frames.

A boot at `mean ~60` means the fix works; `mean ~19` means the prompt is back and the hypothesis is wrong.
"""
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
SWITCH = "270a15eb98dab4d7"
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


def strays():
    out = subprocess.run(["bash", "-lc", "pgrep -af 'citron-linux|eden-linux' | grep -v grep"],
                         capture_output=True, text=True, timeout=30).stdout
    return [line for line in out.splitlines() if line.strip()]


def clean():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(30):
        time.sleep(4)
        if not running() and not jobs_running():
            break
    for _ in range(2):
        if not strays():
            return
        subprocess.run(["bash", "-lc", "pkill -f citron-linux ; pkill -f eden-linux"], timeout=30)
        time.sleep(5)


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


def launch(build=None):
    url = f"/api/games/{SWITCH}/launch?node=lilspark" + (f"&mod={build}" if build else "")
    api("POST", url, {})
    session = None
    for _ in range(40):
        time.sleep(5)
        for row in running():
            if row.get("game_id") == SWITCH:
                session = row.get("session_id") or row.get("id")
        if session:
            break
    return session


def boot_means(session, samples=4, gap=10):
    means = []
    for _ in range(samples):
        time.sleep(gap)
        raw = frame(session)
        if raw:
            means.append(round(mean_of(raw), 1))
    return means


def restore():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


try:
    clean()
    first = launch()
    print("MARK first session", first, flush=True)
    if not first:
        raise SystemExit("no session")
    before = boot_means(first, 3, 8)
    print("MARK boot before:", before, flush=True)
    if before and before[-1] < 30:
        press(first, "up")
        time.sleep(0.6)
        press(first, "a")
        print("MARK answered Yes", flush=True)
        time.sleep(6)
        after_yes = boot_means(first, 3, 8)
        print("MARK after Yes:", after_yes, flush=True)
    # stop from whatever menu is up now: this is the step that should write a menu-state save
    api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": first, "op": "stop_game", "args": {}}})
    time.sleep(10)
    print("MARK stopped from the menu", flush=True)
    second = launch()
    print("MARK second session", second, flush=True)
    if second:
        print("MARK boot after:", boot_means(second, 4, 9), flush=True)
finally:
    restore()
