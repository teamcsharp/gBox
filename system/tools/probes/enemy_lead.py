"""Test the document's enemy lead: class `0xaed3b0`, 26 objects at health 1000.

The lead is the one concrete thing pointing at enemies ("0xae7050 is spawn markers, not enemies"). If `0xaed3b0` is a
module offset, then `module + 0xaed3b0` is a static slot holding a table or a manager; if it is a heap address seen in a
scan, the slot itself will not be a pointer. This reads it both ways, follows whatever pointers it finds, and counts the
objects that carry 1000 in the first 2 KB.

Restore follows docs/mercmode-adding-titles.md: `enabled=true` FIRST, then stop the test session.
"""
import json
import os
import struct
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
LEAD = 0xAED3B0
OUT = "/tmp/re4_enemy_lead.json"
sys.path.insert(0, f"{HOME}/gBox/system")
from gbox.mercs.titles import re4_switch as D          # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S  # noqa: E402


def api(method, path, body=None, timeout=400):
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


def read(sid, address, length):
    code, payload = api("GET", f"/api/sessions/{sid}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(payload["hex"]) if isinstance(payload, dict) and payload.get("hex") else b""


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
code, _ = api("POST", f"/api/games/{GID}/launch?node=lilspark", {})
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
if reached:
    for _ in range(3):
        press(sid, "a")
        time.sleep(2)
    time.sleep(10)

sig = read(sid, MODULE + 0x100000, 32)
print("MARK signature ok:", sig.hex()[:32] == "fd7b07a9fdc30191355100b0b5c646f9", flush=True)

report = {}
slot = MODULE + LEAD
raw = read(sid, slot, 16)
values = [int.from_bytes(raw[i:i + 4], "little") for i in range(0, 12, 4)] if len(raw) >= 12 else []
report["slot"] = hex(slot)
report["raw"] = raw.hex()
report["u32s"] = [hex(v) for v in values]
print("MARK slot", hex(slot), "u32s", report["u32s"], flush=True)

counted = []
for value in values:
    if not (0x3C00000000 <= value < 0x3D00000000):
        continue
    blob = read(sid, value, 0x800)
    if len(blob) < 0x100:
        continue
    thousand = [hex(off) for off in range(0, len(blob) - 2, 2) if struct.unpack_from("<H", blob, off)[0] == 1000]
    hundred = [hex(off) for off in range(0, len(blob) - 2, 2) if struct.unpack_from("<H", blob, off)[0] == 100]
    header = int.from_bytes(blob[:8], "little")
    counted.append({"pointer": hex(value), "health_1000_at": thousand[:8], "health_100_at": hundred[:8],
                    "n_1000": len(thousand), "n_100": len(hundred), "first_word": hex(header)})
    print("MARK", hex(value), "1000:", thousand[:4], "100:", hundred[:4], flush=True)
report["objects"] = counted
json.dump(report, open(OUT, "w"), indent=1)
print("MARK written", OUT, flush=True)

# restore in the documented order
api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                              "rounds_per_title": 1, "keep_warm": 0,
                              "preferred_editions": {"re4": {"platform": "switch", "mode": "mercenaries",
                                                             "title_id": "010099A00BC1E000"},
                                                     "re5": {"platform": "switch", "mode": "no_mercy",
                                                             "title_id": "010018100CD46000"}}})
api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": sid, "op": "stop_game", "args": {}}})
print("MARK restored", flush=True)
