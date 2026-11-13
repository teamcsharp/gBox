"""bounded - the cancellable, evidence-writing replacement for `endless.py`'s play loop.

`endless.py` decides and moves inside one non-yielding loop: a single branch can walk for minutes, and the only
record of what happened is a log line. This driver inverts that. Every action is one bounded tick issued by
`gbox.pso_bounded.Automaton`, and every tick writes a hash-chained ledger line with the pre-state, the action and
the post-state, so a claim like "the switch opened the door" has a trace behind it or is not made.

Two modes, both using the same bounded tick:

    walk   drive toward one coordinate with controller input only, and report the distance actually closed
    play   the full progression policy: warp > live enemy wave > switch > door > optional container

Usage:
    python pso-bounded.py walk --to 120,-40 --seconds 45
    python pso-bounded.py play --seconds 90

Nothing here writes memory. `--assisted` exists only to label a run that somebody else has already modified; it is
recorded as `mode=assisted` in every ledger line and is never evidence for a normal-play gate.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_bounded as B                     # noqa: E402
from gbox import pso_evidence as E                    # noqa: E402

BASE = "http://127.0.0.1:18765"
TOKEN_PATH = pathlib.Path(r"C:\_tools\gBox\system\gbox-data\api_token")
OUT = pathlib.Path(r"D:\gBox\pso-ds\bounded")
OPERATOR_FLAG = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
LOCK = OUT / "bounded.lock"
LOCK_STALE_S = 30.0
STAGE_FLAGS = 0x80515CC8
FLOOR_POINTER = 0x805D5FC0


def log(message: str) -> None:
    safe = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[{time.strftime('%H:%M:%S')}] {safe}", flush=True)


def token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path, payload=None, method="GET", timeout=60):
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


def claim_ownership() -> bool:
    """One bounded runner at a time. A stale lock is a dead runner, not a live one."""
    OUT.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < LOCK_STALE_S:
            log(f"refusing to start: another bounded runner holds the lock ({age:.0f}s old)")
            return False
    LOCK.write_text(json.dumps({"pid": None, "at": time.time(), "by": "pso-bounded"}), encoding="utf-8")
    return True


def release_ownership() -> None:
    try:
        LOCK.unlink()
    except OSError:
        pass


class FloorReads:
    """Small wrapper that reads the two native addresses the evidence needs, and nothing else."""

    def __init__(self, world) -> None:
        self.world = world

    def floor(self) -> int | None:
        raw = self.world.read(FLOOR_POINTER, 4)
        return int.from_bytes(raw, "big") if len(raw) == 4 else None


class SwitchState:
    """Verified switches, remembered across runs.

    A fresh `Automaton` starts with an empty `pressed` map, so a new run walks back to the switch it already verified
    and presses it again - measured: the Forest 1 door key was re-pressed three times, changed nothing (its bit was
    already set) and the run ended on that false miss. The verified set belongs to the session, not to the process.
    """

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.data = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def get(self, sid: str) -> dict:
        return dict(self.data.get(sid) or {})

    def put(self, sid: str, pressed: dict) -> None:
        self.data[sid] = {str(ptr): float(when) for ptr, when in pressed.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")


def run(mode: str, args) -> int:
    sid = args.session or live_session()
    if not sid:
        log("no live session; start the game (or let endless.py launch it) and retry")
        return 2
    if not claim_ownership():
        return 3
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    ledger_path = OUT / f"{mode}-{stamp}.jsonl"
    summary_path = OUT / f"{mode}-{stamp}-summary.json"

    world = B.SessionWorld(sid, call, worker=sid.split("-")[0])
    ledger = E.Ledger(ledger_path, run=f"{mode}-{stamp}")
    clock = B.MonotonicClock()
    operator = B.OperatorGuard(OPERATOR_FLAG)
    policy = B.ProgressionPolicy()
    bound_mode = B.RunMode.ASSISTED if args.assisted else B.RunMode.NORMAL

    # Calibrate the input primitives BEFORE choosing a motion model, which is the lesson the handoff records most
    # sharply: every steering loop that was written before the primitives were measured produced the same zigzag.
    calibration = None
    if not args.no_calibrate:
        calibration = B.calibrate(world, ledger=ledger, clock=clock)
        table = calibration.as_dict()
        log(f"calibration: model={calibration.model} speed={calibration.speed} "
            f"effects={table['effects']} turn={table['turn_deg']}")
    # Movement is the calibrated TAP, steered in the character's own frame. Measured live on 2026-11-13
    # (pso-calibrate.py, 4 samples per key, settling after each action): every direction tap moved 7.8-8.0 units,
    # while a 0.30 s hold moved 38.9 units because the release job lands about a second after the down job. The
    # frame matters as much as the primitive: a world-frame key table goes stale as the character turns (measured:
    # 138 taps around the plaza ending 244 units from a 230-unit target), so facing comes from the last movement.
    arrive = 6.0 if mode == "walk" else 8.0
    turns = {}
    if calibration is not None:
        turns = {key: value for key, value in calibration.turn.items() if abs(value) >= 12.0}
    motion = B.RelativeTapMotion(arrive=arrive, turn_deg=turns)

    router = None
    if args.map:
        sys.path.insert(0, r"C:\_tools\gBox\.tmp")
        from forest_route import MapRouter
        grid = json.loads(pathlib.Path(args.map).read_text(encoding="utf-8"))
        name = args.map_name or next(iter(grid))
        if args.map_name:
            name = next((key for key in grid if args.map_name in key), name)
        row = grid[name]
        router = MapRouter(row["cells"])
        log(f"routing over {name}: {len(row['cells'])} safe cells")

    if mode == "walk":
        target = tuple(args.to)
        # No policy: the objective is the point. The same bounded tick still issues the action, so the walk cannot
        # hold the loop, and the watchdog still recovers a wedge one action at a time. With --map the point is
        # pursued along the decoded collision grid's waypoints (the city railing is why a straight line is not enough).
        walk_policy = _FixedTarget(policy, target, "door" if args.through else "walk")
        if router is not None:
            walk_policy = B.RoutedPolicy(walk_policy, router, arrive=max(arrive, 10.0))
        automaton = B.Automaton(
            world, ledger=ledger, clock=clock, operator=operator, mode=bound_mode,
            motion=motion, policy=walk_policy,
            bounds=B.Bounds(max_objective_ticks=10_000), watchdog=B.Watchdog(stall_s=20.0, max_recoveries=4),
            flag_address=None)
    else:
        play_policy = policy if router is None else B.RoutedPolicy(policy, router, arrive=max(arrive, 10.0))
        automaton = B.Automaton(
            world, ledger=ledger, clock=clock, operator=operator, mode=bound_mode,
            motion=motion, policy=play_policy,
            bounds=B.Bounds(), watchdog=B.Watchdog(stall_s=20.0, max_recoveries=4),
            flag_address=STAGE_FLAGS, flag_length=576,
            fixture_path=OUT / f"failure-{mode}-{stamp}.json")

    floors = FloorReads(world)
    switches = SwitchState(OUT / "switch-state.json")
    automaton.pressed.update(switches.get(sid))
    log(f"{mode}: session {sid}, ledger {ledger_path.name}, floor {floors.floor()}, "
        f"mode={bound_mode.value}, {len(automaton.pressed)} verified switch(es) remembered, {args.seconds:.0f}s")
    started = time.monotonic()
    last_report = 0.0
    start_room = ((world.observe() or {}).get("player") or {}).get("room")
    try:
        while time.monotonic() - started < args.seconds and not automaton.stopped:
            loop_started = time.monotonic()
            tick = automaton.tick()
            if os.environ.get("PSO_TIMING"):
                phases = getattr(automaton, "phases", {})
                log(f"  tick {tick.index}: {time.monotonic() - loop_started:.3f}s "
                    f"(action {tick.duration:.3f}s) {tick.outcome} {tick.action} | {tick.note[:40]} | "
                    f"observe {phases.get('observe', 0):.3f} plan {phases.get('plan', 0):.3f} "
                    f"act {phases.get('act', 0):.3f} after {phases.get('after', 0):.3f}")
            if tick.outcome in ("stall", "failed", "preempted"):
                log(f"  tick {tick.index}: {tick.outcome} - {tick.note}")
            if mode == "walk":
                player = (world.observe() or {}).get("player") or {}
                distance = B.math.hypot(args.to[0] - float(player.get("x") or 0),
                                        args.to[1] - float(player.get("z") or 0))
                if args.through:
                    # A doorway crossing is the evidence: stop when the room settles into a different value.
                    if player.get("room") != start_room:
                        log(f"  crossed a doorway: room {start_room} -> {player.get('room')} after "
                            f"{automaton.stats()['ticks']} ticks")
                        break
                elif distance <= arrive:
                    log(f"  arrived within {arrive:.0f} units after {automaton.stats()['ticks']} ticks")
                    break
            if time.monotonic() - last_report > 10.0:
                last_report = time.monotonic()
                stats = automaton.stats()
                player = (world.observe() or {}).get("player") or {}
                log(f"  t+{time.monotonic() - started:5.0f}s ticks {stats['ticks']:4d} "
                    f"at ({float(player.get('x') or 0):.0f},{float(player.get('z') or 0):.0f}) "
                    f"progress {stats['progress_kind']} ({stats['progress_age']:.0f}s ago) "
                    f"stalls {stats['stalls']} overruns {stats['overruns']}")
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        world.release()
        switches.put(sid, automaton.pressed)
        release_ownership()

    stats = automaton.stats()
    if mode == "walk":
        player = (world.observe() or {}).get("player") or {}
        left = B.math.hypot(float(args.to[0]) - float(player.get("x") or 0),
                            float(args.to[1]) - float(player.get("z") or 0))
        stats["final_distance"] = round(left, 1)
        stats["target"] = list(args.to)
    ok, why = ledger.verify()
    summary = {"mode": mode, "session": sid, "run_mode": bound_mode.value, "started": stamp,
               "seconds": args.seconds, "stats": stats, "ledger": str(ledger_path),
               "ledger_verified": ok, "ledger_verify_note": why,
               "floor": floors.floor(), "failures": automaton.failures}
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    log(f"done: {json.dumps(stats, sort_keys=True)}")
    log(f"ledger {why} -> {ledger_path}")
    if automaton.stopped:
        log(f"stopped: {automaton.stopped}")
        return 1
    return 0


class _FixedTarget:
    """A policy whose only objective is one coordinate: the walk test must not be distracted by loot.

    `kind="door"` makes the automaton walk *through* the coordinate (the door branch aims past the point) instead of
    stopping at it, which is how a doorway crossing is tested.
    """

    def __init__(self, policy: B.ProgressionPolicy, point: tuple, kind: str = "walk") -> None:
        self.policy = policy
        self.point = point
        self.kind = kind

    def choose(self, snap, now, *, pressed=None, avoid=None):
        player = snap.get("player") or {}
        distance = B.math.hypot(float(self.point[0]) - float(player.get("x") or 0),
                                float(self.point[1]) - float(player.get("z") or 0))
        return B.Objective(0, self.kind, (float(self.point[0]), float(self.point[1])), distance,
                           "coordinate", "", None, "walk target")

    def note(self, kind: str, progressed: bool) -> None:
        self.policy.note(kind, progressed)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="bounded PSO controller")
    sub = parser.add_subparsers(dest="mode", required=True)
    walk = sub.add_parser("walk", help="drive to one coordinate with bounded controller input")
    walk.add_argument("--to", type=float, nargs=2, required=True, metavar=("X", "Z"))
    walk.add_argument("--through", action="store_true",
                      help="walk through the coordinate (a doorway) instead of stopping at it")
    play = sub.add_parser("play", help="run the progression policy")
    for name, item in (("walk", walk), ("play", play)):
        item.add_argument("--seconds", type=float, default=60.0)
        item.add_argument("--session", default="")
        item.add_argument("--map", default="", help="decoded collision grid to route over")
        item.add_argument("--map-name", default="", help="substring of the grid entry to use (e.g. forest01)")
        item.add_argument("--no-calibrate", action="store_true",
                          help="skip the one-tap-per-key calibration (it costs about five seconds)")
        item.add_argument("--assisted", action="store_true",
                          help="label the run as assisted: never evidence for a normal-play gate")
    args = parser.parse_args(argv)
    return run(args.mode, args)


if __name__ == "__main__":
    raise SystemExit(main())
