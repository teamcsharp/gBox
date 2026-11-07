"""Find the enemy array by its shape: the value 1000 repeated at a constant stride, about 26 times.

The document's lead was "class 0xaed3b0, 26 objects at health 1000". Read as a module offset that slot holds
`0xa7c0f2b0, 0x3c, 0xa7dadfd0` - class metadata, not a pointer that survives a boot. What does survive is the shape: a
closed set of equal-sized objects carrying the same health. This searches the mapped `.bss` window for `u16 == 1000` and
looks for the stride that repeats most often, instead of guessing another address.
"""
import collections
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
B = "http://127.0.0.1:8765"
H = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GID = "270a15eb98dab4d7"
MODULE = 0x3CA7C04000
BSS = MODULE + 0xB2C738
WINDOW = 7_602_176
OUT = "/tmp/re4_enemy_stride.json"
sys.path.insert(0, f"{HOME}/gBox/system")
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


def rows_of(payload):
    return payload if isinstance(payload, list) else (payload.get("sessions") or []) if isinstance(payload, dict) else []


def running(game_id=None):
    code, payload = api("GET", "/api/sessions")
    return [s for s in rows_of(payload) if s.get("state") == "running"
            and (game_id is None or s.get("game_id") == game_id)]


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


def stop_all():
    for s in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": s.get("session_id") or s.get("id"),
                                                                  "op": "stop_game", "args": {}}})
    for _ in range(20):
        time.sleep(3)
        if not running():
            return True
    return False


api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
print("rotation paused; stopped:", stop_all(), flush=True)
api("POST", f"/api/games/{GID}/launch?node=lilspark", {})
sid = None
for _ in range(40):
    time.sleep(5)
    for s in running(GID):
        sid = s.get("session_id") or s.get("id")
        break
    if sid:
        break
print("MARK session", sid, flush=True)
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
print("MARK reached", reached, flush=True)
if not reached:
    raise SystemExit("no round")
for _ in range(3):
    press(sid, "a")
    time.sleep(2)
time.sleep(12)                       # let the Ganados spawn and walk in

api("DELETE", f"/api/sessions/{sid}/ram/search")
started = api("POST", f"/api/sessions/{sid}/ram/search", {"type": "u16", "base": BSS, "size": WINDOW, "tolerance": 0})
if "detail" in started:
    raise SystemExit(f"search refused: {started['detail'][:200]}")
filtered = api("POST", f"/api/sessions/{sid}/ram/search/sample", {"op": "equals", "value": 1000})
print("MARK 1000 candidates:", filtered.get("candidates") if "detail" not in filtered else filtered["detail"][:160],
      flush=True)
listing = api("GET", f"/api/sessions/{sid}/ram/search?limit=400")
addresses = sorted(row["address"] for row in listing.get("candidates_list") or [])
print("MARK fetched", len(addresses), flush=True)

gaps = collections.Counter()
for previous, current in zip(addresses, addresses[1:]):
    gap = current - previous
    if 0x10 <= gap <= 0x4000:
        gaps[gap] += 1
report = {"candidates": len(addresses), "top_gaps": [(hex(g), n) for g, n in gaps.most_common(8)],
          "first": [hex(a) for a in addresses[:12]]}
print("MARK top gaps:", report["top_gaps"], flush=True)
print("MARK first:", report["first"], flush=True)
json.dump(report, open(OUT, "w"), indent=1)
print("MARK written", OUT, flush=True)

api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                              "rounds_per_title": 1, "keep_warm": 0,
                              "preferred_editions": {"re4": {"platform": "switch", "mode": "mercenaries",
                                                             "title_id": "010099A00BC1E000"},
                                                     "re5": {"platform": "switch", "mode": "no_mercy",
                                                             "title_id": "010018100CD46000"}}})
api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": sid, "op": "stop_game", "args": {}}})
print("MARK restored", flush=True)
