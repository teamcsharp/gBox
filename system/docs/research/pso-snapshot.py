"""Keep a rolling Dolphin moment snapshot of the live PSO session.

Measured 2026-11-13: when the Windows local authority (gbox.desktop_local) died, the session was reaped and the
running game became uncontrollable - two hours of play were only saved because the operator had taken one manual
snapshot 5 minutes earlier, and that artifact (a Dolphin savestate, not a cloud blob) restored the exact moment on a
freshly launched session (`pso-rescue-session.py`). This keeps that safety net automatic: every few minutes it
submits `state_transfer op=snapshot` for the live session and records the artifact digest.

    python pso-snapshot.py                 # every 5 minutes
    python pso-snapshot.py --interval 180
    python pso-snapshot.py --once
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


def call(path, payload=None, method="GET", timeout=180):
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
    with (OUT / "snapshots.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


def live_session():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row for row in rows if row.get("state") in ("running", "starting")), None)


def snapshot():
    session = live_session()
    if session is None:
        return None
    session_id = session["session_id"]
    worker = session_id.split("-")[0]
    job = call("/api/jobs", {"tool": "state_transfer", "require_worker": worker,
                             "input": {"session_id": session_id, "op": "snapshot", "artifact": "",
                                       "slot": None, "not_before": 0}}, "POST", 60)
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        raise RuntimeError(f"snapshot submit rejected: {str(job)[:200]}")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        row = call("/api/jobs/" + job_id) or {}
        state = row.get("state")
        if state == "succeeded":
            result = (row.get("output") or {}).get("result") or {}
            artifact = result.get("artifact")
            log(f"snapshot ok session {session_id} artifact {artifact} bytes {result.get('bytes')} "
                f"path {result.get('path')}")
            return artifact
        if state in ("failed", "cancelled"):
            raise RuntimeError(f"snapshot job {job_id} {state}: {row.get('error')}")
        time.sleep(2)
    raise RuntimeError(f"snapshot job {job_id} timed out")


def main(argv=None):
    parser = argparse.ArgumentParser(description="rolling moment snapshots of the live PSO session")
    parser.add_argument("--interval", type=float, default=300.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    log(f"snapshot keeper started (every {args.interval:.0f}s)")
    while True:
        try:
            snapshot()
        except Exception as error:                               # noqa: BLE001
            log(f"snapshot failed: {type(error).__name__}: {error}")
        if args.once:
            return 0
        time.sleep(max(30.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
