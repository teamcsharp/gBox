"""Relaunch the game, drive the boot menus to an in-game state, then import a savestate (and verify it resumes).

The hard freeze at 00:07 left the guest CPU stopped; relaunching and importing a snapshot at the *title screen* left
the new emulator spinning with in-game RAM (49% CPU, MEM1 static). This does the import only after the game is really
in-game (the player entity exists and MEM1 is ticking), so the loaded state lands in a running game.

    python pso-boot-restore.py --artifact 06ddc641...
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
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
WORKER = "ee68c2f40f10443b"


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
    with (OUT / "boot-restore.jsonl").open("a", encoding="utf-8") as handle:
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
            log(f"job {job_id} {row.get('state')}: {str(row.get('output'))[:250]} {row.get('error') or ''}")
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


def ticking(session_id):
    a = read(session_id, 0x804FE000, 0x4000)
    time.sleep(1.0)
    b = read(session_id, 0x804FE000, 0x4000)
    return sum(1 for index in range(0, 0x4000, 4) if a[index:index + 4] != b[index:index + 4])


def send(session_id, key, hold=0.15):
    for down in (True, False):
        call("/api/jobs", {"tool": "session_op", "require_worker": WORKER,
                           "input": {"session_id": session_id, "op": "send_input",
                                     "args": {"events": [{"key": key, "down": down}]}}}, "POST", 60)
        time.sleep(hold if down else 0.1)


def player(session_id):
    return ((rpc(session_id, "state") or {}).get("player") or {}) or {}


def main(argv=None):
    parser = argparse.ArgumentParser(description="relaunch, boot to in-game, import snapshot, verify")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--no-import", action="store_true")
    args = parser.parse_args(argv)
    before = {row["session_id"] for row in sessions()}
    entry = json.loads(ENTRY.read_text(encoding="utf-8"))
    wait(submit("launch_game", {"game": entry, "keep_session": ""}), 600)
    deadline = time.monotonic() + 240
    session = None
    while time.monotonic() < deadline:
        session = next((row for row in sessions() if row["session_id"] not in before), None)
        if session is not None:
            break
        time.sleep(2)
    if session is None:
        raise SystemExit("no new session")
    session_id = session["session_id"]
    log(f"session {session_id}")
    # Drive the boot menus: title -> main menu -> offline game -> character -> confirm.
    for attempt in range(10):
        info = player(session_id)
        if info.get("ptr"):
            break
        send(session_id, "start")
        time.sleep(2.0)
        send(session_id, "a")
        time.sleep(3.0)
        log(f"boot attempt {attempt + 1}: player={bool(info.get('ptr'))} ticks={ticking(session_id)}")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        info = player(session_id)
        if info.get("ptr") and ticking(session_id) > 0:
            break
        time.sleep(3)
    info = player(session_id)
    log(f"pre-import player {info.get('x')},{info.get('z')} room {info.get('room')} ticks={ticking(session_id)}")
    if args.no_import:
        return 0
    wait(submit("state_transfer", {"session_id": session_id, "op": "import", "artifact": args.artifact,
                                   "slot": None, "not_before": 0}), 300)
    time.sleep(3)
    command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": {"op": "survival", "on": True}}
    survival = call(f"/api/sessions/{session_id}/rpc", {"op": "pso_controls", "args": command}, "POST", 60) or {}
    log(f"survival {str(survival)[:160]}")
    info = player(session_id)
    log(f"post-import player {info.get('x')},{info.get('z')} room {info.get('room')} hp {info.get('hp')} "
        f"ticks={ticking(session_id)}")
    print(json.dumps({"session": session_id, "player": info, "ticks": ticking(session_id)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
