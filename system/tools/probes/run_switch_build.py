"""Launch RE4 Switch with the clothesless build and photograph the player.

The playbook walks the menus and enters a round (that is what `re4switch_bot` is for), then the frames are captured. A change
to the player's model is the thing being looked for: material 1 of `pl00` was 564 vertices and 430 triangles, so if it is
drawn at all it is drawn as a point.
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
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-clothesless"
TAG = sys.argv[2] if len(sys.argv) > 2 else "clothesless"
FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 12
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


def stray_emulators():
    """Emulator processes still alive: a launch that inherits one inherits its screen too, menu and all."""
    out = subprocess.run(["bash", "-lc", "pgrep -af 'citron|eden' | grep -v grep | grep -v gbox.service"],
                         capture_output=True, text=True, timeout=30).stdout
    return [line for line in out.splitlines() if line.strip()]


def pause_and_wait():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(30):
        time.sleep(4)
        if not running() and not jobs_running():
            break
    # a session that ended is not the same as an emulator that exited: the last run left one on a menu, and the next
    # launch attached to it, so the "new" session started on somebody else's screen
    for _ in range(3):
        leftovers = stray_emulators()
        if not leftovers:
            return True
        subprocess.run(["bash", "-lc", "pkill -f 'citron-linux' ; pkill -f 'eden-linux'"], timeout=30)
        time.sleep(5)
    print("MARK emulator still alive:", stray_emulators()[:2], flush=True)
    return not stray_emulators()


def restore():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


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
    # wait for a real picture, not a fixed delay: a modified pack can make the first boot slower (shader cache), and
    # starting the bot on a black frame is indistinguishable from a crash in the captures
    from io import BytesIO as _BytesIO

    from PIL import Image as _Image
    # "up" means alive, not merely bright: two samples that differ, so a frozen leftover screen cannot pass for a boot
    deadline = time.time() + 240
    mean, previous = None, None
    alive = 0
    while time.time() < deadline:
        raw = frame(session)
        if raw:
            mean = statistics.fmean(list(_Image.open(_BytesIO(raw)).convert("L").getdata()))
            if mean > 15.0 and previous is not None and raw != previous:
                alive += 1
                if alive >= 2:
                    print(f"MARK picture up and alive: mean {mean:.1f}", flush=True)
                    break
            previous = raw
        time.sleep(8)
    else:
        print(f"MARK picture never came up (last mean {mean})", flush=True)
    status, started = api("POST", "/api/jobs", {"tool": "autoplay", "require_worker": session.split("-")[0],
                                                "input": {"session_id": session, "op": "start", "mode": "playbook"}})
    print("MARK autoplay", status, json.dumps(started)[:160], flush=True)
    from io import BytesIO

    from PIL import Image
    for step in range(FRAMES):
        time.sleep(12)
        raw = frame(session)
        if not raw:
            print(f"MARK {TAG}_{step:02d} no frame", flush=True)
            continue
        path = f"{LAB}/{TAG}_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        print("MARK %s_%02d mean %.1f -> %s" % (TAG, step,
              statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())), path), flush=True)
finally:
    if session:
        api("POST", "/api/jobs", {"tool": "autoplay", "input": {"session_id": session, "op": "stop"}})
    restore()
