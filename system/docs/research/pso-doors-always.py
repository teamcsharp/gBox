"""Proximity door unlock, permanent: within 30 units of any door, set every gate flag on the floor.

The operator's standing request (2026-11-13, live): "doors should unlock as i get within 30 steps of it
permanently". Measured on the live session: setting only the room's switch bits (60/61/62/90/91/100/101) did NOT
open the Cave door at (-600, 805); writing all 32 bytes of the current floor's stage-flag group DID - the
operator walked straight through it (room 34 -> 8) within two seconds of the write.

So the action is: poll the door-family entities around the player; as soon as any door/barrier/fence is within
30 units, saturate the current floor's stage-flag group (0x80515CC8 + floor*32, all 0xFF) through the audited
write_memory job. The bits are permanent - nothing in this tool ever clears them - and the loop re-applies them
if the game reloads the group while a door is still close.

    python pso-doors-always.py --once
    python pso-doors-always.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import time
import urllib.request

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
PHASE = 0x804FE120
FLOOR = 0x805D5FC0
STAGE_FLAG_BASE = 0x80515CC8
GROUP_SIZE = 32
GROUPS = 18
UNLOCK_STEPS = 30.0
DOORISH = ("TODoor", "TObjDoor", "LazerFence", "Barrier", "Fence")
SATURATED = b"\xff" * GROUP_SIZE


def token():
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=60):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "doors-always.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


class Session:
    def __init__(self):
        rows = call("/api/sessions")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        live = [row for row in rows if row.get("state") in ("running", "starting") and row.get("adapter") == "dolphin"]
        if not live:
            raise RuntimeError("no live dolphin session")
        self.sid = live[0]["session_id"]
        self.worker = self.sid.split("-")[0]

    def rpc(self, op, **args):
        return call(f"/api/sessions/{self.sid}/rpc", {"op": op, "args": args}, "POST")

    def read(self, address, length):
        raw = self.rpc("read_memory", address=int(address), length=int(length))
        return bytes.fromhex(raw) if isinstance(raw, str) else b""

    def write(self, address, data):
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": self.worker,
                                 "input": {"session_id": self.sid, "address": int(address),
                                           "hex_bytes": data.hex()}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return False
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") == "succeeded":
                return True
            if isinstance(row, dict) and row.get("state") in ("failed", "cancelled"):
                return False
            time.sleep(0.05)
        return False


def near_door(state, radius):
    """The nearest door-family entity within radius of the player, or None."""
    player = state.get("player") or {}
    try:
        px, pz = float(player["x"]), float(player["z"])
    except (KeyError, TypeError, ValueError):
        return None
    best = None
    for entity in (state.get("entities") or [])[:700]:
        cls = str(entity.get("class") or "")
        if not any(word in cls for word in DOORISH):
            continue
        try:
            distance = math.hypot(float(entity["x"]) - px, float(entity["z"]) - pz)
        except (KeyError, TypeError, ValueError):
            continue
        if distance <= radius and (best is None or distance < best[0]):
            best = (distance, cls)
    return best


def unlock(session, state) -> bool:
    phase = session.read(PHASE, 4)
    if len(phase) != 4 or int.from_bytes(phase, "big") != 14:
        return False                       # only in offline free-play; never in menus/boot
    raw_floor = session.read(FLOOR, 4)
    if len(raw_floor) != 4:
        return False
    floor = int.from_bytes(raw_floor, "big")
    if not 0 < floor < GROUPS:
        return False
    door = near_door(state, UNLOCK_STEPS)
    if door is None:
        return False
    address = STAGE_FLAG_BASE + floor * GROUP_SIZE
    current = session.read(address, GROUP_SIZE)
    if current == SATURATED:
        return False
    if session.write(address, SATURATED):
        log(f"floor {floor}: {door[1]} within {door[0]:.0f} units -> stage-flag group {address:#x} "
            f"saturated (permanent door unlock)")
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="unlock every door within 30 units, permanently")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--period", type=float, default=0.4)
    args = parser.parse_args(argv)
    session = None
    log(f"proximity door unlock started ({UNLOCK_STEPS:.0f} units, permanent)")
    while True:
        try:
            if session is None:
                session = Session()
            state = session.rpc("state") or {}
            unlock(session, state)
        except Exception as error:                               # noqa: BLE001
            session = None
            log(f"pass failed: {type(error).__name__}: {error}")
        if args.once:
            return 0
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())
