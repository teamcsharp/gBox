"""Recover from a hard-frozen emulator: relaunch the game (which stops the stuck one) and import the last good state.

The 00:07 freeze left Dolphin's Qt window alive with the whole of MEM1 static (1 word of 6.29M changed in a second)
and no GMV/listener on its debug port: the guest was stopped for good, so a savestate load inside the same emulator
could not restart it. `launch_game` closes the running session and starts a fresh emulator; importing a *pre-freeze*
snapshot then restores the moment. Survival (the virtual Scape Doll) is re-armed after the import because the snapshot
predates it.

    python pso-relaunch-restore.py --artifact 06ddc64173e472eed6f3e87a7061a59081fe11d175183b37346d245fbb170031
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:18765"
TOKEN = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token").read_text(encoding="utf-8").strip()
ENTRY = pathlib.Path(r"D:\gBox\pso-ds\mandate\pso-catalog-entry.json")
WORKER = "ee68c2f40f10443b"
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
    with (OUT / "relaunch-restore.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


def submit(tool, payload):
    job = call("/api/jobs", {"tool": tool, "require_worker": WORKER, "input": payload}, "POST", 60)
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        raise RuntimeError(f"{tool} submit rejected: {str(job)[:300]}")
    log(f"{tool} job {job_id}")
    return job_id


def wait(job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = call("/api/jobs/" + job_id) or {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            log(f"job {job_id} {row.get('state')}: {str(row.get('output'))[:300]} {row.get('error') or ''}")
            return row
        time.sleep(2)
    raise RuntimeError(f"job {job_id} timed out")


def sessions():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def rpc(session_id, op, **args):
    return call(f"/api/sessions/{session_id}/rpc", {"op": op, "args": args}, "POST", 90)


def read(session_id, address, length):
    raw = rpc(session_id, "read_memory", address=address, length=length)
    return bytes.fromhex(raw) if isinstance(raw, str) else b""


def main(argv=None):
    parser = argparse.ArgumentParser(description="relaunch the frozen game and restore a snapshot")
    parser.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)
    before = {row["session_id"] for row in sessions()}
    entry = json.loads(ENTRY.read_text(encoding="utf-8"))
    job = submit("launch_game", {"game": entry, "keep_session": ""})
    result = wait(job, 600)
    if result.get("state") != "succeeded":
        raise SystemExit(f"launch failed: {result.get('error')}")
    deadline = time.monotonic() + 240
    session = None
    while time.monotonic() < deadline:
        live = sessions()
        session = next((row for row in live if row["session_id"] not in before), None)
        if session is not None:
            break
        time.sleep(2)
    if session is None:
        raise SystemExit("no new session appeared")
    session_id = session["session_id"]
    log(f"new session {session_id}")
    # let the game reach an in-game state (the snapshot can be imported at any point, but this makes it clean)
    for _ in range(80):
        state = rpc(session_id, "state") or {}
        if (state.get("player") or {}).get("ptr"):
            break
        time.sleep(2)
    job = submit("state_transfer", {"session_id": session_id, "op": "import", "artifact": args.artifact,
                                    "slot": None, "not_before": 0})
    wait(job, 300)
    time.sleep(3)
    command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": {"op": "survival", "on": True}}
    survival = call(f"/api/sessions/{session_id}/rpc", {"op": "pso_controls", "args": command}, "POST", 60) or {}
    log(f"survival re-armed: {str(survival)[:200]}")
    player = (rpc(session_id, "state") or {}).get("player") or {}
    hp = read(session_id, int(player["ptr"], 16) + 0x32C, 2) if player.get("ptr") else b""
    log(f"player {player.get('x')},{player.get('z')} room {player.get('room')} hp bytes {hp.hex()}")
    print(json.dumps({"session": session_id, "player": player, "hp": hp.hex()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
