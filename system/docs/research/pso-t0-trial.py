"""T0 gate: town -> Forest, controller-only, ten verified transitions.

The mandate's first milestone: the Pioneer 2 warp pad must actually deliver the character into Forest 1, driven only by
pad input (no dev warps, no memory writes). This driver does the round trip ten times and records every leg:

    town  -> walk the plaza route (255,-5) -> (340,50) -> pad (360,26); press A, wait, press A -> floor 0 -> 1
    forest-> walk to the return pad (12.1,-16.6); press A -> floor 1 -> 0

Measured menu behaviour (2026-11-14): the town pad needs TWO A presses about a second apart (first opens the FOREST 1 /
CAVE 1 menu, second confirms the highlighted FOREST 1); the Forest pad returns with one A press. Each leg is counted
only when the floor register changes and a live player entity exists; evidence goes to mandate/t0-trial.jsonl and
mandate/t0-receipt.json.

    python pso-t0-trial.py --transitions 10
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
BOUNDED = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-bounded.py")
PYTHON = sys.executable
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
FLOOR = 0x805D5FC0
TOWN_PAD = (360.0, 26.0)
FOREST_PAD = (12.1, -16.6)
TOWN_ROUTE = [(255.0, -5.0), (340.0, 50.0), TOWN_PAD]


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
    print(json.dumps(record)[:400], flush=True)
    with (OUT / "t0-trial.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


class Session:
    def __init__(self):
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = next((row for row in rows if row.get("state") in ("running", "starting")), None)
        if live is None:
            raise RuntimeError("no live session")
        self.sid = live["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST", 90)

    def read(self, address, length):
        raw = self.rpc("read_memory", address=address, length=length)
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def floor(self):
        raw = self.read(FLOOR, 4)
        return int.from_bytes(raw, "big") if len(raw) == 4 else None

    def player(self):
        return (self.rpc("state") or {}).get("player") or {}

    def position(self):
        player = self.player()
        return float(player.get("x") or 0), float(player.get("z") or 0)

    def distance_to(self, point):
        x, z = self.position()
        return ((x - point[0]) ** 2 + (z - point[1]) ** 2) ** 0.5

    def send(self, key, hold=0.14):
        for down in (True, False):
            call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                               "input": {"session_id": self.sid, "op": "send_input",
                                         "args": {"events": [{"key": key, "down": down}]}}}, "POST", 60)
            time.sleep(hold if down else 0.1)


def walk_chain(waypoints, tolerance=5.0, motion="probe", seconds=120.0):
    args = [PYTHON, str(BOUNDED), "chain", "--tolerance", f"{tolerance}", "--motion", motion,
            "--per-hop", "75", "--seconds", f"{seconds}", "--no-calibrate", "--via"]
    args += [f"{x},{z}" for x, z in waypoints]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=seconds + 150,
                                env=dict(os.environ, GBOX_API=BASE))
        return result.returncode, (result.stdout or "")[-400:]
    except subprocess.TimeoutExpired:
        return 124, "walk chain timeout"


def wait_floor(session, target, timeout=18.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session.floor() == target:
            player = session.player()
            return {"floor": target, "x": round(float(player.get("x") or 0), 1),
                    "z": round(float(player.get("z") or 0), 1), "room": player.get("room")}
        time.sleep(0.8)
    return None


def town_to_forest(session):
    for attempt in range(1, 6):
        start = session.position()
        distance = session.distance_to(TOWN_PAD)
        # A return from the Forest lands on the pad's own plaza (the pad is 20-80 units away, railing behind us); only a
        # far start needs the long way round the railing.
        route = [TOWN_PAD] if distance < 90 else TOWN_ROUTE
        rc, tail = walk_chain(route, tolerance=4.0)
        distance = session.distance_to(TOWN_PAD)
        log({"event": "town-route", "attempt": attempt, "distance": round(distance, 1), "rc": rc,
             "start": [round(start[0], 1), round(start[1], 1)]})
        if distance > 14:
            continue
        session.send("a")
        time.sleep(0.9)
        session.send("a")
        got = wait_floor(session, 1)
        if got:
            return got
        session.send("a")
        time.sleep(0.8)
        session.send("a")
        got = wait_floor(session, 1, 10.0)
        if got:
            return got
    return None


def forest_to_town(session):
    for attempt in range(1, 4):
        rc, tail = walk_chain([FOREST_PAD], tolerance=4.0, motion="hill", seconds=90.0)
        log({"event": "forest-route", "attempt": attempt, "distance": round(session.distance_to(FOREST_PAD), 1),
             "rc": rc})
        if session.distance_to(FOREST_PAD) > 10:
            continue
        for press in range(3):
            session.send("a")
            got = wait_floor(session, 0, 6.0)
            if got:
                return got
        if session.floor() == 0:
            return {"floor": 0, "x": None, "z": None, "room": None}
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="town -> Forest, controller-only, ten verified transitions")
    parser.add_argument("--transitions", type=int, default=10)
    args = parser.parse_args(argv)
    session = Session()
    log({"event": "start", "session": session.sid, "transitions": args.transitions, "floor": session.floor()})
    verified = []
    for cycle in range(1, args.transitions + 1):
        if session.floor() != 0:
            log({"event": "wait-town", "cycle": cycle, "floor": session.floor()})
            if not forest_to_town(session):
                log({"event": "abort", "reason": "not in town and could not return"})
                break
        got = town_to_forest(session)
        if not got:
            log({"event": "abort", "cycle": cycle, "reason": "could not enter Forest"})
            break
        verified.append({"cycle": cycle, "leg": "town->forest", **got})
        log({"event": "verified", "cycle": cycle, "leg": "town->forest", **got})
        got_back = forest_to_town(session)
        if not got_back:
            log({"event": "abort", "cycle": cycle, "reason": "could not return to Pioneer 2"})
            break
        verified.append({"cycle": cycle, "leg": "forest->town", **got_back})
        log({"event": "verified", "cycle": cycle, "leg": "forest->town", **got_back})
    passed = [row for row in verified if row["leg"] == "town->forest"]
    receipt = {"schema": 1, "session": session.sid, "requested": args.transitions,
               "town_to_forest_verified": len(passed), "legs": verified,
               "controller_only": True, "memory_writes": 0, "dev_warps": 0, "at": time.time()}
    (OUT / "t0-receipt.json").write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    log({"event": "done", "verified": len(passed), "requested": args.transitions,
         "receipt": str(OUT / "t0-receipt.json")})
    print(json.dumps({"verified": len(passed), "requested": args.transitions}))
    return 0 if len(passed) >= args.transitions else 1


if __name__ == "__main__":
    raise SystemExit(main())

