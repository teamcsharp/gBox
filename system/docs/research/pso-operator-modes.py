"""operator-modes - keep the operator's standing PSO preferences applied to the live session.

The operator's standing requests (2026-11-13):
  * "my build is supposed to change every 2 minutes"                              -> Randomized, interval=120
  * "i need this paralysis gone and ... enemies [must not] be able to do that"    -> Cure/Paralysis + the other
                                                                                      attack/control ailments equipped
  * "remove ... and prevent ... automatically on game load"                       -> re-applied after any load

This is a small live watchdog, not a game mod: every 20 s it reads the session's own state through the audited
control RPC, and only acts when something is missing. It never writes memory directly; gear goes through the native
give/equip path (pso-native.py) and Randomized through its own op.

    python pso-operator-modes.py --once
    python pso-operator-modes.py            # watchdog until interrupted
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\mandate")
NATIVE = pathlib.Path(r"C:\_tools\gBox\system\docs\research\pso-native.py")
PYTHON = sys.executable
CURE_UNITS = ("010343", "010347", "010346", "010345")     # Paralysis, Shock, Freeze, Confuse
FULL_UNIT_SET = ",".join(CURE_UNITS)
ROTATION = {"interval": 120, "categories": ["weapon", "shield", "mag"], "character_class": "HUmar"}


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except urllib.error.HTTPError as error:
        return {"http_status": error.code, "body": error.read().decode()[:600]}
    except Exception as error:                                   # noqa: BLE001
        return {"error": str(error)}


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "operator-modes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "message": message}) + "\n")


def live_session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    alive = [row for row in rows if row.get("state") in ("running", "starting")
             and row.get("adapter") == "dolphin" and row.get("game_id", "").startswith("436e")]
    return alive[0]["session_id"] if alive else ""


def mods(sid: str, **fields):
    command = {"command_id": str(uuid.uuid4()), "expires": time.time() + 12, "input": fields}
    return call(f"/api/sessions/{sid}/rpc", {"op": "pso_controls", "args": command}, "POST", 120)


def tick(sid: str) -> None:
    status = mods(sid, op="modes") or {}
    randomized = status.get("randomized") or {}
    if not randomized.get("on"):
        if randomized and randomized.get("error"):
            mods(sid, op="randomized", on=False)
            time.sleep(0.4)
        started = mods(sid, op="randomized", on=True, **ROTATION)
        log(f"randomized started: {json.dumps(started)[:300]}")
    inventory = mods(sid, op="list") or {}
    rows = inventory.get("inventory") or []
    equipped = {row["code"] for row in rows if row.get("equipped")}
    missing = [code for code in CURE_UNITS if code not in equipped]
    if missing:
        log(f"cure units missing: {missing}; re-applying through the native equipment path")
        result = subprocess.run([PYTHON, str(NATIVE), "--units", FULL_UNIT_SET],
                                capture_output=True, text=True, timeout=300)
        log(f"native re-apply rc={result.returncode} out={result.stdout[-400:]} err={result.stderr[-300:]}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="keep the operator's PSO modes applied")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--period", type=float, default=20.0)
    args = parser.parse_args(argv)
    while True:
        sid = live_session()
        if sid:
            try:
                tick(sid)
            except Exception as error:                           # noqa: BLE001 - a watchdog never dies on one pass
                log(f"tick failed: {type(error).__name__}: {error}")
        else:
            log("no live PSO session yet")
        if args.once:
            return 0
        time.sleep(args.period)


if __name__ == "__main__":
    raise SystemExit(main())
