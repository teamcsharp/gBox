"""Test the document's two player-pointer leads on a live RE4 Switch round.

`docs/mercmode-adding-titles.md` says: "The pointer leads disagree between notes (`module+0xb25d78`, `module+0xb25d88`).
Test both." It also says not to assume full health is 100 (an earlier pass measured 1336 -> 1054), and to prove the round
is live first - so this reads both slots, dereferences them, and looks for a unit-shaped object rather than hunting a
value.

Order follows the same document: pause the rotation, launch directly, then restore with `enabled=true` FIRST.
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
OUT = "/tmp/re4_leads.json"
LAB = HOME / "gBox_alt/re4-lab"
sys.path.insert(0, str(HOME / "gBox" / "system"))
from gbox.mercs.titles import re4_switch as D          # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S  # noqa: E402

MODULE = 0x3CA7C04000
LEADS = {"documented a": 0xB25D78, "documented b": 0xB25D88}


def api(method, path, body=None, timeout=400):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:250].decode("utf-8", "replace")
    except Exception as exc:
        return None, str(exc)[:150]


def rows_of(payload):
    if isinstance(payload, list):
        return payload
    return (payload.get("sessions") or []) if isinstance(payload, dict) else []


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
                                                                   {**{"key": key}, "down": False}]}}})[0]


def read(sid, address, length):
    code, payload = api("GET", f"/api/sessions/{sid}/ram/hex?address={address}&length={length}")
    if isinstance(payload, dict) and payload.get("hex"):
        return bytes.fromhex(payload["hex"])
    return b""


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
code, body = api("POST", f"/api/games/{GID}/launch?node=lilspark", {})
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
    time.sleep(8)

# module base: the measured signature
sig = read(sid, MODULE + 0x100000, 32)
print("MARK signature ok:", sig.hex()[:32] == "fd7b07a9fdc30191355100b0b5c646f9", flush=True)

results = {}
for label, offset in LEADS.items():
    slot = MODULE + offset
    raw = read(sid, slot, 8)
    value = int.from_bytes(raw, "little") if len(raw) >= 8 else None
    row = {"slot": hex(slot), "raw": raw.hex(), "value": hex(value) if value else None}
    if value and 0x3C00000000 <= value < 0x3D00000000:
        # a pointer into the guest heap: does the object look like a unit?
        head = read(sid, value, 0x40)
        health_word = read(sid, value + 0x3C2, 2)
        row["head"] = head.hex()
        row["h_3c2"] = int.from_bytes(health_word, "little") if len(health_word) == 2 else None
        row["first_pointer"] = hex(int.from_bytes(head[:8], "little")) if len(head) >= 8 else None
    results[label] = row
    print("MARK", label, json.dumps(row)[:260], flush=True)
json.dump(results, open(OUT, "w"), indent=1)
print("MARK written", OUT, flush=True)
