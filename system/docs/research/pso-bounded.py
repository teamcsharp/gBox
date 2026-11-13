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
import math
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
        holder = None
        try:
            holder = json.loads(LOCK.read_text(encoding="utf-8")).get("pid")
        except (OSError, ValueError):
            holder = None
        alive = False
        if holder:
            try:
                os.kill(int(holder), 0)              # query only: signal 0 never delivers on Windows
                alive = True
            except OSError:
                alive = False
        if age < LOCK_STALE_S and alive:
            log(f"refusing to start: another bounded runner holds the lock ({age:.0f}s old, pid {holder})")
            return False
        if age < LOCK_STALE_S and holder is None:
            # A lock written before the pid was recorded cannot name its holder; it is a crashed run, and refusing
            # forever on it is worse than the small risk of two starts racing (the second write wins).
            log(f"taking over a lock with no recorded pid ({age:.0f}s old)")
        log(f"taking over the lock from a dead runner (pid {holder}, {age:.0f}s old)")
    LOCK.write_text(json.dumps({"pid": os.getpid(), "at": time.time(), "by": "pso-bounded"}), encoding="utf-8")
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


def simplify_trace(points: list, spacing: float = 8.0) -> list:
    kept = []
    for x, z in points:
        if not kept or math.dist(kept[-1], (x, z)) >= spacing:
            kept.append((round(x, 1), round(z, 1)))
    return kept


class OffsetRouter:
    """Route in the collision mesh's frame while the game reports world coordinates.

    A collision file holds several areas' geometry in one frame; each area's world position differs from it by a
    constant. Measured for Forest 1: rooms 4 and 8 sit at world = file + (450, -325), which no route could cross before
    because the query point was 300 units outside the mesh. This wrapper maps the query into the file's frame and the
    waypoints back out.
    """

    def __init__(self, router, offset) -> None:
        self.router = router
        self.offset = (float(offset[0]), float(offset[1]))
        self.safe = getattr(router, "safe", set())

    def route(self, start, goal):
        dx, dz = self.offset
        points = self.router.route((start[0] + dx, start[1] + dz), (goal[0] + dx, goal[1] + dz))
        return [(x - dx, z - dz) for x, z in (points or [])]


class TraceRouter:
    """A router that replays one recorded path: the operator's demonstration, verbatim.

    No map, no A*: `route()` returns the trace's waypoints from the nearest one to the current position, so the
    follower walks the same line the operator walked. This is the "monkey-see-monkey-do" path that avoids every failure
    of the decoded collision grid (false-positive cells, doors that are walls, rooms in separate components).
    """

    def __init__(self, waypoints: list) -> None:
        self.waypoints = [tuple(point) for point in waypoints]
        self.safe = set()

    def route(self, start: tuple, goal: tuple) -> list:
        if not self.waypoints:
            return []
        nearest = min(range(len(self.waypoints)),
                      key=lambda index: math.dist(start, self.waypoints[index]))
        return self.waypoints[nearest:]


