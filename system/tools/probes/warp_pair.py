"""Warp into the village twice: once from the disc with a destroyed room archive, once from the stock disc.

The room loader is the game's own (`re_mods op=warp`), so the menus never matter. The broken build must fail to produce a
village; the stock build must produce one. The difference between the two runs is the answer to "does the game read the file
at the FST offset", and nothing else in this session depends on that question being open.

`re_mods` needs `session_id` in the input - the first attempt omitted it and the tool refused with a validation error.

Restores the rotation in `finally`, in the documented order.
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
ROOM = "r100"
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
        return exc.code, {"detail": exc.read()[:400].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:200]}


def rows(body, key):
    return body if isinstance(body, list) else (body.get(key) or []) if isinstance(body, dict) else []


def running():
    return [r for r in rows(api("GET", "/api/sessions")[1], "sessions") if r.get("state") == "running"]


def jobs_running():
    return [r for r in rows(api("GET", "/api/jobs?limit=8")[1], "jobs") if r.get("state") == "running"]


def idle():
    for _ in range(30):
        if not running() and not jobs_running():
            return True
        time.sleep(4)
    return False


def stop_all():
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    return idle()


def frame(session):
    try:
        url = f"{BASE}/api/sessions/{session}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                            # noqa: BLE001
        return None


def one_run(build, tag):
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={build}", {}) if build else \
        api("POST", f"/api/games/{GC}/launch?node=lilspark", {})
    print(f"MARK {tag} launch", status, (body.get("id") if isinstance(body, dict) else ""), flush=True)
    session = None
    for _ in range(36):
        time.sleep(5)
        for row in running():
            if row.get("game_id") == GC:
                session = row.get("session_id") or row.get("id")
        if session:
            break
    print(f"MARK {tag} session", session, flush=True)
    if not session:
        return {"build": build, "error": "no session"}
    time.sleep(40)
    before = frame(session)
    status, warp = api("POST", "/api/jobs", {"tool": "re_mods", "require_worker": session.split("-")[0],
                                             "input": {"session_id": session, "op": "warp", "target": ROOM}})
    print(f"MARK {tag} warp", status, json.dumps(warp)[:200], flush=True)
    means = []
    from io import BytesIO

    from PIL import Image
    for step in range(8):
        time.sleep(12)
        raw = frame(session)
        if raw is None:
            means.append(None)
            continue
        path = f"{LAB}/{tag}_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        means.append(round(statistics.fmean(list(Image.open(BytesIO(raw)).convert("L").getdata())), 1))
        print(f"MARK {tag} frame {step} {means[-1]}", flush=True)
    alive = any((r.get("session_id") or r.get("id")) == session for r in running())
    print(f"MARK {tag} alive at end:", alive, "| means", means, flush=True)
    stop_all()
    return {"build": build, "session": session, "warp": warp if isinstance(warp, dict) else str(warp)[:200],
            "means": means, "alive": alive}


results = []
try:
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    print("MARK idle:", stop_all(), flush=True)
    results.append(one_run("re4gc-stagebreak", "warpbreak"))
    results.append(one_run(None, "warpstock"))
finally:
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    stop_all()
    print("MARK rotation restored", flush=True)
json.dump(results, open("/tmp/warp_pair.json", "w"), indent=1)
print("MARK written /tmp/warp_pair.json", flush=True)
