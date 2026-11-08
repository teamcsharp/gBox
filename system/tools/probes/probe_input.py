"""Does one key change the picture? A two-frame input assertion before any walking.

Round 73 left a run sitting on "Cancel loading? Yes/No" while the playbook pressed back every twelve seconds, so the keys were
either not sent, not delivered, or delivered to a process whose frames are not the ones being read. This answers it directly:
launch, wait for a live picture, send one key, and look at the next frame. No menus are walked and nothing is measured until
the answer is yes.

It also prints the session's own view of the input path (sent count / last key) so a silent adapter is visible.
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
                                                                   {"key": key, "down": False}]}}})


def mean_of(raw):
    from io import BytesIO

    from PIL import Image
    return statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())) if raw else None


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
    status, body = api("POST", f"/api/games/{SWITCH}/launch?node=lilspark&mod={BUILD}", {})
    print("MARK launch", status, (body.get("id") if isinstance(body, dict) else ""), flush=True)
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
        if raw and (mean_of(raw) or 0) > 15:
            with open(f"{LAB}/input_before.jpg", "wb") as handle:
                handle.write(raw)
            print(f"MARK picture up: mean {mean_of(raw):.1f}", flush=True)
            break
    before = frame(session)
    status, reply = press(session, "a")
    print("MARK press a ->", status, json.dumps(reply)[:160], flush=True)
    time.sleep(2.0)
    after = frame(session)
    print("MARK 'a' changed the picture:", before != after,
          "| means", round(mean_of(before) or 0, 1), "->", round(mean_of(after) or 0, 1), flush=True)
    time.sleep(1.0)
    before2 = frame(session)
    status, reply = press(session, "b")
    print("MARK press b ->", status, json.dumps(reply)[:160], flush=True)
    time.sleep(2.0)
    after2 = frame(session)
    print("MARK 'b' changed the picture:", before2 != after2,
          "| means", round(mean_of(before2) or 0, 1), "->", round(mean_of(after2) or 0, 1), flush=True)
    if after2:
        with open(f"{LAB}/input_after.jpg", "wb") as handle:
            handle.write(after2)
finally:
    if session:
        api("POST", "/api/jobs", {"tool": "autoplay", "input": {"session_id": session, "op": "stop"}})
    restore()
