"""Measure RE4 Switch anchors on a *proven-live* round, restoring the rotation no matter how it exits.

Round 51's lessons, built in:

* the rotation is restored in a `finally`, so a failed walk cannot leave the host unsupervised - and the restore order is
  the document's (`enabled=true` first, then stop the session);
* **the round is proved live before anything is measured**: the clock's corner of the frame must change between two
  samples, which is what "the clock counts" means when you only have pixels;
* a failed boot is retried once rather than wasting the pause.

Measurements, all of which the objectives still need:

1. `clock` - floats that fall while nothing is pressed (a countdown is the easiest thing to isolate);
2. `enemy_stride` - `u16 == 1000` candidates and the stride that repeats between them (the document's "26 objects at
   health 1000", scanned by shape because the address it was seen at is class metadata);
3. `slots` - the two documented pointer slots, for the record.

Usage: `python3 probe_re4_measure.py [--out FILE]`. Restores the rotation on the way out, always.
"""
import argparse
import collections
import json
import os
import statistics
import struct
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GID = "270a15eb98dab4d7"
MODULE = 0x3CA7C04000
BSS = MODULE + 0xB2C738
WINDOW = 7_602_176
SLOTS = {"documented a": 0xB25D78, "documented b": 0xB25D88}
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"},
        "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}}
CLOCK_BOX = (16, 8, 210, 64)          # x0, y0, x1, y1: the Mercenaries timer
sys.path.insert(0, f"{HOME}/gBox/system")
from gbox.mercs.titles import re4_switch as D          # noqa: E402
from gbox.mercs.titles import re4_switch_screens as S  # noqa: E402


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200].decode("utf-8", "replace")
    except Exception as exc:                                   # noqa: BLE001
        return None, str(exc)[:150]


def sessions():
    _, payload = api("GET", "/api/sessions")
    rows = payload if isinstance(payload, list) else (payload.get("sessions") or []) if isinstance(payload, dict) else []
    return rows


def running(game_id=None):
    return [r for r in sessions() if r.get("state") == "running"
            and (game_id is None or r.get("game_id") == game_id)]


def frame(sid):
    try:
        url = f"{BASE}/api/sessions/{sid}/frame.jpg"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
            return response.read()
    except Exception:                                          # noqa: BLE001
        return None


def press(sid, key):
    return api("POST", "/api/jobs", {"tool": "session_op", "require_worker": str(sid).split("-")[0],
                                     "input": {"session_id": sid, "op": "send_input",
                                               "args": {"events": [{"key": key, "down": True},
                                                                   {"key": key, "down": False}]}}})[0]


def read(sid, address, length):
    _, payload = api("GET", f"/api/sessions/{sid}/ram/hex?address={address}&length={length}")
    return bytes.fromhex(payload["hex"]) if isinstance(payload, dict) and payload.get("hex") else b""


def pause_rotation():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for session in running():
        api("POST", "/api/jobs", {"tool": "session_op",
                                  "input": {"session_id": session.get("session_id") or session.get("id"),
                                            "op": "stop_game", "args": {}}})
    for _ in range(20):
        time.sleep(3)
        if not running():
            return True
    return False


