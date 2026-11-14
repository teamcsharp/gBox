"""Track the live session's campaign progress, and snapshot on every floor change.

The autoplayer will run for hours across rounds; the mandate needs a durable, timestamped record of where the
character has actually been. This samples the session every ten seconds (floor, room, position, HP, status word,
enemy count) into `progress.jsonl`, keeps a `visited.json` map of rooms per floor, and takes an extra
`state_transfer` snapshot whenever the floor changes (a new area is the most expensive progress to lose).

    python pso-progress-tracker.py
    python pso-progress-tracker.py --period 5
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
FLOOR = 0x805D5FC0
PHASE = 0x804FE120
STATUS_OFFSET = 0x254


def call(path, payload=None, method="GET", timeout=90):
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
    with (OUT / "progress.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def live_session():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row for row in rows if row.get("state") in ("running", "starting")), None)


def rpc(session_id, op, **args):
    return call(f"/api/sessions/{session_id}/rpc", {"op": op, "args": args}, "POST", 90)


def read(session_id, address, length):
    raw = rpc(session_id, "read_memory", address=address, length=length)
    return bytes.fromhex(raw) if isinstance(raw, str) else b""


def snapshot(session):
    job = call("/api/jobs", {"tool": "state_transfer", "require_worker": session["session_id"].split("-")[0],
                             "input": {"session_id": session["session_id"], "op": "snapshot", "artifact": "",
                                       "slot": None, "not_before": 0}}, "POST", 60)
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        row = call("/api/jobs/" + job_id) or {}
        if row.get("state") == "succeeded":
            return ((row.get("output") or {}).get("result") or {}).get("artifact")
        if row.get("state") in ("failed", "cancelled"):
            return None
        time.sleep(1.5)
    return None


def sample(session):
    session_id = session["session_id"]
    state = rpc(session_id, "state") or {}
    player = state.get("player") or {}
    if not player.get("ptr"):
        return None
    player_ptr = int(player["ptr"], 16)
    raw_floor = read(session_id, FLOOR, 4)
    floor = int.from_bytes(raw_floor, "big") if len(raw_floor) == 4 else None
    status = read(session_id, player_ptr + STATUS_OFFSET, 4)
    enemies = sum(1 for entity in state.get("entities") or [] if "Ene" in str(entity.get("class")))
    return {"at": time.time(), "session": session_id, "floor": floor,
            "room": player.get("room"), "x": round(float(player.get("x") or 0), 1),
            "z": round(float(player.get("z") or 0), 1), "hp": player.get("hp"),
            "status": status.hex() if len(status) == 4 else None, "enemies": enemies}


def main(argv=None):
    parser = argparse.ArgumentParser(description="campaign progress record and floor-change snapshots")
    parser.add_argument("--period", type=float, default=10.0)
    args = parser.parse_args(argv)
    visited_path = OUT / "visited.json"
    visited = json.loads(visited_path.read_text(encoding="utf-8")) if visited_path.exists() else {}
    last = None
    log({"at": time.time(), "event": "tracker start"})
    while True:
        try:
            session = live_session()
            if session is None:
                time.sleep(args.period)
                continue
            record = sample(session)
            if record is None:
                time.sleep(args.period)
                continue
            floor_key = str(record["floor"])
            rooms = set(visited.get(floor_key) or [])
            changed = last is None or (record["floor"], record["room"]) != (last["floor"], last["room"])
            if changed:
                rooms.add(record["room"])
                visited[floor_key] = sorted(int(room) for room in rooms if isinstance(room, int))
                visited_path.write_text(json.dumps(visited, indent=1), encoding="utf-8")
                log({**record, "event": "room", "previous_floor": (last or {}).get("floor"),
                     "previous_room": (last or {}).get("room")})
                if last is not None and record["floor"] != last["floor"]:
                    artifact = snapshot(session)
                    log({"at": time.time(), "event": "floor-change-snapshot", "floor": record["floor"],
                         "artifact": artifact})
                last = record
            elif int(record["at"]) % 60 < args.period:
                log({**record, "event": "tick"})
                last = record
        except Exception as error:                               # noqa: BLE001
            log({"at": time.time(), "event": "error", "error": f"{type(error).__name__}: {error}"})
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())
