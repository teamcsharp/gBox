"""Print the emulator's COMPLETE argument list for a mod launch.

With every font's glyphs filled and the title text untouched, the game is not reading patched files - but Dolphin does appear
to receive the patched ISO. Both can be true at once if the argument list carries the library `.gcz` as well, with the ISO
somewhere else in it. So this prints every token, not a substring match.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
BUILD = "re4gc-fontall"
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


def pull(path):
    _, body = api("GET", path)
    return body


def rows(body, key):
    return body if isinstance(body, list) else (body.get(key) or []) if isinstance(body, dict) else []


def running():
    return [r for r in rows(pull("/api/sessions"), "sessions") if r.get("state") == "running"]


def jobs_running():
    return [r for r in rows(pull("/api/jobs?limit=8"), "jobs") if r.get("state") == "running"]


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


def dolphin_lines():
    out = subprocess.run(["bash", "-lc", "ps -eo args | grep -E 'dolphin-emu|dolphin-emu-wrapper' | grep -v grep"],
                         capture_output=True, text=True, timeout=30).stdout
    return [line for line in out.splitlines() if line.strip()]


try:
    print("MARK host idle:", pause_and_wait(), flush=True)
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={BUILD}", {})
    print("MARK launch", status, (body.get("id") if isinstance(body, dict) else ""), flush=True)
    printed = 0
    for _ in range(20):
        time.sleep(5)
        for line in dolphin_lines():
            if "dolphin-emu -b" in line or line.startswith("dolphin-emu "):
                print("MARK full argv:", line, flush=True)
                discs = [token for token in line.split() if token.lower().endswith((".iso", ".gcz", ".rvz", ".wbfs"))]
                print("MARK disc tokens:", discs, flush=True)
                printed += 1
        if printed >= 2:
            break
    if not printed:
        print("MARK no dolphin process seen", flush=True)
finally:
    restore()
