"""Put the title's save back to a menu: answer "Cancel loading?" with Yes, wait for the title screen, stop there.

Round 98 measured that a session stopped from a menu writes a menu-state save, and the next boot comes up clean; a session stopped
mid-load writes the prompt back. The bash version of this kept failing on quoting, so it is Python.
"""
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from io import BytesIO

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
SWITCH = "270a15eb98dab4d7"


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read()[:200].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:160]}


def rows(body, key):
    return body if isinstance(body, list) else (body.get(key) or []) if isinstance(body, dict) else []


def running():
    return [r for r in rows(api("GET", "/api/sessions")[1], "sessions") if r.get("state") == "running"]


def frame(session):
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/sessions/{session}/frame.jpg",
                                                           headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def mean_of(raw):
    from PIL import Image
    return statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())) if raw else 0.0


def press(session, key):
    return api("POST", "/api/jobs", {"tool": "session_op", "require_worker": session.split("-")[0],
                                     "input": {"session_id": session, "op": "send_input",
                                               "args": {"events": [{"key": key, "down": True},
                                                                   {"key": key, "down": False}]}}})[0]


def main() -> int:
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    sessions = running()
    if not sessions:
        api("POST", f"/api/games/{SWITCH}/launch?node=lilspark", {})
        for _ in range(40):
            time.sleep(5)
            sessions = [r for r in running() if r.get("game_id") == SWITCH]
            if sessions:
                break
    if not sessions:
        print("no session could be started")
        return 1
    session = sessions[0].get("session_id") or sessions[0].get("id")
    print("session", session)
    answered = 0
    for step in range(14):
        time.sleep(9)
        raw = frame(session)
        mean = mean_of(raw)
        print(f"  {step:02d} mean {mean:.1f}")
        if 12 <= mean <= 24 and answered < 3:
            # the prompt wants input at a moment it does not announce, so a single press can miss it; retry up to three times and
            # only count it answered once the picture has actually moved on
            press(session, "up")
            time.sleep(0.8)
            press(session, "a")
            answered += 1
            print(f"  answered Yes (cancel the load), attempt {answered}")
            continue
        if answered and mean > 40:
            break
    api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": session, "op": "stop_game", "args": {}}})
    time.sleep(8)
    print("stopped from the menu" if answered else "stopped (the prompt never appeared)")
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0,
                                  "preferred_editions": {"re4": {"platform": "switch", "mode": "mercenaries",
                                                                 "title_id": "010099A00BC1E000"},
                                                         "re5": {"platform": "switch", "mode": "no_mercy",
                                                                 "title_id": "010018100CD46000"}}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
