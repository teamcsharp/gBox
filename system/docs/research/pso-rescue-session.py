"""Bring the PSO live session back after the local gBox server died.

The server process was lost at ~23:29; with it went the in-game progress, but the operator's moment-snapshot
(state_transfer op=snapshot at 23:28:34) is a real Dolphin savestate (artifact 4ccd99..., starts with GPOE8P) - so
relaunching the game and importing that snapshot restores the character where it was, TSUMIKIRI J-SWORD +50 and all.

    python pso-rescue-session.py            # launch + import + verify
    python pso-rescue-session.py --verify-only
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
ENTRY = pathlib.Path(r"D:\gBox\pso-ds\mandate\pso-catalog-entry.json")
WORKER = "ee68c2f40f10443b"
ARTIFACT = "4ccd99fe106a684d5ef51a1c00adf922f745717cb48d2690222b6d4200f9fc1f"
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message):
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "rescue.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


def submit(tool, input_payload):
    job = call("/api/jobs", {"tool": tool, "require_worker": WORKER, "input": input_payload}, "POST", 60)
    if not isinstance(job, dict) or not job.get("id"):
        raise RuntimeError(f"{tool} submit rejected: {str(job)[:300]}")
    log(f"{tool} job {job['id']} submitted")
    return job["id"]


def wait_job(job_id, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = call("/api/jobs/" + job_id, timeout=60)
        state = (row or {}).get("state")
        if state in ("succeeded", "failed", "cancelled"):
            log(f"job {job_id} {state} error={row.get('error')}")
            return row
        time.sleep(2)
    raise RuntimeError(f"job {job_id} still running after {timeout}s")


def live_session():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row for row in rows if row.get("state") in ("running", "starting")), None)


def rpc(session_id, op, **args):
    return call(f"/api/sessions/{session_id}/rpc", {"op": op, "args": args}, "POST", 120)


def read(session_id, address, length):
    raw = rpc(session_id, "read_memory", address=address, length=length)
    return bytes.fromhex(raw) if isinstance(raw, str) else b""


def verify(session_id):
    state = rpc(session_id, "state") or {}
    player = state.get("player") or {}
    pointer = player.get("ptr")
    if not pointer:
        return {"ready": False, "state": state}
    player_ptr = int(pointer, 16)
    status = read(session_id, player_ptr + 0x254, 4)
    inventory = rpc(session_id, "pso_controls", command_id=__import__("uuid").uuid4().hex,
                    expires=time.time() + 12, input={"op": "list"}) or {}
    weapons = [row for row in inventory.get("inventory") or []
               if str(row.get("code", "")).startswith("00") and row.get("equipped")]
    return {"ready": True, "player": {k: player.get(k) for k in ("x", "y", "z", "room", "hp")},
            "status": status.hex(), "weapon": [(row.get("code"), row.get("name"),
            bytes.fromhex(row.get("data") or "")[3] if len(bytes.fromhex(row.get("data") or "")) > 3 else None)
            for row in weapons]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="relaunch PSO and restore the operator's moment snapshot")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--artifact", default=ARTIFACT)
    args = parser.parse_args(argv)
    if not args.verify_only:
        session = live_session()
        if session is None:
            entry = json.loads(ENTRY.read_text(encoding="utf-8"))
            job = submit("launch_game", {"game": entry})
            result = wait_job(job, 600)
            if result.get("state") != "succeeded":
                raise SystemExit(f"launch failed: {result.get('error')}")
            log(f"launch result: {json.dumps(result.get('output'))[:400]}")
        # wait for the session to appear and reach running
        deadline = time.monotonic() + 180
        session = None
        while time.monotonic() < deadline:
            session = live_session()
            if session is not None:
                break
            time.sleep(2)
        if session is None:
            raise SystemExit("no live session appeared after the launch")
        session_id = session["session_id"]
        log(f"session {session_id} state {session.get('state')}")
        # let the game boot to the attract/title loop before loading the savestate
        for _ in range(40):
            ver = verify(session_id)
            if ver.get("ready"):
                break
            time.sleep(3)
        log(f"pre-import: {json.dumps(verify(session_id))[:300]}")
        job = submit("state_transfer", {"session_id": session_id, "op": "import", "artifact": args.artifact})
        result = wait_job(job, 300)
        log(f"import result: {json.dumps(result.get('output'))[:400]}")
        time.sleep(3)
    session = live_session()
    if session is None:
        raise SystemExit("no live session to verify")
    final = verify(session["session_id"])
    log(f"post-import: {json.dumps(final)[:500]}")
    print(json.dumps(final, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
