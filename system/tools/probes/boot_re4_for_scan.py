"""Boot RE4 (Switch) into a Mercenaries round and leave it there, so a RAM scan can run against a live session.

MercMode's rotation refuses this edition (no snapshot yet), so the game is launched directly and walked with the proven
frame reader - the same harness rounds 16-21 used. Prints the session id for the scan to use.
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home()
TOKEN = (HOME / "gBox/system/gbox-data/api_token").read_text().strip()
B = "http://127.0.0.1:8765"
H = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GID = "270a15eb98dab4d7"
OUT = "/tmp/re4_session.json"
sys.path.insert(0, str(HOME / "gBox" / "system"))
from gbox.mercs.titles import re4_switch as D          # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S  # noqa: E402


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200].decode("utf-8", "replace")
    except Exception as exc:
        return None, str(exc)[:150]


def running(game_id=None):
    code, payload = api("GET", "/api/sessions")
    rows = payload if isinstance(payload, list) else (payload.get("sessions") or []) if isinstance(payload, dict) else []
    return [s for s in rows if s.get("state") == "running" and (game_id is None or s.get("game_id") == game_id)]


def grab(sid):
    try:
        with urllib.request.urlopen(urllib.request.Request(B + f"/api/sessions/{sid}/frame.jpg", headers=H),
                                    timeout=120) as r:
            return r.read()
    except Exception:
        return None


def press(sid, key):
    return api("POST", "/api/jobs", {"tool": "session_op", "require_worker": str(sid).split("-")[0],
                                     "input": {"session_id": sid, "op": "send_input",
                                               "args": {"events": [{"key": key, "down": True},
                                                                   {"key": key, "down": False}]}}})[0]


api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
for s in running():
    api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": s.get("session_id") or s.get("id"),
                                                              "op": "stop_game", "args": {}}})
for _ in range(20):
    time.sleep(3)
    if not running():
        break

code, body = api("POST", f"/api/games/{GID}/launch?node=lilspark", {})
sid = None
for _ in range(40):
    time.sleep(5)
    for s in running(GID):
        sid = s.get("session_id") or s.get("id")
        break
    if sid:
        break
print("MARK launch", code, "session", sid, flush=True)
if not sid:
    raise SystemExit("no session")

D.begin_run()
reader = S.Reader()
last, seen_stage, reached = 0.0, False, False
for tick in range(40):
    time.sleep(6)
    raw = grab(sid)
    if raw is None:
        continue
    scr = reader.read(raw)
    where = scr.get("where")
    seen_stage = seen_stage or where == "select_stage"
    target = D.EXTRAS_ROW if where == "main_menu" else (D.MERCENARIES_ROW if where == "extras_menu" else None)
    key = D.step({**scr, "target": target}) if time.monotonic() - last > 3.5 else None
    if key:
        press(sid, key)
        D.pressed(scr, key)
        last = time.monotonic()
    if where == "unknown" and seen_stage:
        reached = True
        break
# into the stage: three A presses, as the driver's own note says
if reached:
    for _ in range(3):
        press(sid, "a")
        time.sleep(2)
    time.sleep(25)
json.dump({"session": sid, "reached_stage": reached, "game_id": GID}, open(OUT, "w"))
print("MARK reached_stage", reached, "-> written", OUT, flush=True)