class DoorState:
    """Which doors have been crossed and which have been tried and blocked.

    No door exposes a readable open/closed field (`+0xAC` is 0 either way), so the only honest source is an attempt:
    a crossing through a door's position marks it open, and a no-close failure on that door marks it closed. Both are
    ledger events, so the belief is always backed by something that happened.
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

    def put(self, sid: str, ptr: str, state: str) -> None:
        if not ptr:
            return
        self.data.setdefault(sid, {})[str(ptr)] = str(state)
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
    doors = DoorState(OUT / "door-state.json")
    known_doors = doors.get(sid)
    policy = B.ProgressionPolicy(door_state=known_doors)
    bound_mode = B.RunMode.ASSISTED if args.assisted else B.RunMode.NORMAL

    # Calibrate the input primitives BEFORE choosing a motion model, which is the lesson the handoff records most
    # sharply: every steering loop that was written before the primitives were measured produced the same zigzag.
    calibration = None
    cache_path = OUT / "calibration-cache.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    cached = cache.get(sid) if isinstance(cache.get(sid), dict) else None
    if not args.no_calibrate and cached and (time.time() - float(cached.get("at") or 0)) < args.calibration_ttl:
        calibration = B.Calibration(effects={k: tuple(v) for k, v in (cached.get("effects") or {}).items()},
                                    speed=float(cached.get("speed") or 0.0),
                                    turn=dict(cached.get("turn") or {}),
                                    model=str(cached.get("model") or "vector"), samples=list(cached.get("samples") or []))
        log(f"calibration: reusing the one from {time.time() - float(cached.get('at') or 0):.0f}s ago "
            f"({calibration.model}); calibration taps move the character, so it is not repeated every run")
    elif not args.no_calibrate:
        calibration = B.calibrate(world, ledger=ledger, clock=clock)
        table = calibration.as_dict()
        cache[sid] = {"at": time.time(), **table}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
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
    # `hill` is the default because the frame cannot be inferred reliably: measured at 1,050 units of path for 105 of
    # progress with the frame-relative rule. It infers nothing - it credits the key that closed distance and switches
    # when one stops paying.
    if args.motion == "hill":
        motion = B.HillClimbMotion(arrive=arrive)
    elif args.motion == "wall":
        # Close the distance, step sideways when a wall stops it: for rooms the decoded map does not cover.
        motion = B.WallFollowMotion(arrive=arrive,
                                    effects=(calibration.effects if calibration is not None else None),
                                    cal_heading=(calibration.heading if calibration is not None else 0.0))
    elif args.motion == "commit":
        # Commit to a heading, learn each key's direction live, slide when blocked: for long walks in unmapped rooms.
        motion = B.CommitMotion(arrive=arrive)
    elif args.motion == "vector":
        motion = B.VectorMotion(arrive=arrive, primitive="tap")
        if calibration is not None:
            motion.seed(calibration.effects, speed=calibration.speed or None)
    else:
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
        cells = row["cells"]
        if args.carve:
            # The disc mesh has every door closed, so a doorway is wall in the static grid and A* goes around the
            # room instead of through the door. Carve a passage at every gate the session currently reports.
            state = world.observe() or {}
            # Only gates this session has already crossed are carved. Carving every gate also opens false passages
            # through *closed* doors, and a route then leads into a wall: measured, the character pinned 20 units short
            # of a door it could not enter. A doorway that is really open is already walkable in the raw mesh, so the
            # raw grid needs no help until a crossing proves otherwise.
            known = doors.get(sid)
            gates = [(float(e["x"]), float(e["z"])) for e in (state.get("entities") or [])
                     if str(e.get("class")) in B.DOOR_CLASSES and e.get("x") is not None
                     and known.get(str(e.get("ptr"))) == "open"]
            cells = B.carve_doorways(cells, gates, radius=args.carve_radius, cell=2.5)
            log(f"carved {len(gates)} known-open doorway(s) into the grid")
        router = MapRouter(sorted(cells))
        log(f"routing over {name}: {len(row['cells'])} safe cells")
        # A collision file is one area's frame. Measured today: room 10 sits 1.4 units from the nearest grid cell,
        # while rooms 2, 4, 5, 8, 11 are 190-460 units outside it - a route there snaps to a cell across the level and
        # the follower walks into walls. When there is no coverage at the character, say so and move directly instead.
        here = (world.observe() or {}).get("player") or {}
        offset = (0.0, 0.0)
        if here.get("x") is not None:
            room = str(here.get("room"))
            offsets_path = pathlib.Path(r"D:\gBox\pso-ds\area-offsets.json")
            try:
                table = json.loads(offsets_path.read_text(encoding="utf-8"))
                per_file = table.get(name) or {}
                candidates = [tuple(float(v) for v in pair) for pair in (per_file.get("offsets") or [(0.0, 0.0)])]
            except (OSError, ValueError, KeyError, TypeError):
                candidates = [(0.0, 0.0)]
            # The area boundary is not the room boundary - room 4 alone needs two offsets - so pick the one that lands
            # the character nearest walkable ground instead of trusting the room number.
            def mapped_distance(pair):
                px = float(here["x"]) + pair[0]
                pz = float(here["z"]) + pair[1]
                return min(math.hypot(px - cell[0], pz - cell[1]) for cell in cells)
            offset = min(candidates, key=mapped_distance)
            if offset != (0.0, 0.0):
                router = OffsetRouter(router, offset)
                log(f"room {room} sits at file offset {tuple(int(v) for v in offset)}: routing in the mesh's frame")
            nearest = min(math.dist((float(here["x"]) + offset[0], float(here["z"]) + offset[1]), cell)
                          for cell in cells)
            if nearest > 30.0:
                log(f"no map coverage here: nearest grid cell is {nearest:.0f} units away "
                    f"(this room is outside {name}'s frame) - moving directly, without a route")
                router = None

    if mode == "sweep":
        # Serpentine the room. A bounded area has an exit somewhere on its edge, and random roaming does not find it:
        # measured, 200 s of play in Forest 1 room 16 bounced inside x 460-590, z 380-500 without a room change.
        clock2 = clock
        motion = B.CommitMotion(arrive=15.0)
        player = (world.observe(player_only=True) or {}).get("player") or {}
        px, pz = float(player.get("x") or 0), float(player.get("z") or 0)
        room = player.get("room")
        half, step = float(args.half), float(args.spacing)
        rows, z = [], pz - half
        left = True
        while z <= pz + half:
            xs = range(int(px - half), int(px + half) + 1, int(step))
            for x in (xs if left else reversed(list(xs))):
                rows.append((float(x), float(z)))
            left = not left
            z += step
        log(f"sweep room {room}: {len(rows)} waypoints around ({px:.0f},{pz:.0f}) +/-{half:.0f}")
        for index, point in enumerate(rows):
            deadline = time.monotonic() + float(args.per_point)
            while time.monotonic() < deadline:
                current = ((world.observe(player_only=True) or {}).get("player")) or {}
                if current.get("room") != room:
                    log(f"  EXIT: room {room} -> {current.get('room')} near {point}")
                    world.release()
                    release_ownership()
                    return 0
                here = (float(current.get("x") or 0), float(current.get("z") or 0))
                if math.dist(here, point) <= 15.0:
                    break
                action = motion.step({"x": here[0], "z": here[1]}, point, "sweep")
                if action is None:
                    break
                world.act(action, time.monotonic() + 2.0)
                clock2.sleep(0.10)
            if index % 6 == 0:
                current = ((world.observe(player_only=True) or {}).get("player")) or {}
                log(f"  sweep {index}/{len(rows)} at ({float(current.get('x') or 0):.0f},"
                    f"{float(current.get('z') or 0):.0f})")
        log("sweep finished without a room change")
        world.release()
        release_ownership()
        return 0

    if mode == "climb":
        # Follow rising ground: the forest has a basin the character slides into, and a 2D motion cannot walk up the
        # cliff to the doors. Probing every key and taking the one that raises y climbed from y 6.9 to 22.7 live.
        target_y = float(args.to_height)
        for step in range(int(args.max_steps)):
            player = (world.observe(player_only=True) or {}).get("player") or {}
            if player.get("y") is None or float(player["y"]) >= target_y:
                log(f"climbed to y {float(player.get('y') or 0):.1f} at "
                    f"({float(player.get('x') or 0):.0f},{float(player.get('z') or 0):.0f})")
                break
            best = None
            for key in B.DIRECTIONS:
                before = ((world.observe(player_only=True) or {}).get("player") or {})
                world.act(B.press(key, "climb probe"), time.monotonic() + 3.0)
                clock.sleep(0.08)
                after = ((world.observe(player_only=True) or {}).get("player") or {})
                dy = float(after.get("y") or 0) - float(before.get("y") or 0)
                if best is None or dy > best[0]:
                    best = (dy, key)
            if best is None or best[0] < 0.2:
                log(f"no higher ground from y {float(player.get('y') or 0):.1f}")
                break
            for _ in range(2):
                world.act(B.press(best[1], "climb"), time.monotonic() + 3.0)
                clock.sleep(0.06)
            if step % 3 == 0:
                player = (world.observe(player_only=True) or {}).get("player") or {}
                log(f"  climb: y {float(player.get('y') or 0):.1f} "
                    f"at ({float(player.get('x') or 0):.0f},{float(player.get('z') or 0):.0f})")
        world.release()
        release_ownership()
        return 0

    if mode == "walk":
        target = tuple(args.to) if args.to is not None else (0.0, 0.0)
        # No policy: the objective is the point. The same bounded tick still issues the action, so the walk cannot
        # hold the loop, and the watchdog still recovers a wedge one action at a time. With --map the point is
        # pursued along the decoded collision grid's waypoints (the city railing is why a straight line is not enough).
        if args.route_file:
            rows = [json.loads(line) for line in pathlib.Path(args.route_file).read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            points = [(float(row["x"]), float(row["z"])) for row in rows if row.get("x") is not None]
            waypoints = simplify_trace(points, args.trace_spacing)
            if len(waypoints) < 2:
                log(f"trace {args.route_file} has {len(waypoints)} usable waypoint(s) - nothing to replay")
                world.release()
                release_ownership()
                return 4
            target = waypoints[-1]
            router = TraceRouter(waypoints)
            log(f"replaying {len(waypoints)} waypoints from {pathlib.Path(args.route_file).name} "
                f"ending at {target}")
        walk_policy = _FixedTarget(policy, target, "door" if args.through else "walk")
        if router is not None:
            walk_policy = B.RoutedPolicy(walk_policy, router, arrive=10.0)
        automaton = B.Automaton(
            world, ledger=ledger, clock=clock, operator=operator, mode=bound_mode,
            motion=motion, policy=walk_policy,
            # A walk may have to go around a plaza railing for a minute before the distance improves; the 20 s
            # default ended runs mid-detour ("walk coordinate not closed for 20s" at (190,322) while still moving).
            # The watchdog's net-stall detector is what catches a genuinely stuck character now.
            bounds=B.Bounds(max_objective_ticks=10_000, max_no_close_s=60.0),
            watchdog=B.Watchdog(stall_s=20.0, max_recoveries=4),
            flag_address=None)
    else:
        play_policy = policy if router is None else B.RoutedPolicy(policy, router, arrive=10.0)
        automaton = B.Automaton(
            world, ledger=ledger, clock=clock, operator=operator, mode=bound_mode,
            motion=motion, policy=play_policy,
            # An objective can be hundreds of units away in these rooms: a 20 s no-improvement clock failed a switch
        # objective at 344 units while the character was still travelling. 45 s, with the net-stall watchdog for a
        # body that is genuinely pinned.
        bounds=B.Bounds(max_no_close_s=45.0), watchdog=B.Watchdog(stall_s=20.0, max_recoveries=4),
            flag_address=STAGE_FLAGS, flag_length=576,
            fixture_path=OUT / f"failure-{mode}-{stamp}.json")

    floors = FloorReads(world)
    switches = SwitchState(OUT / "switch-state.json")
    automaton.pressed.update(switches.get(sid))
    log(f"{mode}: session {sid}, ledger {ledger_path.name}, floor {floors.floor()}, "
        f"mode={bound_mode.value}, {len(automaton.pressed)} verified switch(es), "
        f"{len(known_doors)} door state(s) remembered, {args.seconds:.0f}s")
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
                distance = B.math.hypot(target[0] - float(player.get("x") or 0),
                                        target[1] - float(player.get("z") or 0))
                if args.through:
                    # A doorway crossing is the evidence, and it needs both parts: the room changed AND the character
                    # is at the door. The room value alone flickers at boundaries without any movement (measured: room
                    # 10 -> 5 in one tick, 215 units from the door).
                    if player.get("room") != start_room and distance <= 15.0:
                        log(f"  crossed the doorway at {tuple(target)}: room {start_room} -> "
                            f"{player.get('room')} after {automaton.stats()['ticks']} ticks")
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
        objective = automaton.last_objective
        if objective is not None and objective.kind == "door":
            final_state = world.observe() or {}
            door_ptr = objective.ptr
            if not door_ptr:
                # A coordinate walk has no entity pointer; resolve it to the door it just crossed so the state sticks.
                near = sorted(
                    ((math.dist((float(e["x"]), float(e["z"])), objective.point), str(e.get("ptr")))
                     for e in (final_state.get("entities") or [])
                     if str(e.get("class")) in B.DOOR_CLASSES and e.get("x") is not None),
                    key=lambda pair: pair[0])
                if near and near[0][0] <= 15.0:
                    door_ptr = near[0][1]
            objective = B.Objective(objective.rank, objective.kind, objective.point, objective.distance,
                                    objective.cls, door_ptr, objective.hp, objective.why,
                                    target_distance=objective.target_distance)
            final_player = (final_state.get("player") or {})
            final_room = final_player.get("room")
            final_position = (float(final_player.get("x") or 0), float(final_player.get("z") or 0)) \
                if final_player.get("ptr") else None
            if "not closed" in (automaton.stopped or "") or "stalled" in (automaton.stopped or ""):
                doors.put(sid, objective.ptr, "closed")
                log(f"  door {objective.ptr} marked closed (could not be crossed)")
            elif final_room != start_room and final_position is not None and math.dist(final_position, objective.point) <= 15.0:
                doors.put(sid, objective.ptr, "open")
                log(f"  door {objective.ptr} marked open (room {start_room} -> {final_room}, "
                    f"at {math.dist(final_position, objective.point):.0f} units)")
        release_ownership()

    stats = automaton.stats()
    if mode == "walk":
        player = (world.observe() or {}).get("player") or {}
        left = B.math.hypot(float(target[0]) - float(player.get("x") or 0),
                            float(target[1]) - float(player.get("z") or 0))
        stats["final_distance"] = round(left, 1)
        stats["target"] = list(target)
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
    sweep = sub.add_parser("sweep", help="serpentine the current room to find its exits")
    sweep.add_argument("--half", type=float, default=150.0)
    sweep.add_argument("--spacing", type=float, default=45.0)
    sweep.add_argument("--per-point", type=float, default=18.0)
    sweep.add_argument("--session", default="")
    sweep.add_argument("--motion", default="commit")
    sweep.add_argument("--seconds", type=float, default=600.0)
    sweep.add_argument("--map", default="")
    sweep.add_argument("--map-name", default="")
    sweep.add_argument("--carve", action="store_true", default=False)
    sweep.add_argument("--no-carve", dest="carve", action="store_false")
    sweep.add_argument("--carve-radius", type=float, default=8.0)
    sweep.add_argument("--trace-spacing", type=float, default=8.0)
    sweep.add_argument("--calibration-ttl", type=float, default=900.0)
    sweep.add_argument("--no-calibrate", action="store_true")
    sweep.add_argument("--assisted", action="store_true")

    climb = sub.add_parser("climb", help="follow rising ground until the character reaches a height")
    climb.add_argument("--to-height", type=float, default=21.0)
    climb.add_argument("--max-steps", type=int, default=24)
    climb.add_argument("--session", default="")
    climb.add_argument("--assisted", action="store_true")
    climb.add_argument("--no-calibrate", action="store_true")
    climb.add_argument("--calibration-ttl", type=float, default=900.0)
    climb.add_argument("--motion", default="commit", choices=("hill", "wall", "commit", "vector", "relative"))
    climb.add_argument("--seconds", type=float, default=300.0)
    climb.add_argument("--map", default="")
    climb.add_argument("--map-name", default="")
    climb.add_argument("--carve", action="store_true", default=False)
    climb.add_argument("--no-carve", dest="carve", action="store_false")
    climb.add_argument("--carve-radius", type=float, default=8.0)
    climb.add_argument("--trace-spacing", type=float, default=8.0)

    walk = sub.add_parser("walk", help="drive to one coordinate with bounded controller input")
    walk.add_argument("--to", type=float, nargs=2, metavar=("X", "Z"),
                      help="target coordinate (omit when replaying --route-file)")
    walk.add_argument("--route-file", default="",
                      help="replay a recorded demonstration trace (.jsonl) instead of using the map")
    walk.add_argument("--through", action="store_true",
                      help="walk through the coordinate (a doorway) instead of stopping at it")
    play = sub.add_parser("play", help="run the progression policy")
    for name, item in (("walk", walk), ("play", play)):
        item.add_argument("--seconds", type=float, default=60.0)
        item.add_argument("--session", default="")
        item.add_argument("--map", default="", help="decoded collision grid to route over")
        item.add_argument("--carve", action="store_true", default=False,
                          help="open a grid passage at gates the session has actually crossed (default off)")
        item.add_argument("--no-carve", dest="carve", action="store_false")
        item.add_argument("--carve-radius", type=float, default=8.0)
        item.add_argument("--trace-spacing", type=float, default=8.0,
                          help="waypoint spacing when replaying a recorded trace")
        item.add_argument("--motion", default="hill", choices=("hill", "wall", "commit", "vector", "relative"),
                          help="movement controller: hill climbs measured gains, vector/relative infer a frame")
        item.add_argument("--map-name", default="", help="substring of the grid entry to use (e.g. forest01)")
        item.add_argument("--calibration-ttl", type=float, default=900.0,
                          help="seconds a cached calibration stays valid (it moves the character)")
        item.add_argument("--no-calibrate", action="store_true",
                          help="skip the one-tap-per-key calibration (it costs about five seconds)")
        item.add_argument("--assisted", action="store_true",
                          help="label the run as assisted: never evidence for a normal-play gate")
    args = parser.parse_args(argv)
    if getattr(args, "mode", None) == "walk" and not args.route_file and args.to is None:
        parser.error("walk needs --to X Z or --route-file")
    return run(args.mode, args)


if __name__ == "__main__":
    raise SystemExit(main())
