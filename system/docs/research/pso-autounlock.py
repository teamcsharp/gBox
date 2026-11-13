"""autounlock - open every door the operator walks up to. ASSISTED mode, never evidence.

The operator's instruction, twice: *"just auto unlock any door I walk up to"* and *"unlock any door that I approach
ever"*. This does that, and nothing else:

* it polls the live state ~8 times a second and looks for any door-class entity within `--radius` of the player;
* when one appears it writes the **whole 32-byte stage-flag group of the current floor** to 0xFF, which is what the
  game's doors read every frame (verified in `pso_coop_gates`: the actor's native state is recomputed from that array);
* it rate-limits per floor so a character standing in a doorway does not write sixty times a second.

It is deliberately a **separate process** from the controller. Every line it prints is prefixed `ASSISTED`, and nothing
the controller does depends on it: a run with this tool attached can never be used as evidence for a normal-play gate
(the mandate, section 5). It writes memory; the controller writes nothing.

    python pso-autounlock.py                    # doors within 45 units, foreground
    python pso-autounlock.py --radius 60 --seconds 600
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
import urllib.request

# The app the worker actually registered with. Two app instances can run (the config default 8765 and a
# hand-started 18765); talking to the wrong one returns 504 for every session RPC while the other answers
# normally - measured. GBOX_API overrides it.
BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
STAGE_FLAGS = 0x80515CC8
FLOOR_POINTER = 0x805D5FC0
GROUP_SIZE = 32
GATE_CLASSES = ("TObjDoor", "TObjLazerFenceNorm", "TObjLazerFence", "TOBarrierEnergy01",
                "TLazerFenceSw", "TObjDoorKey")


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] ASSISTED {str(message).encode('ascii', 'replace').decode('ascii')}",
          flush=True)


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="assisted auto-unlock of approached doors")
    parser.add_argument("--radius", type=float, default=45.0)
    parser.add_argument("--seconds", type=float, default=3600.0)
    parser.add_argument("--cooldown", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true", help="log what it would unlock, write nothing")
    args = parser.parse_args(argv)

    sid = live_session()
    if not sid:
        log("no live session")
        return 2
    worker = sid.split("-")[0]
    log(f"watching session {sid} for doors within {args.radius:.0f} units "
        f"({'DRY RUN' if args.dry_run else 'writing the floor flag group'})")

    started = time.monotonic()
    last_write = {}
    writes = 0
    while time.monotonic() - started < args.seconds:
        state = call(f"/api/sessions/{sid}/rpc", {"op": "state", "args": {}}, "POST")
        player = (state or {}).get("player") or {}
        if player.get("x") is None:
            time.sleep(0.12)
            continue
        px, pz = float(player["x"]), float(player["z"])
        near = []
        for entity in (state.get("entities") or []):
            if str(entity.get("class")) not in GATE_CLASSES or entity.get("x") is None:
                continue
            distance = ((float(entity["x"]) - px) ** 2 + (float(entity["z"]) - pz) ** 2) ** 0.5
            if distance <= args.radius:
                near.append((distance, str(entity.get("class")), entity.get("ptr")))
        if not near:
            time.sleep(0.12)
            continue
        near.sort()
        distance, cls, ptr = near[0]
        floor_raw = call(f"/api/sessions/{sid}/rpc",
                         {"op": "read_memory", "args": {"address": FLOOR_POINTER, "length": 4}}, "POST")
        try:
            floor = int.from_bytes(bytes.fromhex(floor_raw), "big")
        except (TypeError, ValueError):
            time.sleep(0.3)
            continue
        now = time.monotonic()
        if now - last_write.get(floor, 0.0) < args.cooldown:
            time.sleep(0.12)
            continue
        address = STAGE_FLAGS + floor * GROUP_SIZE
        current = call(f"/api/sessions/{sid}/rpc",
                       {"op": "read_memory", "args": {"address": address, "length": GROUP_SIZE}}, "POST")
        if isinstance(current, str) and current.lower() == "ff" * GROUP_SIZE:
            log(f"floor {floor} already fully open (door {cls} at {distance:.0f} units)")
            last_write[floor] = now
            time.sleep(0.12)
            continue
        if args.dry_run:
            log(f"would write floor {floor} flags for {cls} {ptr} at {distance:.0f} units")
            last_write[floor] = now
            continue
        job = call("/api/jobs", {"tool": "write_memory", "require_worker": worker,
                                 "input": {"session_id": sid, "address": address,
                                           "hex_bytes": ("ff" * GROUP_SIZE)}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        deadline = time.monotonic() + 5.0
        state_of_job = "no-job"
        while job_id and time.monotonic() < deadline:
            row = call("/api/jobs/" + job_id)
            state_of_job = str((row or {}).get("state"))
            if state_of_job in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.05)
        last_write[floor] = now
        if state_of_job == "succeeded":
            writes += 1
            log(f"floor {floor} unlocked for {cls} {ptr} at {distance:.0f} units (write #{writes})")
        else:
            log(f"floor {floor} write did not succeed: {state_of_job}")
        time.sleep(0.12)
    log(f"stopped after {writes} unlock write(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
