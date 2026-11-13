"""record - watch the operator play, and turn the demonstration into machine-readable data.

The operator's instruction: *"I can walk you where you got to go but you have to be scanning the game and reading what
I am doing."* So this tool does exactly that: it polls the live state several times a second while the operator drives,
records every sample, and writes the whole demonstration as

* `demo-<stamp>.jsonl` - one line per sample: time, position, room, heading, hp, entity count;
* `demo-<stamp>.json`  - a compact route: the path simplified to ~4-unit spacing, plus the rooms crossed, the
  start/end and the wall-clock duration.

The route it writes is directly replayable by `pso-bounded.py walk --route-file`, which means a route the operator
walked becomes a route the controller can follow without a decoded map being right about anything.

    python pso-record.py --seconds 120
    python pso-record.py --seconds 60 --hz 12      # denser samples

Nothing here sends input. It is a passive observer, so the operator keeps the pad.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import time
import urllib.request

# The app the worker actually registered with. Two app instances can run (the config default 8765 and a
# hand-started 18765); talking to the wrong one returns 504 for every session RPC while the other answers
# normally - measured. GBOX_API overrides it.
BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\bounded")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=20):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                      # noqa: BLE001
        return {"err": type(exc).__name__}


def live_session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    return live[0]["session_id"] if live else ""


def simplify(points: list, spacing: float = 4.0) -> list:
    kept = []
    for x, z in points:
        if not kept or math.dist(kept[-1], (x, z)) >= spacing:
            kept.append((round(x, 1), round(z, 1)))
    if points and (not kept or kept[-1] != (round(points[-1][0], 1), round(points[-1][1], 1))):
        kept.append((round(points[-1][0], 1), round(points[-1][1], 1)))
    return kept


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="record an operator demonstration")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--hz", type=float, default=8.0)
    parser.add_argument("--spacing", type=float, default=4.0)
    args = parser.parse_args(argv)

    sid = live_session()
    if not sid:
        log("no live session to record")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trace_path = OUT / f"demo-{stamp}.jsonl"
    route_path = OUT / f"demo-{stamp}.json"

    started = time.monotonic()
    interval = 1.0 / max(args.hz, 1.0)
    samples, path, rooms = [], [], []
    last_report = 0.0
    moved_total = 0.0
    log(f"recording session {sid} for {args.seconds:.0f}s - walk wherever you want the bot to go")
    with trace_path.open("w", encoding="utf-8") as trace:
        while time.monotonic() - started < args.seconds:
            t0 = time.monotonic()
            state = call(f"/api/sessions/{sid}/rpc", {"op": "state", "args": {}}, "POST")
            player = (state or {}).get("player") or {}
            if player.get("x") is None:
                time.sleep(max(0.0, interval - (time.monotonic() - t0)))
                continue
            x, z = float(player["x"]), float(player["z"])
            row = {"t": round(time.monotonic() - started, 3), "x": round(x, 2), "z": round(z, 2),
                   "room": player.get("room"), "heading": player.get("heading_deg"),
                   "hp": player.get("hp"), "entities": len((state or {}).get("entities") or [])}
            samples.append(row)
            trace.write(json.dumps(row) + "\n")
            if not path or math.dist(path[-1], (x, z)) >= 1.0:
                if path:
                    moved_total += math.dist(path[-1], (x, z))
                path.append((x, z))
            if player.get("room") not in rooms:
                rooms.append(player.get("room"))
                log(f"  room {player.get('room')} at ({x:.0f},{z:.0f})")
            now = time.monotonic()
            if now - last_report >= 1.0:
                last_report = now
                log(f"  t+{now - started:5.1f}s at ({x:6.0f},{z:6.0f}) room {player.get('room')} "
                    f"path {moved_total:6.0f} units, {len(samples)} samples")
            time.sleep(max(0.0, interval - (time.monotonic() - t0)))
        trace.flush()

    route = {"stamp": stamp, "session": sid, "seconds": round(time.monotonic() - started, 1),
             "spacing": args.spacing, "rooms": rooms, "path_length": round(moved_total, 1),
             "samples": len(samples), "waypoints": simplify(path, args.spacing),
             "start": samples[0] if samples else None, "end": samples[-1] if samples else None}
    route_path.write_text(json.dumps(route, indent=1), encoding="utf-8")
    log(f"recorded {len(samples)} samples, path {moved_total:.0f} units, rooms {rooms}")
    log(f"route with {len(route['waypoints'])} waypoints -> {route_path}")
    log(f"trace -> {trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
