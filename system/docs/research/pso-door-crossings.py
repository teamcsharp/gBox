"""Record every room crossing in the live session with where it happened, to learn the floor's door graph.

The bot walks through doorways and the room value changes; that observation (floor, from-room, to-room, the player
position at the crossing, the collision digest of the floor it happened on) is the only honest source of "which door
leads where" - no object exposes a destination. `pso-frontier.py` reads this log to pick the nearest doorway that has
never been crossed and walk through it, which turns wandering into deliberate floor coverage.

    python pso-door-crossings.py
    python pso-door-crossings.py --period 0.8
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
ROUTES = pathlib.Path(r"D:\gBox\pso-ds\routes")
FLOOR = 0x805D5FC0


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(record):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "door-crossings.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def layout_key(floor):
    """Name of the newest live-map dump for this floor (its digest identifies the randomized layout)."""
    candidates = sorted(ROUTES.glob(f"live-map-floor{floor}-*.json"), key=lambda path: path.stat().st_mtime)
    return candidates[-1].stem if candidates else f"floor{floor}"


def live_session():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row for row in rows if row.get("state") in ("running", "starting")), None)


def main(argv=None):
    parser = argparse.ArgumentParser(description="learn door destinations from live room crossings")
    parser.add_argument("--period", type=float, default=0.9)
    args = parser.parse_args(argv)
    last = None
    log({"at": time.time(), "event": "crossing tracker start"})
    while True:
        try:
            session = live_session()
            if session is None:
                time.sleep(args.period)
                continue
            session_id = session["session_id"]
            state = call(f"/api/sessions/{session_id}/rpc", {"op": "state", "args": {}}, "POST", 60) or {}
            player = state.get("player") or {}
            if not player.get("ptr"):
                time.sleep(args.period)
                continue
            raw_floor = call(f"/api/sessions/{session_id}/rpc",
                             {"op": "read_memory", "args": {"address": FLOOR, "length": 4}}, "POST", 60)
            floor = int(raw_floor, 16) if isinstance(raw_floor, str) else None
            current = {"session": session_id, "floor": floor, "room": player.get("room"),
                       "x": round(float(player.get("x") or 0), 1), "z": round(float(player.get("z") or 0), 1)}
            if last is not None and current["room"] != last["room"] and current["floor"] == last["floor"]:
                # settle one sample: a room value flickers at boundaries, so confirm on the next read
                time.sleep(0.35)
                confirm = call(f"/api/sessions/{session_id}/rpc", {"op": "state", "args": {}}, "POST", 60) or {}
                room2 = (confirm.get("player") or {}).get("room")
                if room2 == current["room"]:
                    log({"at": time.time(), "event": "crossing", **current, "from_room": last["room"],
                         "to_room": current["room"], "layout": layout_key(floor)})
            if current["room"] != (last or {}).get("room") or current["floor"] != (last or {}).get("floor"):
                last = current
        except Exception as error:                               # noqa: BLE001
            log({"at": time.time(), "event": "error", "error": f"{type(error).__name__}: {error}"})
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())
