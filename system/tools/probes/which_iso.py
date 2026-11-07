"""Which file does Dolphin open for a GameCube mod build?

Two builds were verified byte-for-byte different from the disc and neither was drawn, so the question is no longer the
model: it is whether the patched ISO is the file the emulator was given. This launches with a mod, reads the emulator's own
command line within seconds, and stops it again - no round, no walk.

Restores the rotation in `finally` in the documented order.
"""
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
BUILD = "re4gsonic_enemies"
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"},
        "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}}


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read()[:400].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:200]}


def sessions():
    _, body = api("GET", "/api/sessions")
    return body if isinstance(body, list) else (body.get("sessions") or []) if isinstance(body, dict) else []


def running(game_id=None):
    return [row for row in sessions() if row.get("state") == "running"
            and (game_id is None or row.get("game_id") == game_id)]


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


def emulator_argv():
    """Every process whose command line mentions a disc image, plus the plain `dolphin` processes."""
    out = subprocess.run(["bash", "-lc", "ps -eo pid,etimes,args | grep -i -E 'dolphin|gcz|re4-d1' | grep -v grep"],
                         capture_output=True, text=True, timeout=30).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


session = None
try:
    print("MARK paused:", pause(), flush=True)
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={BUILD}", {})
    print("MARK launch", status, (body.get("id") if isinstance(body, dict) else ""), flush=True)
    seen = []
    for attempt in range(12):
        time.sleep(5)
        lines = emulator_argv()
        for line in lines:
            if line not in seen:
                seen.append(line)
                print("MARK proc:", line[:300], flush=True)
                if "dolphin-emu -b" in line or "dolphin-emu -e" in line:
                    tail = line.split("-C ")[-1]
                    print("MARK argv tail:", tail[:400], flush=True)
                    for token in line.split():
                        if token.endswith((".iso", ".gcz", ".rvz", ".wbfs")):
                            print("MARK game file:", token, flush=True)
        for row in running(GC):
            session = row.get("session_id") or row.get("id")
        if session and attempt >= 2:
            break
    print("MARK session", session, flush=True)
    print("MARK opened:", "the patched ISO" if any("re4-d1.iso" in line for line in seen)
          else ("the library file" if any(re.search(r"\.gcz", line) for line in seen) else "not visible in ps"),
          flush=True)
finally:
    if session:
        api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": session, "op": "stop_game", "args": {}}})
    restore()
