"""session - own the PSO session lifecycle: stop, launch, and drive the menus to a character in the world.

Why this exists rather than reusing `endless.py`'s helpers: that file's `ensure_in_game` also exists, but it is an
inner function of a loop that also arms global stage-flag writes, and the whole point of a fresh session is that
nothing writes the flag array. This driver does one thing - get a clean session into the world - and reports the
stage-flag array before and after so the state can be audited.

    python pso-session.py status
    python pso-session.py restart --force      # stop the live session, launch, boot, print flags

The boot key sequence is the one measured by the earlier campaign (title -> offline game -> character select -> load),
with a menu-closing probe first, because a pause menu reads exactly like "no player" in the entity table.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
import urllib.request

BASE = "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\bounded")
GAME = "436e0bb84d5337d1"            # PSO Episode I & II Plus (USA), the catalog id the campaign used
STAGE_FLAGS = 0x80515CC8
FLOOR_POINTER = 0x805D5FC0
BOOT_MENU = [("start", 2.6), ("down", 1.2), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.5)]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=40):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                      # noqa: BLE001
        return {"err": type(exc).__name__, "code": getattr(exc, "code", None)}


def sessions() -> list:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return rows


def live() -> list:
    return [row for row in sessions() if row.get("state") in ("running", "starting")]


def worker() -> str:
    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row["id"] for row in rows if row.get("online")), "")


def wait_job(job_id: str, seconds: float = 90.0) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = call("/api/jobs/" + job_id)
        if isinstance(row, dict) and row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
        time.sleep(1.0)
    return "timeout"


def job(tool: str, payload: dict, *, seconds: float = 90.0) -> str:
    created = call("/api/jobs", {"tool": tool, "require_worker": worker(), "input": payload}, "POST")
    job_id = created.get("id") if isinstance(created, dict) else None
    if not job_id:
        log(f"job {tool} rejected: {str(created)[:160]}")
        return "rejected"
    return wait_job(job_id, seconds)


class Pad:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.worker = sid.split("-")[0]

    def state(self) -> dict:
        state = call(f"/api/sessions/{self.sid}/rpc", {"op": "state", "args": {}}, "POST")
        return state if isinstance(state, dict) else {}

    def read(self, address: int, length: int) -> bytes:
        raw = call(f"/api/sessions/{self.sid}/rpc",
                   {"op": "read_memory", "args": {"address": address, "length": length}}, "POST")
        try:
            return bytes.fromhex(raw) if isinstance(raw, str) else b""
        except ValueError:
            return b""

    def tap(self, key: str) -> None:
        call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                           "input": {"session_id": self.sid, "op": "send_input",
                                     "args": {"events": [{"key": key, "down": True}, {"key": key, "down": False}]}}},
             "POST", timeout=30)
        time.sleep(0.35)

    def release(self) -> None:
        call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                           "input": {"session_id": self.sid, "op": "send_input",
                                     "args": {"events": [{"key": key, "down": False} for key in
                                                         ("up", "down", "left", "right")]}}}, "POST", timeout=30)

    def flags(self) -> dict:
        raw = self.read(STAGE_FLAGS, 576)
        floor = self.read(FLOOR_POINTER, 4)
        return {"floor": int.from_bytes(floor, "big") if len(floor) == 4 else None,
                "groups_set_bits": [sum(bin(byte).count("1") for byte in raw[g * 32:(g + 1) * 32])
                                    for g in range(18)] if raw else [],
                "sha256": __import__("hashlib").sha256(raw).hexdigest() if raw else None}


def boot(pad: Pad, seconds: float = 90.0) -> bool:
    """Drive the menus until a player entity exists. Bounded, and it says what it saw at every step."""
    deadline = time.monotonic() + seconds
    attempt = 0
    while time.monotonic() < deadline:
        state = pad.state()
        if state.get("player"):
            return True
        attempt += 1
        log(f"boot attempt {attempt}: no player yet - closing any menu and pressing through the title")
        pad.tap("start")
        time.sleep(1.2)
        if pad.state().get("player"):
            log("a pause menu was open; character was there all along")
            return True
        pad.tap("b")
        time.sleep(0.8)
        if pad.state().get("player"):
            log("a dialog was open; character is in the world")
            return True
        for key, wait in BOOT_MENU:
            if time.monotonic() > deadline:
                break
            pad.tap(key)
            time.sleep(wait)
    return False


def restart(args) -> int:
    current = live()
    if current and not args.force:
        log(f"a session is already live ({current[0]['session_id']}); pass --force to replace it")
        return 2
    for row in current:
        sid = row["session_id"]
        log(f"stopping {sid}")
        state = job("session_op", {"session_id": sid, "op": "stop_game", "args": {}}, seconds=60)
        log(f"stop_game: {state}")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and any(r["session_id"] == sid for r in live()):
            time.sleep(1.5)
        log("session ended" if not any(r["session_id"] == sid for r in live()) else "session did not end")
    game = call("/api/catalog/" + GAME)
    if not isinstance(game, dict) or game.get("err"):
        log(f"catalog lookup failed: {str(game)[:160]}")
        return 2
    log(f"launching {game.get('title') or GAME}")
    state = job("launch_game", {"game": game}, seconds=120)
    log(f"launch_game: {state}")
    deadline = time.monotonic() + 60
    found = ""
    while time.monotonic() < deadline and not found:
        rows = live()
        found = rows[0]["session_id"] if rows else ""
        if not found:
            time.sleep(2)
    if not found:
        log("no session appeared after launch")
        return 2
    log(f"session {found} is up - booting")
    pad = Pad(found)
    if not boot(pad, seconds=args.boot_seconds):
        log("could not reach a character in the world")
        return 3
    state = pad.state()
    player = state.get("player") or {}
    log(f"in the world: {player.get('class')} at ({player.get('x')},{player.get('z')}) room {player.get('room')} "
        f"hp {player.get('hp')}/{player.get('hp_max')}")
    audit = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": found, "player": player, **pad.flags()}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"session-open-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(audit, indent=1), encoding="utf-8")
    log(f"floor {audit['floor']}  set bits per group {audit['groups_set_bits']}")
    log(f"wrote {path}")
    return 0


def status(args) -> int:
    rows = live()
    if not rows:
        log("no live session")
        return 2
    pad = Pad(rows[0]["session_id"])
    state = pad.state()
    player = state.get("player") or {}
    log(f"session {pad.sid}  entities {len(state.get('entities') or [])}")
    log(f"player at ({player.get('x')},{player.get('z')}) room {player.get('room')} "
        f"hp {player.get('hp')}/{player.get('hp_max')}")
    log(f"flags: {json.dumps(pad.flags())}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PSO session lifecycle")
    sub = parser.add_subparsers(dest="mode", required=True)
    restart_parser = sub.add_parser("restart")
    restart_parser.add_argument("--force", action="store_true")
    restart_parser.add_argument("--boot-seconds", type=float, default=120.0)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    return restart(args) if args.mode == "restart" else status(args)


if __name__ == "__main__":
    raise SystemExit(main())
