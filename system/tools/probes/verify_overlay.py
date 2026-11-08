"""Is the launched build actually active while the game runs?

Three checks, taken from the running host rather than inferred afterwards:

1. the emulator's `[DisabledAddOns]` entry for the RE4 title, as the emulator sees it during the session;
2. the `load/<title>/<build>` entry - a link or a staged copy - and the md5 of the `pl00.udas` the emulator will read, against
   the md5 of the build's own file;
3. a frame, so the same run can be read.

The previous round measured a config in which the launched build was itself disabled, which would explain every "nothing
changed" result without any need for the pack to be wrong.
"""
import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
SWITCH = "270a15eb98dab4d7"
TITLE = "010099A00BC1E000"
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-shrinkall2"
CITRON = f"{HOME}/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/data/citron"
CONFIG = f"{HOME}/gBox/system/gbox-data/runtime-linux-aarch64/citron-linux/config/citron/qt-config.ini"
CACHE = f"{HOME}/gBox_alt/gbox-cache/mods/{SWITCH}/{BUILD}"
LAB = f"{HOME}/gBox_alt/re4-lab"
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": TITLE},
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


def disabled_for_re4():
    text = open(CONFIG, encoding="utf-8", errors="replace").read()
    i = text.find("[DisabledAddOns]")
    block = text[i:text.find("\n[", i + 5)]
    return re.findall(r"5\\\\disabled\\\\\d+\\\\d=(.+)", block)


def overlay_md5():
    """The pl00.udas the emulator will read, through the load entry, and the build's own copy."""
    entry = os.path.join(CITRON, "load", TITLE, BUILD)
    read_path = os.path.join(entry, "romfs", "bio4", "em", "pl00.udas")
    build_path = os.path.join(CACHE, "romfs", "bio4", "em", "pl00.udas")
    def md5(p):
        try:
            with open(p, "rb") as handle:
                return hashlib.md5(handle.read()).hexdigest()
        except OSError as exc:
            return f"missing ({exc.errno})"
    return {"entry_is_link": os.path.islink(entry), "entry_target": os.path.realpath(entry) if os.path.exists(entry) else None,
            "emulator_reads": md5(read_path), "build_copy": md5(build_path),
            "same": md5(read_path) == md5(build_path)}


session = None
try:
    print("MARK host idle:", pause_and_wait(), flush=True)
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
    time.sleep(45)
    disabled = disabled_for_re4()
    print("MARK disabled count:", len(disabled), "| build disabled:", BUILD in disabled, flush=True)
    print("MARK other enabled:", [n for n in disabled if n.startswith("re4sw") or n.startswith("re4-")][:6], flush=True)
    print("MARK overlay:", json.dumps(overlay_md5())[:300], flush=True)
    from io import BytesIO

    from PIL import Image
    for step in range(8):
        time.sleep(15)
        try:
            url = f"{BASE}/api/sessions/{session}/frame.jpg"
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
                raw = response.read()
        except Exception:                                        # noqa: BLE001
            continue
        path = f"{LAB}/verify_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        print("MARK verify_%02d mean %.1f" % (step,
              statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata()))), flush=True)
finally:
    restore()
