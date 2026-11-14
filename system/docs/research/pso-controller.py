"""controller - put the operator's physical pad onto the bot's virtual pad so the game actually reads it.

Why this exists. Dolphin's `GCPad1` is bound to `XInput/{vpad.slot}` - the **virtual** pad the bot drives
(`adapters.PAD_INI_WIN` replaces `Device = XInput/0/Gamepad` with the vpad's slot at launch). The operator's physical pad
is on another XInput slot, so Dolphin never reads it and the operator is pushed onto the keyboard. This relays the pad
they are actually holding into the virtual pad, so one binding serves both: the operator drives the game, and the bot
keeps the same channel when they put the pad down.

It reads the pad directly through gBox's own XInput binding (`gbox.gamepads.xinput_snapshot`), so no extra driver is
needed. On start it watches both slots and latches onto the first one that shows *activity*: the bot's virtual pad sits
at neutral while the bot is not driving, so an active slot is the operator's.

    python pso-controller.py                 # auto-detect the pad, relay until Ctrl+C
    python pso-controller.py --slot 0        # name the slot explicitly
    python pso-controller.py --no-sticks     # only buttons and the d-pad

Buttons map exactly as the vpad expects: A/B/X/Y, START, the d-pad, and the triggers to Z and L.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import os
import pathlib
import sys
import threading
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import gamepads                     # noqa: E402

# The app the worker actually registered with. Two app instances can run (the config default 8765 and a
# hand-started 18765); talking to the wrong one returns 504 for every session RPC while the other answers
# normally - measured. GBOX_API overrides it.
BASE = os.environ.get("GBOX_API") or "http://127.0.0.1:8765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
TRACE_DIR = pathlib.Path(r"D:\gBox\pso-ds\bounded")
# The bot stands down while this is fresh (`pso_bounded.OperatorGuard`): the operator always wins.
OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
# One relay only. Two ran at once (one from each Python environment), and the pair produced single key presses exactly
# every --idle-seconds for minutes - input the operator never made, which kept the bot standing down for the whole
# session. With the relays stopped the pad was silent for 35 s, so the duplicates were the source.
RELAY_LOCK = pathlib.Path(r"D:\gBox\pso-ds\pso-controller.lock")
# While the bounded runner holds its lock, the pad's state includes the BOT's own virtual pad. Reading it and forwarding
# it back is a closed loop: the relay saw the bot's taps as "operator input", claimed the pad, and preempted the run that
# produced them - measured as single key presses exactly every --idle-seconds for minutes, which is the bot's own
# cadence. The operator's pad can wait one run.
BOT_LOCK = pathlib.Path(r"D:\gBox\pso-ds\bounded\bounded.lock")

# XInput button bits (xinput.h).
BUTTONS = ((0x1000, "a"), (0x2000, "b"), (0x4000, "x"), (0x8000, "y"),
           (0x0010, "start"), (0x0020, "back"),
           (0x0001, "up"), (0x0002, "down"), (0x0004, "left"), (0x0008, "right"))


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {str(message).encode('ascii', 'replace').decode('ascii')}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=15):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"err": type(exc).__name__}


def live_session() -> str:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    return live[0]["session_id"] if live else ""


def read(slot: int) -> dict | None:
    for row in gamepads.xinput_snapshot([slot]):
        return row
    return None


def simplify(points: list, spacing: float = 4.0) -> list:
    kept = []
    for x, z in points:
        if not kept or math.dist(kept[-1], (x, z)) >= spacing:
            kept.append((round(x, 1), round(z, 1)))
    return kept


def keys_for(state: dict, *, sticks: bool = True, deadzone: float = 0.35) -> set:
    """The vpad keys this pad state means. Sticks are read as directions with a deadzone."""
    keys = set()
    buttons = int(state.get("buttons") or 0)
    for bit, key in BUTTONS:
        if buttons & bit:
            keys.add(key)
    if sticks:
        # Raw XInput axes are -32768..32767; comparing them to a 0..1 deadzone made a 4% stick drift read as a
        # full deflection (measured: lx=1415 latched the relay onto a resting pad as "right+down").
        lx = float(state.get("lx") or 0.0) / 32767.0
        ly = float(state.get("ly") or 0.0) / 32767.0
        if lx <= -deadzone:
            keys.add("left")
        elif lx >= deadzone:
            keys.add("right")
        if ly <= -deadzone:
            keys.add("up")
        elif ly >= deadzone:
            keys.add("down")
    if float(state.get("lt") or 0) > 96:
        keys.add("z")
    if float(state.get("rt") or 0) > 96:
        keys.add("l")
    return keys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="relay the operator's physical pad into the session's virtual pad")
    parser.add_argument("--session", default="")
    parser.add_argument("--slot", type=int, default=-1, help="XInput slot (-1 = auto-detect by activity)")
    parser.add_argument("--hz", type=float, default=60.0)
    parser.add_argument("--no-sticks", action="store_true")
    parser.add_argument("--seconds", type=float, default=3600.0)
    parser.add_argument("--idle-seconds", type=float, default=10.0,
                        help="how long after their last input the operator keeps the pad")
    parser.add_argument("--latch-seconds", type=float, default=900.0,
                        help="how long to wait for the first button press that identifies the operator pad")
    args = parser.parse_args(argv)

    sid = args.session or live_session()
    if not sid:
        log("no live session")
        return 2
    if RELAY_LOCK.exists():
        try:
            holder = json.loads(RELAY_LOCK.read_text(encoding="utf-8")).get("pid")
        except (OSError, ValueError):
            holder = None
        alive = False
        if holder:
            try:
                os.kill(int(holder), 0)
                alive = True
            except OSError:
                alive = False
        if alive:
            log(f"another relay is already running (pid {holder}) - refusing to be the second one")
            return 4
        log(f"taking over a dead relay's lock (pid {holder})")
    RELAY_LOCK.write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
    slot = args.slot
    if slot < 0:
        log("watching for an active pad (press any button on your controller) ...")
        deadline = time.monotonic() + args.latch_seconds
        while time.monotonic() < deadline and slot < 0:
            for row in gamepads.xinput_snapshot():
                state = row if isinstance(row, dict) else {}
                # A button press identifies the pad; a resting stick drift must not (it did once already).
                if int(state.get("buttons") or 0):
                    slot = int(state["slot"])
                    log(f"latched onto pad slot {slot} (button press seen)")
                    break
            if slot < 0:
                time.sleep(0.05)
        if slot < 0:
            log(f"no button press seen in {args.latch_seconds:.0f} s - pass --slot N to force one")
            return 3

    interval = 1.0 / max(args.hz, 1.0)
    held: set = set()
    started = time.monotonic()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trace_path = TRACE_DIR / f"demo-{stamp}.jsonl"
    route_path = TRACE_DIR / f"demo-{stamp}.json"
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace = trace_path.open("w", encoding="utf-8")
    samples: list = []
    stop = threading.Event()

    def record() -> None:
        """Positions at ~8 Hz while the operator drives: the other half of a demonstration trace."""
        while not stop.is_set():
            state = call(f"/api/sessions/{sid}/rpc", {"op": "state", "args": {"player_only": True}}, "POST", 5)
            player = (state or {}).get("player") or {}
            if player.get("x") is not None:
                row = {"t": round(time.monotonic() - started, 3), "keys": sorted(held),
                       "x": round(float(player["x"]), 2), "z": round(float(player["z"]), 2),
                       "room": player.get("room"), "heading": player.get("heading_deg")}
                samples.append(row)
                trace.write(json.dumps(row) + "\n")
            time.sleep(0.12)

    watcher = threading.Thread(target=record, daemon=True, name="demo-recorder")
    watcher.start()
    log(f"relaying XInput slot {slot} -> session {sid} at {args.hz:.0f} Hz "
        f"({'without sticks' if args.no_sticks else 'with sticks'}), recording to {trace_path.name}")
    last_activity = 0.0
    flagged = False
    while time.monotonic() - started < args.seconds:
        if BOT_LOCK.exists():
            # The bot owns the pad: anything on it may be the bot's own input, so forward nothing.
            if flagged:
                try:
                    OPERATOR_FLAG.unlink()
                except OSError:
                    pass
                flagged = False
                log("bot is driving - relay paused")
            time.sleep(0.05)
            continue
        try:
            state = read(slot)
        except Exception as exc:                                   # noqa: BLE001 - a pad read must never end the relay
            log(f"pad read failed: {type(exc).__name__}")
            time.sleep(0.5)
            continue
        if state is None:
            time.sleep(0.5)
            continue
        wanted = keys_for(state, sticks=not args.no_sticks)
        events = []
        for key in wanted - held:
            events.append({"key": key, "down": True})
        for key in held - wanted:
            events.append({"key": key, "down": False})
        if events:
            try:
                call(f"/api/sessions/{sid}/input", {"events": events}, "POST", timeout=5)
            except Exception as exc:                                # noqa: BLE001 - keep the pad alive
                log(f"input post failed: {type(exc).__name__}")
            log("keys " + ", ".join(f"{'+' if event['down'] else '-'}{event['key']}" for event in events))
            held = wanted
            last_activity = time.monotonic()
        # The bot yields while the operator is playing, through the same flag the human relay always used.
        if wanted or (time.monotonic() - last_activity) < args.idle_seconds:
            try:
                OPERATOR_FLAG.parent.mkdir(parents=True, exist_ok=True)
                OPERATOR_FLAG.write_text("operator pad relay", encoding="ascii")
                if not flagged:
                    log("operator owns the pad - the bot will stand down")
                    flagged = True
            except OSError:
                pass
        elif flagged:
            try:
                OPERATOR_FLAG.unlink()
            except OSError:
                pass
            log("operator idle - the bot may resume")
            flagged = False
        time.sleep(interval)
    stop.set()
    try:
        OPERATOR_FLAG.unlink()
    except OSError:
        pass
    watcher.join(timeout=3.0)
    trace.close()
    if held:
        call(f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": False} for key in held]}, "POST")
    points = [(row["x"], row["z"]) for row in samples]
    path_length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    route = {"stamp": stamp, "session": sid, "slot": slot, "seconds": round(time.monotonic() - started, 1),
             "samples": len(samples), "path_length": round(path_length, 1),
             "rooms": sorted({row["room"] for row in samples if row.get("room") is not None}),
             "waypoints": simplify(points), "trace": str(trace_path)}
    route_path.write_text(json.dumps(route, indent=1), encoding="utf-8")
    log(f"recorded {len(samples)} samples, path {path_length:.0f} units, rooms {route['rooms']}")
    log(f"route -> {route_path}")
    try:
        RELAY_LOCK.unlink()
    except OSError:
        pass
    log("relay stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