def restore_rotation():
    """The document's order: enabled first, then stop the test session."""
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for session in running():
        api("POST", "/api/jobs", {"tool": "session_op",
                                  "input": {"session_id": session.get("session_id") or session.get("id"),
                                            "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


def clock_is_ticking(first, second):
    """Two frames, same scene, and the timer's corner differs: the round is live. No OCR, just change."""
    if not first or not second:
        return False
    try:
        from io import BytesIO

        from PIL import Image
        box = CLOCK_BOX
        a = Image.open(BytesIO(first)).convert("L").crop(box)
        b = Image.open(BytesIO(second)).convert("L").crop(box)
    except Exception:                                          # noqa: BLE001
        return False
    if a.size != b.size:
        return False
    diff = sum(abs(p - q) for p, q in zip(a.getdata(), b.getdata()))
    return diff > 2000                                        # a ticking clock moves a few glyphs, not the whole box


def walk_to_round(sid, reader, tick_limit=40):
    last, seen_stage, reached = 0.0, False, False
    for _ in range(tick_limit):
        time.sleep(6)
        raw = frame(sid)
        if raw is None:
            continue
        screen = reader.read(raw)
        where = screen.get("where")
        seen_stage = seen_stage or where == "select_stage"
        target = D.EXTRAS_ROW if where == "main_menu" else (D.MERCENARIES_ROW if where == "extras_menu" else None)
        key = D.step({**screen, "target": target}) if time.monotonic() - last > 3.5 else None
        if key:
            press(sid, key)
            D.pressed(screen, key)
            last = time.monotonic()
        if where == "unknown" and seen_stage:
            reached = True
            break
    if not reached:
        return False
    for _ in range(3):
        press(sid, "a")
        time.sleep(2)
    time.sleep(10)
    return True


def reach_live_round(attempts=2):
    for attempt in range(1, attempts + 1):
        print(f"MARK launch attempt {attempt}", flush=True)
        api("POST", f"/api/games/{GID}/launch?node=lilspark", {})
        sid = None
        for _ in range(40):
            time.sleep(5)
            for session in running(GID):
                sid = session.get("session_id") or session.get("id")
                break
            if sid:
                break
        if not sid:
            continue
        print("MARK session", sid, flush=True)
        D.begin_run()
        if walk_to_round(sid, S.Reader()):
            first = frame(sid)
            time.sleep(4)
            second = frame(sid)
            if clock_is_ticking(first, second):
                print("MARK round is live (clock ticking)", flush=True)
                return sid
            print("MARK reached a stage but the clock is not ticking", flush=True)
        else:
            print("MARK walk did not reach a stage", flush=True)
        api("POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": sid, "op": "stop_game", "args": {}}})
        time.sleep(5)
    return None


def measure_clock(sid):
    api("DELETE", f"/api/sessions/{sid}/ram/search")
    started = api("POST", f"/api/sessions/{sid}/ram/search", {"type": "f32", "base": BSS, "size": WINDOW})
    if "detail" in started:
        return {"error": started["detail"][:160]}
    ranged = api("POST", f"/api/sessions/{sid}/ram/search/sample", {"op": "range", "lo": 1.0, "hi": 130.0})
    time.sleep(6)
    dropped = api("POST", f"/api/sessions/{sid}/ram/search/sample", {"op": "decreased"})
    listing = api("GET", f"/api/sessions/{sid}/ram/search?limit=40")
    rows = []
    for row in listing.get("candidates_list") or []:
        blob = read(sid, row["address"], 4)
        rows.append({"address": row["address_hex"],
                     "value": round(struct.unpack("<f", blob)[0], 3) if len(blob) == 4 else None})
    return {"in_range": ranged.get("candidates") if "detail" not in ranged else ranged["detail"][:120],
            "decreased": dropped.get("candidates") if "detail" not in dropped else dropped["detail"][:120],
            "rows": sorted(rows, key=lambda r: abs((r["value"] or 0) - 120.0))[:10]}


def measure_enemy_stride(sid):
    api("DELETE", f"/api/sessions/{sid}/ram/search")
    started = api("POST", f"/api/sessions/{sid}/ram/search", {"type": "u16", "base": BSS, "size": WINDOW})
    if "detail" in started:
        return {"error": started["detail"][:160]}
    filtered = api("POST", f"/api/sessions/{sid}/ram/search/sample", {"op": "equals", "value": 1000})
    listing = api("GET", f"/api/sessions/{sid}/ram/search?limit=400")
    addresses = sorted(row["address"] for row in listing.get("candidates_list") or [])
    gaps = collections.Counter(current - previous for previous, current in zip(addresses, addresses[1:])
                               if 0x10 <= current - previous <= 0x4000)
    return {"candidates": filtered.get("candidates") if "detail" not in filtered else filtered["detail"][:120],
            "top_gaps": [(hex(gap), count) for gap, count in gaps.most_common(8)],
            "first": [hex(address) for address in addresses[:12]]}


def measure_slots(sid):
    out = {}
    for label, offset in SLOTS.items():
        blob = read(sid, MODULE + offset, 8)
        out[label] = {"slot": hex(MODULE + offset), "raw": blob.hex(),
                      "value": hex(int.from_bytes(blob, "little")) if len(blob) == 8 else None}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/re4_measure.json")
    args = parser.parse_args()
    report = {"at": time.time()}
    try:
        print("MARK pausing rotation; stopped:", pause_rotation(), flush=True)
        sid = reach_live_round()
        report["session"] = sid
        if not sid:
            report["error"] = "no live round on any attempt"
            print("MARK no live round", flush=True)
            return
        signature = read(sid, MODULE + 0x100000, 32).hex()[:32]
        report["module_signature_ok"] = signature == "fd7b07a9fdc30191355100b0b5c646f9"
        print("MARK signature ok:", report["module_signature_ok"], flush=True)
        report["slots"] = measure_slots(sid)
        report["clock"] = measure_clock(sid)
        report["enemy_stride"] = measure_enemy_stride(sid)
        print("MARK clock:", json.dumps(report["clock"])[:300], flush=True)
        print("MARK stride:", json.dumps(report["enemy_stride"])[:300], flush=True)
    finally:
        if report.get("session"):
            api("DELETE", f"/api/sessions/{report['session']}/ram/search")
        json.dump(report, open(args.out, "w"), indent=1)
        print("MARK written", args.out, flush=True)
        restore_rotation()


if __name__ == "__main__":
    main()
