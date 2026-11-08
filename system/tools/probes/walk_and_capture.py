"""Walk to a Mercenaries round by pressing directly, with no autoplay thread in the way.

The input path is proven (one `a` moves the picture), and the autoplay playbook's presses did not move a stuck menu, so this
drives the same route the driver already describes - frame, classify, one key - through `session_op send_input` and nothing
else. It is the harness that reached rounds in earlier rounds, with the two fixes since: stray emulators are killed first, and
the picture must be alive before the walk starts.
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
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-plhalf"
TAG = sys.argv[2] if len(sys.argv) > 2 else "walk"
FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 10
LAB = f"{HOME}/gBox_alt/re4-lab"
PROMPT_KEYS = ("a", "b", "down", "a", "up", "b")   # what a trapped Yes/No can want, tried in turn rather than repeated
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"},
        "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}}
sys.path.insert(0, f"{HOME}/gBox/system")
from gbox.mercs.titles import re4_switch as D          # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S  # noqa: E402


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


def pause_and_clean():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(30):
        time.sleep(4)
        if not running() and not jobs_running():
            break
    for _ in range(3):
        if not strays():
            return True
        subprocess.run(["bash", "-lc", "pkill -f citron-linux ; pkill -f eden-linux"], timeout=30)
        time.sleep(5)
    return not strays()


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def press(session, key):
    return api("POST", "/api/jobs", {"tool": "session_op", "require_worker": session.split("-")[0],
                                     "input": {"session_id": session, "op": "send_input",
                                               "args": {"events": [{"key": key, "down": True},
                                                                   {"key": key, "down": False}]}}})[0]


def mean_of(raw):
    from io import BytesIO

    from PIL import Image
    return statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())) if raw else 0.0


def restore():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


session = None
try:
    print("MARK cleaned:", pause_and_clean(), "| strays:", len(strays()), flush=True)
    url = f"/api/games/{SWITCH}/launch?node=lilspark" if BUILD == "stock" else \
        f"/api/games/{SWITCH}/launch?node=lilspark&mod={BUILD}"
    status, body = api("POST", url, {})
    print("MARK launch", status, flush=True)
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
    for _ in range(30):
        time.sleep(8)
        raw = frame(session)
        if raw and mean_of(raw) > 15:
            break
    print("MARK picture up", flush=True)

    D.begin_run()
    reader = S.Reader()
    previous_raw = None
    settled_count = 0
    last, last_where, seen_stage, reached, steps = 0.0, None, False, False, 0
    prompt_steps, prompt_where = 0, None
    prompt_seen, resume_attempts = 0, 0
    for _ in range(45):
        raw = frame(session)
        if raw is None:
            time.sleep(4)
            continue
        settled = raw == previous_raw          # the prompt accepts input only once it has stopped animating
        previous_raw = raw
        settled_count = settled_count + 1 if settled else 0
        screen = reader.read(raw)
        where = screen.get("where")
        if where != last_where:
            last_where = where
        seen_stage = seen_stage or where == "select_stage"
        target = D.EXTRAS_ROW if where == "main_menu" else (D.MERCENARIES_ROW if where == "extras_menu" else None)
        # the driver's own per-screen gap: a flat 3.5 s presses a second confirm while the fade is still running, and that
        # second confirm lands on LOAD - which is exactly the menu the walk then cannot leave (measured this round)
        gap = D.CONFIRM_GAP_S.get(where, 3.0)
        key = D.step({**screen, "target": target}) if time.monotonic() - last > gap else None
        if key:
            press(session, key)
            D.pressed(screen, key)
            last = time.monotonic()
            steps += 1
        elif where == "playing":
            # "playing" IS the round: the classifier names it, and waiting for "unknown" instead made the harness keep
            # pressing through a reached round until it opened the quit dialog (measured 2026-11-08, two attempts)
            reached = True
            break
        elif where == "unknown" and seen_stage:
            for _ in range(3):
                press(session, "a")
                steps += 1
                time.sleep(1.5)
            reached = True
            break
        elif where == "story_prompt":
            # The save was written mid-load, so the game boots asking "Cancel loading? Yes/No" with No selected. Declining
            # only returns to the list; the way to a title screen is YES. The press must wait for the prompt to be steady -
            # pressing during the fade does nothing and looks exactly like a wrong key (round 83) - and it is retried,
            # because the first attempt can land while the dialog is still animating.
            prompt_seen += 1
            if settled_count < 2:              # two identical frames: the dialog has stopped moving, not just paused
                time.sleep(1.2)
                continue
            if resume_attempts < 3:
                resume_attempts += 1
                prompt_seen = 0
                settled_count = 0
                time.sleep(0.8)
                press(session, "up")
                time.sleep(0.6)
                press(session, "a")
                steps += 2
                last = time.monotonic()
                print(f"MARK resume prompt: Yes attempt {resume_attempts}", flush=True)
                time.sleep(1.5)
            else:
                key = D._recover_story()
                if key is None:
                    print("MARK prompt will not clear; stopping the walk", flush=True)
                    break
                press(session, key)
                steps += 1
                last = time.monotonic()
        elif time.monotonic() - last > 14:
            # a menu nothing names: back out once, the way the playbook's escape does
            press(session, "b")
            steps += 1
            last = time.monotonic()
        time.sleep(3)
    print(f"MARK walk steps {steps} | reached {reached} | last screen {last_where}", flush=True)
    for step in range(FRAMES):
        # STAND STILL and let the Ganados come: they path to the player, and running away kept the frame empty of them for a
        # dozen rounds. A tap on the aim button raises the camera without moving the feet.
        if step % 3 == 0:
            api("POST", "/api/jobs", {"tool": "session_op", "require_worker": session.split("-")[0],
                                      "input": {"session_id": session, "op": "send_input",
                                                "args": {"events": [{"key": "zl", "down": True}]}}})
            time.sleep(0.4)
            api("POST", "/api/jobs", {"tool": "session_op", "require_worker": session.split("-")[0],
                                      "input": {"session_id": session, "op": "send_input",
                                                "args": {"events": [{"key": "zl", "down": False}]}}})
        time.sleep(5.0)
        raw = frame(session)
        if not raw:
            continue
        path = f"{LAB}/{TAG}_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        print("MARK %s_%02d mean %.1f -> %s" % (TAG, step, mean_of(raw), path), flush=True)
finally:
    restore()
