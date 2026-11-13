"""A bounded, cancellable controller for the PSO autoplayer.

Why this module exists
----------------------
`system/docs/research/pso-endless.py` is a single procedural loop: `route_walk` may walk twelve legs inside one
iteration, `walk_to` up to 40 steps, and the interaction branch runs *before* the stuck counter, so a wedged
character repeats a walking instruction for minutes at a time. Measured before this was written: the position
unchanged at `(487, 0)` for **180 seconds** while the log repeated `walking to TLazerFenceSw 170 -> 194 units`, and
a later log line `walked 30 -> 73 units` followed by `unstick: up freed it`. A branch that can hold the loop for
minutes is not a controller; it is a script that cannot be interrupted.

The mandate (`PSO_ENGINEERING_AND_AUTOPLAY_RECOVERY.md`, sections 6, 8 and 9) asks for the opposite shape:

* **one bounded action per tick**, with a wall-clock deadline and a cancellation token;
* **a watchdog that runs before every branch**, independent of what the branch is doing;
* **operator takeover checked before every input**, with the pad released on takeover;
* **no silent looping**: after bounded retries the tick loop stops and writes a failure fixture;
* **objective progress, not movement**, as the acceptance signal, and *evidence* as the product.

This module is that scheduler plus the policy needed to exercise it. It is deliberately ignorant of PSO's memory
layout: a `World` adapter supplies snapshots and applies actions, so the same controller can be driven by the live
session channel (`SessionWorld`), by a recorded trace, or by a simulated world in tests.

What it will not do
-------------------
It never writes memory. The assisted auto-unlock is a separate, explicitly-labelled feature in the live runner; a
run in `RunMode.ASSISTED` is marked in every ledger line and is not evidence for the normal-play gates.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .pso_evidence import Ledger, diff, failure_fixture, snapshot, with_flags

#: The buttons this controller may press. Anything else is a bug, not an experiment.
KEYS = ("a", "b", "x", "y", "start", "up", "down", "left", "right")
DIRECTIONS = ("up", "down", "left", "right")


class RunMode(Enum):
    NORMAL = "normal"          # controller inputs only; admissible as gate evidence
    ASSISTED = "assisted"      # anything else (RAM writes, warps) happened; never gate evidence


# ---------------------------------------------------------------------------------------------------------------------
# Actions and their bounds
# ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Bounds:
    """Hard ceilings. A tick that exceeds them is a defect, and the controller records the overrun."""
    action_s: float = 0.5        # section 9's initial engineering target for one input hold
    # The tick ceiling is calibrated from the control plane, not guessed: a `session_op send_input` job costs ~1.0 s
    # of queue latency (measured 0.53-1.22 s over 20 jobs on this host) and a hold needs two jobs (down, release), so
    # a normal live tick is 2.1-2.5 s. 3.0 s is therefore the ceiling, and anything beyond it is a real defect.
    tick_s: float = 3.0
    wait_s: float = 0.25         # a deliberate no-input tick (combo gap, operator grace)
    max_recoveries: int = 4      # watchdog recoveries before a failure fixture
    hard_progress_s: float = 300.0      # no room/HP/flag progress for this long is a failure, not a slow room
    max_objective_ticks: int = 150      # legacy tick bound, kept for callers that pass it
    max_objective_s: float = 120.0      # seconds one objective may consume without progress before escalating
    max_no_close_ticks: int = 40        # legacy tick bound, kept for callers that pass it
    max_no_close_s: float = 20.0        # seconds a point objective may spend without getting measurably closer
    max_escapes: int = 3                # hold-based escapes tried before a no-close failure is reported
    max_switch_attempts: int = 3        # presses of one switch with no flag change before it is a reported failure
    flag_wait_s: float = 0.6            # a press is applied asynchronously: poll the array this long for the change
    full_read_every: int = 4            # ticks between full entity reads; the player is read every tick


@dataclass(frozen=True)
class Action:
    """One bounded thing to do to the pad. Exactly one is issued per tick."""
    kind: str                  # "press" | "hold" | "release" | "wait"
    key: str | None = None
    seconds: float = 0.0
    reason: str = ""

    def __post_init__(self):
        if self.kind not in ("press", "hold", "release", "wait"):
            raise ValueError(f"unknown action kind {self.kind!r}")
        if self.kind in ("press", "hold") and self.key not in KEYS:
            raise ValueError(f"unknown key {self.key!r}")
        if self.seconds < 0:
            raise ValueError("an action cannot take negative time")

    def clipped(self, bounds: Bounds) -> "Action":
        if self.kind == "hold":
            return Action(self.kind, self.key, min(self.seconds, bounds.action_s), self.reason)
        if self.kind == "wait":
            return Action(self.kind, None, min(self.seconds, bounds.action_s), self.reason)
        return self

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "seconds": round(self.seconds, 3), "reason": self.reason}

    def events(self) -> list:
        """The concrete event batch for a world adapter: a tap carries its down and up together."""
        if self.kind == "press":
            return [{"key": self.key, "down": True}, {"key": self.key, "down": False}]
        if self.kind == "hold":
            return [{"key": self.key, "down": True}]
        if self.kind == "release":
            return [{"key": key, "down": False} for key in DIRECTIONS]
        return []

    def __str__(self) -> str:
        if self.kind in ("press", "hold"):
            return f"{self.kind} {self.key}" + (f" {self.seconds:.2f}s" if self.kind == "hold" else "")
        return self.kind


WAIT = Action("wait", None, 0.2, "nothing to do yet")
RELEASE = Action("release", None, 0.0, "release every direction")


def press(key: str, reason: str = "") -> Action:
    return Action("press", key, 0.0, reason)


def hold(key: str, seconds: float, reason: str = "") -> Action:
    return Action("hold", key, max(0.0, float(seconds)), reason)


# ---------------------------------------------------------------------------------------------------------------------
# Clock, operator ownership, watchdog
# ---------------------------------------------------------------------------------------------------------------------
class Clock(Protocol):
    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class OperatorGuard:
    """True while the human owns the pad.

    The relay drops `operator-playing.flag` while the operator plays, so a fresh flag means "hands off". A flag
    older than `stale_s` is a dead relay, not a playing operator: the endless loop learned that after an orphaned
    flag stood the bot down indefinitely.
    """

    def __init__(self, flag=None, *, stale_s: float = 15.0, source: Callable[[], bool] | None = None) -> None:
        self.flag = Path(flag) if flag else None
        self.stale_s = float(stale_s)
        self.source = source

    def active(self, now: float) -> bool:
        if self.source is not None:
            return bool(self.source())
        if self.flag is None:
            return False
        try:
            return (now - self.flag.stat().st_mtime) < self.stale_s
        except OSError:
            return False


@dataclass(frozen=True)
class Stall:
    seconds: float
    position: tuple
    recovery: int

    @property
    def to_dict(self) -> dict:
        return {"seconds": round(self.seconds, 2), "position": [round(v, 1) for v in self.position],
                "recovery": self.recovery}


class Watchdog:
    """Movement and objective liveness, evaluated once per tick before any branch.

    Two separate clocks, because they answer different questions:

    * `observe()`: has the character moved? A stall is recoverable motion.
    * `progress_age()`: has anything *happened* (room change, enemy HP, a flag, a container breaking)? A controller
      walking in circles is alive by the first clock and dead by the second, and the mandate's acceptance criterion
      is the second.
    """

    def __init__(self, *, movement_epsilon: float = 2.0, heading_epsilon: float = 10.0, stall_s: float = 20.0,
                 max_recoveries: int = 4, hard_progress_s: float = 300.0) -> None:
        self.movement_epsilon = float(movement_epsilon)
        self.heading_epsilon = float(heading_epsilon)
        self.stall_s = float(stall_s)
        self.max_recoveries = int(max_recoveries)
        self.hard_progress_s = float(hard_progress_s)
        self.position = None
        self.heading = None
        self.moved_at = 0.0
        self.started_at = 0.0
        self.recoveries = 0
        self.stalls = 0
        self.progressed_at = 0.0
        self.progress_kind = "start"

    def observe(self, player: dict, now: float) -> Stall | None:
        if not self.started_at:
            self.started_at = now
            self.progressed_at = now
        position = (float(player.get("x") or 0), float(player.get("z") or 0))
        heading = player.get("heading_deg")
        self.heading = None if heading is None else float(heading) % 360.0
        moved = self.position is None or math.dist(self.position, position) > self.movement_epsilon
        if moved:
            # Translation is the liveness signal. A rotation is not: every blocked tap in the Pioneer 2 plaza still
            # rotated the character by ~90 degrees, so counting rotation as liveness let a completely wedged character
            # look alive for 138 taps (measured). A controller that legitimately turns in place must show a step
            # within stall_s or it is stuck by definition.
            self.position, self.moved_at = position, now
            self.recoveries = 0
            return None
        if now - self.moved_at < self.stall_s:
            return None
        seconds = now - self.moved_at
        self.moved_at = now          # re-arm: the next verdict comes a full stall_s later
        self.stalls += 1
        self.recoveries += 1
        return Stall(seconds, position, self.recoveries)

    def note_progress(self, now: float, kind: str) -> None:
        self.progressed_at = now
        self.progress_kind = str(kind)
        self.recoveries = 0

    def progress_age(self, now: float) -> float:
        return now - (self.progressed_at or now)

    def overdue(self, now: float) -> bool:
        return self.progress_age(now) > self.hard_progress_s

    def recovery(self) -> Action:
        """One bounded recovery action, rotating. Never a nested unstick routine.

        A **hold**, not a tap, and the difference is measured: in the city corner at (349.6, -45.0) forty taps of
        every direction changed the position by 0.0 over three minutes, and a single 0.45 s hold of `left` moved the
        character 33 units out of it. A hold's distance depends on release latency (~35 units because the release job
        lands a second late), which is a defect for *movement* but exactly what an escape wants: a large, immediate
        displacement out of whatever geometry the small steps cannot leave.
        """
        plan = (("down", "reverse out of the obstruction"),
                ("left", "strafe away and probe"),
                ("right", "strafe the other way and probe"),
                ("up", "advance again after the sidestep"))
        key, why = plan[min(self.recoveries, len(plan)) - 1]
        return hold(key, 0.45, f"watchdog recovery {self.recoveries}/{self.max_recoveries}: {why}")

    def exhausted(self) -> bool:
        return self.recoveries > self.max_recoveries


# ---------------------------------------------------------------------------------------------------------------------
# Motion: one press per tick toward a point
# ---------------------------------------------------------------------------------------------------------------------
def _unit(dx: float, dz: float) -> tuple:
    length = math.hypot(dx, dz)
    return (0.0, 0.0) if length < 1e-9 else (dx / length, dz / length)


def _bearing(fx: float, fz: float, tx: float, tz: float) -> float:
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


class RelativeTapMotion:
    """Steer in the character's own frame: the facing comes from the last tap, not from `heading_deg`.

    The oscillation that this replaces is measured, not hypothetical: 138 taps around the Pioneer 2 plaza, ending 244
    units from a target 230 units away, with the room changing back and forth. The cause is that every direction key
    is **camera-relative**, the camera follows the character, and the character turns to face the way it moves - so
    the world direction of a key rotates between taps and a table learned one tap ago is already wrong.

    What stays valid is the relationship *between* the last movement and the target: after a tap the character is
    facing the direction it just moved, so the error to the target can be measured in that frame and the next key
    chosen from it. A tap is ~8 units, so the path turns in coarse steps and closes.

    `turn_deg` (from `calibrate()`) supplies how much a key rotates the character when it does not translate, which is
    how a turn-and-step build is handled by the same controller.
    """

    def __init__(self, *, arrive: float = 6.0, aim_deg: float = 60.0, min_move: float = 3.0,
                 turn_deg: dict | None = None, patience: int = 6) -> None:
        self.arrive = float(arrive)
        self.aim_deg = float(aim_deg)
        self.min_move = float(min_move)
        self.turn = {str(key): float(value) for key, value in (turn_deg or {}).items()}
        self.patience = int(patience)
        self.facing = None              # world unit vector: the direction the character last moved
        self.last_key = None
        self.need_probe = False         # a turn tap moved nothing, so the facing has to be re-measured
        self.best = None
        self.no_progress = 0
        self.flip_lateral = False       # the camera mode can invert left/right; one bad turn teaches the sign
        self.last_error = None
        self.last_was_lateral = False

    def step(self, player: dict, target: tuple, reason: str = "") -> Action | None:
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        dx, dz = float(target[0]) - x, float(target[1]) - z
        distance = math.hypot(dx, dz)
        if distance <= self.arrive:
            return None
        if self.best is None or distance < self.best - 0.5:
            self.best, self.no_progress = distance, 0
        else:
            self.no_progress += 1
        if self.no_progress >= self.patience:
            # Circling is not a stall: the character keeps moving, so the watchdog cannot see it, and the same key
            # choice keeps producing the same orbit. Turning around is a bounded action that changes the geometry.
            self.no_progress, self.best = 0, distance
            return press("down", f"no closing for {self.patience} taps toward {reason or 'target'}: turn around")
        if self.facing is None or self.need_probe:
            # One forward tap both moves and tells the model which way the character now faces. On a turn-and-step
            # build a turn key moves nothing, so without this the model would keep turning while the world turned
            # underneath it - which is exactly how a controller can spin forever while reporting progress.
            self.need_probe = False
            self.last_was_lateral = False
            return press("up", f"probe forward toward {reason or 'target'}")
        want = _unit(dx, dz)
        error = _bearing_degrees(self.facing, want)          # + right, - left, same sign as heading_deg
        if self.last_was_lateral and self.last_error is not None:
            # A lateral tap is only correct if it reduced the angular error. When the camera mode inverts the lateral
            # keys (measured: the same "left" tap rotated the character clockwise in one session and anticlockwise in
            # another), the first turn *increases* the error and this flips the sign for every turn after it.
            if abs(error) > abs(self.last_error) + 10.0:
                self.flip_lateral = not self.flip_lateral
        self.last_error = error
        self.last_was_lateral = False
        if abs(error) <= self.aim_deg:
            key = "up"
        elif abs(error) >= 180.0 - self.aim_deg:
            key = "down"
        else:
            key = "right" if error > 0 else "left"
            if self.flip_lateral:
                key = "left" if key == "right" else "right"
            self.last_was_lateral = True
        self.last_key = key
        return press(key, f"tap {key} ({error:+.0f} deg off) toward {reason or 'target'} ({distance:.0f} units)")

    def learn(self, action: Action, before: dict, after: dict) -> float:
        b = (float(before.get("x") or 0), float(before.get("z") or 0))
        a = (float(after.get("x") or 0), float(after.get("z") or 0))
        moved = math.dist(b, a)
        if action.kind == "press" and action.key in DIRECTIONS:
            if moved >= self.min_move:
                self.facing = _unit(a[0] - b[0], a[1] - b[1])
                self.need_probe = False
            elif action.key in self.turn and self.facing is not None:
                radians = math.radians(self.turn[action.key])
                fx, fz = self.facing
                self.facing = (fx * math.cos(radians) + fz * math.sin(radians),
                               -fx * math.sin(radians) + fz * math.cos(radians))
            elif action.key in DIRECTIONS:
                self.need_probe = True         # a turn we cannot model: re-measure the facing with one step
        return moved


def _bearing_degrees(a: tuple, b: tuple) -> float:
    """Signed angle from `a` to `b` in the heading convention (0 = +z, 90 = +x): + is clockwise, i.e. right."""
    return ((math.degrees(math.atan2(b[0], b[1])) - math.degrees(math.atan2(a[0], a[1])) + 540.0) % 360.0) - 180.0


class RouteFollower:
    """Advance along a router's waypoints toward a goal, and re-plan when the current leg does not yield.

    The city walk needed this: the plaza railing sits between the lobby and the warp door, and a point-to-point tap
    controller bounces against it (measured: 95 taps between (105,154) and (131,160)). The decoded collision grid has
    a 60-waypoint route between the same two points, so the controller follows the route instead of the straight line.
    """

    def __init__(self, router, *, arrive: float = 5.0, replan_after: int = 4, spacing: float = 12.0,
                 cell: float = 2.5) -> None:
        self.router = router
        self.arrive = float(arrive)
        self.replan_after = int(replan_after)
        self.spacing = float(spacing)
        self.cell = float(cell)
        self.route = None
        self.index = 0
        self.goal = None
        self.plans = 0
        self.stalls = 0

    def waypoint(self, player: dict, goal: tuple):
        """The point to walk toward now: the current anchor, advanced only when it is reached.

        A "nearest waypoint in the next ten" rule was tried and oscillates: the index jumps forward when the character
        happens to sit near a waypoint it already passed, the target jumps with it, and the character turns around -
        measured as 167 ticks ending 381 units from a target it started 390 away from. The route is resampled to
        anchors `spacing` apart so one anchor is worth about two taps, and the anchor only changes on arrival.
        """
        position = (float(player.get("x") or 0), float(player.get("z") or 0))
        if self.route is None or tuple(goal) != self.goal:
            self._plan(position, goal)
        if not self.route:
            return tuple(goal)
        # Advance the current anchor when it is reached or when the character has passed it along the leg to the next
        # one. "Passed" is safe *because the anchor is sequential*: the earlier version asked "is any waypoint in the
        # next ten already passed", which consumed the route while the character was far off to the side.
        while self.index < len(self.route) - 1:
            anchor = self.route[self.index]
            following = self.route[self.index + 1]
            leg = (following[0] - anchor[0], following[1] - anchor[1])
            offset = (position[0] - anchor[0], position[1] - anchor[1])
            passed = leg[0] * offset[0] + leg[1] * offset[1] > 0
            if math.dist(position, anchor) <= self.arrive or passed:
                self.index += 1
            else:
                break
        if math.dist(position, tuple(goal)) <= self.arrive:
            return None
        return self.route[self.index]

    def note_progress(self, progressed: bool) -> None:
        if progressed:
            self.stalls = 0
            return
        self.stalls += 1

    def replan(self, player: dict) -> None:
        """Called when a leg keeps failing: route again from where the character actually is."""
        position = (float(player.get("x") or 0), float(player.get("z") or 0))
        self._plan(position, self.goal or position, skip_first=True)

    def _connected_near(self, position: tuple):
        """The nearest grid cell that is actually part of a corridor, not one of the erosion's isolated islands.

        Measured: the Forest grid's safe set contains single-cell islands, and snapping onto one makes A* return None -
        the follower then falls back to a straight line and orbits (187 ticks, 380 units still to go). A cell with two
        or more safe neighbours is a corridor cell by definition, so routing from it works.
        """
        safe = getattr(self.router, "safe", None)
        if not isinstance(safe, set) or not safe:
            return None
        base = (math.floor(position[0] / self.cell), math.floor(position[1] / self.cell))
        neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1))

        def good(cell) -> bool:
            return cell in safe and sum((cell[0] + ox, cell[1] + oz) in safe for ox, oz in neighbours) >= 2

        if good(base):
            return ((base[0] + 0.5) * self.cell, (base[1] + 0.5) * self.cell)
        for radius in range(1, 28):
            for dx in range(-radius, radius + 1):
                for dz in (-radius, radius):
                    for cell in ((base[0] + dx, base[1] + dz), (base[0] + dz, base[1] + dx)):
                        if good(cell):
                            return ((cell[0] + 0.5) * self.cell, (cell[1] + 0.5) * self.cell)
        return None

    def _plan(self, position: tuple, goal: tuple, skip_first: bool = False) -> None:
        try:
            route = self.router.route(position, goal) or []
            if not route:
                snapped = self._connected_near(position)
                if snapped is not None and snapped != position:
                    route = self.router.route(snapped, goal) or []
        except Exception:                                    # noqa: BLE001 - a map is an aid, never a dependency
            route = []
        if skip_first and len(route) > 1:
            route = route[1:]                                # the leg that just failed: start past it
        # Resample to anchors about `spacing` apart: the raw route is one waypoint per 2.5-unit cell, which is a
        # quarter of a tap, and chasing those makes every tick a direction change.
        anchors = []
        for point in route:
            point = tuple(point)
            if not anchors or math.dist(anchors[-1], point) >= self.spacing:
                anchors.append(point)
        if route and (not anchors or tuple(route[-1]) != anchors[-1]):
            anchors.append(tuple(route[-1]))
        self.route = anchors
        self.index = 0
        self.goal = tuple(goal)
        self.plans += 1
        self.stalls = 0


class RoutedPolicy:
    """Wrap a policy so point objectives are pursued along the router's waypoints instead of in a straight line."""

    POINT_KINDS = ("walk", "door", "warp", "switch", "container")

    def __init__(self, base, router, *, arrive: float = 6.0) -> None:
        self.base = base
        self.follower = RouteFollower(router, arrive=arrive)

    @property
    def press_range(self) -> float:
        return float(getattr(self.base, "press_range", 14.0))

    @property
    def attack_range(self) -> float:
        return float(getattr(self.base, "attack_range", 30.0))

    def choose(self, snap: dict, now: float, *, pressed=None, avoid=None):
        objective = self.base.choose(snap, now, pressed=pressed, avoid=avoid)
        if objective is None or objective.kind not in self.POINT_KINDS:
            return objective
        player = snap.get("player") or {}
        real_distance = math.hypot(float(player.get("x") or 0) - objective.point[0],
                                   float(player.get("z") or 0) - objective.point[1])
        if self.follower.stalls >= self.follower.replan_after:
            # Several ticks without closing on this waypoint: it is blocked, so route around it from the current cell
            # instead of pushing against it until the no-close budget ends the run.
            self.follower.replan(player)
        goal = objective.point
        if objective.kind == "door" and real_distance > 22.0:
            # A closed door is *wall* to the collision mesh, so A* routes around it even after its flag opens it. Route
            # to a point just short of the door instead, and let the direct door logic walk the last 22 units through
            # the doorway (measured: the router delivered the character 25 units from the door and then took it 60
            # units away around the wall).
            ux, uz = _unit(objective.point[0] - float(player.get("x") or 0),
                           objective.point[1] - float(player.get("z") or 0))
            goal = (objective.point[0] - ux * 18.0, objective.point[1] - uz * 18.0)
        point = self.follower.waypoint(player, goal)
        if point is None:
            return objective                                 # the approach point or the goal itself is reached
        distance = math.hypot(float(player.get("x") or 0) - point[0], float(player.get("z") or 0) - point[1])
        return Objective(objective.rank, objective.kind, point, distance, objective.cls, objective.ptr,
                         objective.hp, objective.why, target_distance=real_distance)

    def note(self, kind: str, progressed: bool) -> None:
        self.base.note(kind, progressed)
        self.follower.note_progress(progressed)

    def progress_token(self) -> int:
        """A re-plan is a new attempt: the no-close budget must start again rather than end the run mid-route."""
        return self.follower.plans


class HillClimbMotion:
    """Keep the key that measurably closes the distance; when it stops, try another and keep the best.

    The models above try to say *which way* a key points and then trust that. The measured failure of that approach is
    a lane of 1,050 units travelled for 105 units of progress: a frame that cannot be inferred reliably turns every
    correction into a new orbit. This controller infers nothing. It records the distance closed by the last tap, credits
    or debits the key that produced it, and switches keys only when the current one stops paying - so an inverted or
    rotating frame costs one tap to notice, not a detour.
    """

    def __init__(self, *, arrive: float = 6.0, min_gain: float = 1.0, patience: int = 2,
                 keys: Iterable[str] = DIRECTIONS) -> None:
        self.arrive = float(arrive)
        self.min_gain = float(min_gain)
        self.patience = int(patience)
        self.keys = tuple(keys)
        self.key = None
        self.last_key = None
        self.last_pos = None
        self.last_dir = None
        self.gains = {key: 0.0 for key in self.keys}
        self.misses = 0
        self.switches = 0

    def step(self, player: dict, target: tuple, reason: str = "") -> Action | None:
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        dx, dz = float(target[0]) - x, float(target[1]) - z
        distance = math.hypot(dx, dz)
        if distance <= self.arrive:
            return None
        ux, uz = _unit(dx, dz)
        if self.last_key is not None and self.last_pos is not None and self.last_dir is not None:
            # Reward is the component of the last movement along the direction that was being aimed at *then*. The
            # distance to a route anchor cannot be used: the anchor moves ~12 units every couple of taps, so a target
            # jump reads as a loss and the controller abandons the key that was working (measured: 169 ticks of
            # zigzag between two areas 150 units apart).
            moved = (x - self.last_pos[0]) * self.last_dir[0] + (z - self.last_pos[1]) * self.last_dir[1]
            if moved >= self.min_gain:
                self.gains[self.last_key] += moved
                self.misses = 0
            else:
                self.gains[self.last_key] -= 2.0
                self.misses += 1
        if self.key is None or self.misses >= self.patience:
            self.key = self._next_key()
            self.misses = 0
            self.switches += 1
        self.last_key = self.key
        self.last_pos = (x, z)
        self.last_dir = (ux, uz)
        return press(self.key, f"tap {self.key} ({distance:.0f} units, gain {self.gains[self.key]:+.1f}) "
                              f"toward {reason or 'target'}")

    def _next_key(self) -> str:
        ranked = sorted(self.keys, key=lambda key: -self.gains[key])
        for key in ranked:
            if key != self.last_key:
                return key
        return ranked[0]


@dataclass
class Calibration:
    """What each key actually did, measured once at the start of a session.

    The handoff's post-mortem (`HANDOFF.md` 5.2) is the reason this exists: control loops were built before the input
    primitives were calibrated, and a 4x over-rotation per correction produced the zigzag the operator watched for
    hours. This measures each direction once, records it in the ledger, and states which motion model the session
    matches instead of assuming one.
    """
    effects: dict
    speed: float
    turn: dict
    model: str
    samples: list

    def as_dict(self) -> dict:
        return {"model": self.model, "speed": round(self.speed, 2),
                "effects": {key: [round(value[0], 2), round(value[1], 2)] for key, value in self.effects.items()},
                "turn_deg": {key: round(value, 1) for key, value in self.turn.items()},
                "samples": self.samples}


def calibrate(world, *, keys=DIRECTIONS, ledger: Ledger | None = None, clock: Clock | None = None,
              minimum: float = 1.0, turn_threshold: float = 12.0) -> Calibration:
    """Measure each direction key with one bounded tap, then say which motion model fits.

    A *tap* (down and up in one event batch) is the cheapest primitive that produces a measurable change, and it was
    measured on the live build as 2-3 units of travel. A key that moves less than `minimum` and rotates the heading
    by more than `turn_threshold` is a turn key; a key that moves is a translation key. When only the forward/back
    keys translate and the side keys turn, the session is the `heading` model; otherwise it is `vector`.
    """
    clock = clock or MonotonicClock()
    samples, effects, turn = [], {}, {}
    def read():
        return world.observe() or {}
    for key in keys:
        # Two taps, not one: a single tap can land against geometry and read as a dead key (measured live: `up`
        # returned a zero displacement on the first tap and 2.5 units a minute earlier). The larger sample wins.
        # The deadline is generous because a calibration press queues behind the run's release job: the control plane
        # takes ~1 s per job, and measuring before the job lands reads the previous position and invents a dead key.
        best = None
        for attempt in (1, 2):
            before = ((read().get("player") or {}))
            started = clock.now()
            state = world.act(press(key, f"calibration: measure {key} ({attempt})"), started + 8.0)
            after = ((read().get("player") or {}))
            dx = float(after.get("x") or 0) - float(before.get("x") or 0)
            dz = float(after.get("z") or 0) - float(before.get("z") or 0)
            moved = math.hypot(dx, dz)
            heading = ((float(after.get("heading_deg") or 0) - float(before.get("heading_deg") or 0) + 540.0)
                       % 360.0) - 180.0
            sample = {"key": key, "attempt": attempt, "job": state, "moved": round(moved, 2),
                      "heading": round(heading, 1),
                      "from": [round(float(before.get("x") or 0), 1), round(float(before.get("z") or 0), 1)],
                      "to": [round(float(after.get("x") or 0), 1), round(float(after.get("z") or 0), 1)]}
            samples.append(sample)
            if moved > (best or {}).get("moved", -1.0):
                best = {**sample, "dx": dx, "dz": dz}
            if moved >= minimum:
                break                                # one good sample is enough; do not waste a job on the second
        effects[key] = ((best or {}).get("dx", 0.0), (best or {}).get("dz", 0.0))
        turn[key] = (best or {}).get("heading", 0.0)
    moving = [key for key in keys if math.hypot(*effects[key]) >= minimum]
    turning = [key for key in keys if abs(turn[key]) >= turn_threshold and math.hypot(*effects[key]) < minimum]
    forward = [key for key in ("up", "down") if key in moving]
    model = "heading" if (forward and len(turning) >= 1 and len(moving) <= 2) else "vector"
    for key in keys:
        if key not in moving:
            effects[key] = (0.0, 0.0)                 # measured dead this session: do not blame the geometry later
    travel = [math.hypot(*effects[key]) for key in moving]
    speed = round(sum(travel) / len(travel) / 0.12, 1) if travel else 0.0
    result = Calibration(effects=effects, speed=speed, turn=turn, model=model, samples=samples)
    if ledger is not None:
        ledger.record("calibration", note=f"model={model}; {len(moving)} moving key(s)",
                      extra=result.as_dict())
    return result


class VectorMotion:
    """Learn what each key does to the world, then press the one that points at the target.

    Model-free on purpose: on the builds measured so far the same key has moved the character in different world
    directions as the camera turned, so a fixed key->direction table is wrong within a second. Every press is
    followed by a measurement, and the table is replaced with what actually happened.

    `primitive="tap"` is the calibrated default for this control plane. Measured live on 2026-11-13 with the character
    standing in the open: every direction tap moved **7.8-8.0 units** (n=4 per key, range 7.0-8.0), while a 0.30 s
    hold moved **38.9 units** - the release job lands about a second after the down job, so a "0.3 s" hold is really
    a 1.3 s run. A tap is one job, self-releasing, and its distance does not depend on job latency, which makes it the
    only primitive on this channel whose displacement is predictable. Holds remain available for a world whose
    release is prompt.
    """

    def __init__(self, *, arrive: float = 12.0, step_s: float = 0.3, min_move: float = 1.0,
                 max_blocked: int = 2, keys: Iterable[str] = DIRECTIONS, speed: float = 14.0,
                 primitive: str = "tap") -> None:
        if primitive not in ("tap", "hold"):
            raise ValueError("primitive must be 'tap' or 'hold'")
        self.arrive = float(arrive)
        self.step_s = float(step_s)
        self.min_move = float(min_move)
        self.max_blocked = int(max_blocked)
        self.keys = tuple(keys)
        self.speed = float(speed)
        self.primitive = primitive
        self.effects = {key: None for key in self.keys}     # None = unmeasured, (0, 0) = measured dead
        self.blocked = {key: 0 for key in self.keys}
        self.last = None

    def seed(self, effects: dict, *, speed: float | None = None) -> "VectorMotion":
        """Install a measured key->world table (see `calibrate`), so the first step is not a blind probe."""
        for key in self.keys:
            if key in effects:
                self.effects[key] = tuple(effects[key])
        if speed:
            self.speed = float(speed)
        return self

    def step(self, player: dict, target: tuple, reason: str = "") -> Action | None:
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        dx, dz = float(target[0]) - x, float(target[1]) - z
        distance = math.hypot(dx, dz)
        if distance <= self.arrive:
            return None
        ux, uz = _unit(dx, dz)
        scored = [(effect[0] * ux + effect[1] * uz, key) for key, effect in self.effects.items() if effect]
        scored = [entry for entry in scored if entry[0] > 0.2 and self.blocked[entry[1]] < self.max_blocked]
        unmeasured = [key for key in self.keys if self.effects[key] is None]
        # A measured key that merely points the right way is worse than measuring an unmeasured one: with only `up`
        # known, a target to the east has a positively-scored `down` (dot 0.2) and the character oscillates north and
        # south instead of ever trying `right`. Measured live as the same zigzag the operator watched, so probe first
        # unless the known key points almost straight at the target.
        if scored and (not unmeasured or max(entry[0] for entry in scored) >= 0.85):
            _, key = max(scored)
            self.last = key
            if self.primitive == "tap":
                return press(key, f"tap toward {reason or 'target'} ({distance:.0f} units)")
            seconds = min(self.step_s, max(0.12, distance / max(self.speed, 1e-6)))
            return hold(key, seconds, f"step toward {reason or 'target'} ({distance:.0f} units)")
        key = unmeasured[0] if unmeasured else min(self.keys, key=lambda k: self.blocked[k])
        self.last = key
        if self.primitive == "tap":
            return press(key, f"measure {key} toward {reason or 'target'}")
        return hold(key, self.step_s, f"measure {key} toward {reason or 'target'}")

    def learn(self, action: Action, before: dict, after: dict) -> float:
        """Update the key table from one measured press. Returns the distance actually moved."""
        if action.kind not in ("hold", "press") or action.key not in self.keys:
            return 0.0                                     # an attack button is not a movement measurement
        b = (float(before.get("x") or 0), float(before.get("z") or 0))
        a = (float(after.get("x") or 0), float(after.get("z") or 0))
        moved = math.dist(b, a)
        if moved >= self.min_move:
            self.effects[action.key] = (a[0] - b[0], a[1] - b[1])
            self.blocked[action.key] = 0
            if action.seconds > 0:
                observed = moved / action.seconds
                self.speed = 0.7 * self.speed + 0.3 * observed if self.speed else observed
        elif action.kind in ("hold", "press"):
            self.blocked[action.key] += 1
            if self.blocked[action.key] >= self.max_blocked:
                self.effects[action.key] = (0.0, 0.0)
        return moved


class HeadingMotion:
    """Turn by counted taps, then take one short step: the model that measurably converged on this build.

    Measured on the live GameCube build: one direction **tap** rotates ~8-11 degrees (a hold rotates far more, and
    assuming 10 degrees per tap while *holding* over-rotated every correction - the zigzag the operator watched),
    and a **0.22 s** forward hold walks about **14 units** (a 0.5 s hold walks ~31.6). That pair closed 60.8 -> 9.5
    units in ten steps with no position writes. This class issues exactly one tap or one step per tick.
    """

    def __init__(self, *, arrive: float = 12.0, aim_deg: float = 25.0, tap_s: float = 0.11,
                 step_s: float = 0.22, step_units: float = 14.0,
                 turn_rate_deg_per_s: float = 90.0, max_taps: int = 6) -> None:
        self.arrive = float(arrive)
        self.aim_deg = float(aim_deg)
        self.tap_s = float(tap_s)
        self.step_s = float(step_s)
        self.step_units = float(step_units)
        self.turn_rate = float(turn_rate_deg_per_s)
        self.max_taps = int(max_taps)
        self.blocked = 0
        self.heading = None

    def observe(self, player: dict) -> None:
        heading = player.get("heading_deg")
        if heading is not None:
            try:
                self.heading = float(heading) % 360.0
            except (TypeError, ValueError):
                pass

    def step(self, player: dict, target: tuple, reason: str = "") -> Action | None:
        self.observe(player)
        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        distance = math.hypot(float(target[0]) - x, float(target[1]) - z)
        if distance <= self.arrive:
            return None
        if self.heading is None:
            return hold("up", self.step_s, f"probe forward toward {reason or 'target'}")
        want = _bearing(x, z, float(target[0]), float(target[1]))
        error = ((want - self.heading + 540.0) % 360.0) - 180.0
        if abs(error) > self.aim_deg:
            # Measured on this build: a left tap LOWERS `heading_deg` (five samples, -39 to -88 degrees), so a target
            # clockwise of the facing is reached with `right`. The inverse was an assumption, and it steered away.
            key = "right" if error > 0 else "left"
            seconds = min(self.tap_s, max(0.06, abs(error) / max(self.turn_rate, 1e-3)))
            return hold(key, seconds, f"turn {error:+.0f} deg toward {reason or 'target'}")
        seconds = min(self.step_s, max(0.12, distance / max(self.step_units / self.step_s, 1e-6)))
        return hold("up", seconds, f"step toward {reason or 'target'} ({distance:.0f} units)")

    def learn(self, action: Action, before: dict, after: dict) -> float:
        b = (float(before.get("x") or 0), float(before.get("z") or 0))
        a = (float(after.get("x") or 0), float(after.get("z") or 0))
        moved = math.dist(b, a)
        if action.kind == "hold" and action.key == "up":
            self.blocked = 0 if moved >= 1.0 else self.blocked + 1
        return moved


# ---------------------------------------------------------------------------------------------------------------------
# Progression policy: what to do next, in dependency order
# ---------------------------------------------------------------------------------------------------------------------
SWITCH_CLASSES = frozenset({"TObjDoorKey", "TLazerFenceSw", "TOKeyGenericSw"})
DOOR_CLASSES = frozenset({"TObjDoor", "TObjLazerFenceNorm", "TOBarrierEnergy01", "TObjLazerFence"})
CONTAINER_HINTS = ("Container", "Capsule", "Trap")


@dataclass(frozen=True)
class Objective:
    rank: int
    kind: str                 # warp | wave | switch | door | container | walk
    point: tuple
    distance: float           # to `point` (a route waypoint once routed)
    cls: str = ""
    ptr: str = ""
    hp: float | None = None
    why: str = ""
    #: distance to the actual target entity. When a router replaces `point` with a waypoint this is the only number
    #: that may decide "close enough to press/attack" - using the waypoint distance pressed a door key from 70 units
    #: away (measured), because the first waypoint happened to be 8 units ahead of the character.
    target_distance: float | None = None

    def as_dict(self) -> dict:
        return {"rank": self.rank, "kind": self.kind, "class": self.cls, "ptr": self.ptr,
                "distance": round(self.distance, 1), "hp": self.hp, "why": self.why,
                "target_distance": None if self.target_distance is None else round(self.target_distance, 1)}


class ProgressionPolicy:
    """Choose the next objective from the dependency chain, not from what is near.

    The old loop ranked a container inside 60 units above a switch and spent its life on boxes: 79 containers in
    one reading. Here the order is fixed - warp (the way on) > live enemy wave (a required wave) > switch (the key
    to the way on) > door > **optional** container - and a container is only ever chosen when nothing in the chain
    is reachable, and never more than `optional_limit` times in a row. Containers cannot starve progression by
    construction; the streak is a second belt.
    """

    def __init__(self, *, engage: float = 40.0, reach: float = 400.0, press_range: float = 14.0,
                 attack_range: float = 30.0, avoid_s: float = 30.0, optional_limit: int = 3,
                 switch_demote_s: float = 60.0) -> None:
        self.engage = float(engage)
        self.reach = float(reach)
        self.press_range = float(press_range)
        self.attack_range = float(attack_range)
        self.avoid_s = float(avoid_s)
        self.optional_limit = int(optional_limit)
        self.switch_demote_s = float(switch_demote_s)
        self.optional_streak = 0
        self.current_key = None

    def choose(self, snap: dict, now: float, *, pressed=None, avoid=None) -> Objective | None:
        pressed = pressed or {}
        avoid = avoid or {}
        player = snap.get("player") or {}
        px, pz = float(player.get("x") or 0), float(player.get("z") or 0)
        candidates = []
        for kind in ("enemy", "gate", "object", "other"):
            for entity in (snap.get("entities") or {}).get(kind, []):
                if entity.get("x") is None or entity.get("z") is None:
                    continue
                cls = str(entity.get("class") or "")
                distance = math.hypot(float(entity["x"]) - px, float(entity["z"]) - pz)
                if distance > self.reach:
                    continue
                ptr = str(entity.get("ptr") or "")
                hp = entity.get("hp")
                if "Warp" in cls:
                    candidates.append(Objective(0, "warp", (float(entity["x"]), float(entity["z"])),
                                                distance, cls, ptr, None, "level exit in reach"))
                elif kind == "enemy" and hp is not None and float(hp) > 0 and distance <= self.engage:
                    if ptr in avoid and now - avoid[ptr] < self.avoid_s:
                        continue
                    candidates.append(Objective(1, "wave", (float(entity["x"]), float(entity["z"])),
                                                distance, cls, ptr, float(hp), "live enemy in the room"))
                elif cls in SWITCH_CLASSES:
                    if ptr in pressed:
                        continue                              # verified this session: a flag bit changed for it
                    candidates.append(Objective(2, "switch", (float(entity["x"]), float(entity["z"])),
                                                distance, cls, ptr, None, "switch for the way on"))
                elif cls in DOOR_CLASSES:
                    candidates.append(Objective(3, "door", (float(entity["x"]), float(entity["z"])),
                                                distance, cls, ptr, None, "door on the way on"))
                elif kind == "object" and any(hint in cls for hint in CONTAINER_HINTS):
                    if self.optional_streak < self.optional_limit:
                        candidates.append(Objective(4, "container", (float(entity["x"]), float(entity["z"])),
                                                    distance, cls, ptr, None, "optional loot"))
        if not candidates:
            return None
        best = min(candidates, key=lambda objective: (objective.rank, objective.distance))
        # Keep the current objective while it is still a candidate of the same rank. Two doors 115 and 116 units away
        # swap places on every tick as the character moves, and each swap re-planned the whole route (measured: a
        # 1 tick/s run whose character covered 45 units in 67 s, every re-plan an A* over 90,986 cells).
        current = next((objective for objective in candidates
                        if (objective.kind, objective.ptr) == self.current_key), None)
        if current is not None and current.rank <= best.rank:
            best = current
        self.current_key = (best.kind, best.ptr)
        return best

    def note(self, kind: str, progressed: bool) -> None:
        if kind == "container":
            self.optional_streak = 0 if progressed else self.optional_streak + 1
        elif kind in ("wave", "switch", "door", "warp"):
            self.optional_streak = 0


# ---------------------------------------------------------------------------------------------------------------------
# Combat: bounded combo sequencer, verified by what the game did
# ---------------------------------------------------------------------------------------------------------------------
class ComboSequencer:
    """Advance one combo hit per tick, and verify each attempt by what the game did.

    Section 7 of the mandate: a normal combo is up to three timed attacks, and the second and third must land inside
    the animation's cancel window. The windows are calibrated, not guessed: the tick loop records `action_state`
    (actor +0x326) before and after every press when the world can read it, and the enemy's HP always. An attempt
    that produced neither a state change nor an HP change after `grace_s` is a whiff and is counted as one; the
    target is abandoned after `whiff_limit` attempts rather than swinging forever.

    Presses are spaced by `gap_s`, and each gap is spent as a bounded `wait` action so the tick loop still yields.
    """

    def __init__(self, *, keys=("a", "a", "a"), gap_s: float = 0.45, grace_s: float = 0.9,
                 whiff_limit: int = 3) -> None:
        self.keys = tuple(keys)
        self.gap_s = float(gap_s)
        self.grace_s = float(grace_s)
        self.whiff_limit = int(whiff_limit)
        self.stage = 0
        self.pressed_at = 0.0
        self.attempt_hp = None
        self.attempt_end = None
        self.attempts = 0
        self.hits = 0
        self.whiffs = 0
        self.stage_transitions = 0
        self.hp = None
        self.action_state = None

    def next_action(self, now: float, *, reason: str = "combo") -> Action | None:
        # The gap applies between every press, including the first press of the next combo. Without it the 4th press
        # follows the 3rd immediately, which is not a combo and also keeps refreshing `attempt_end` so the whiff check
        # never gets its 0.9 s window (measured: one whiff counted across ten attempts).
        if self.pressed_at and (now - self.pressed_at) < self.gap_s:
            return Action("wait", None, self.gap_s - (now - self.pressed_at), f"{reason}: wait for the cancel window")
        if self.stage == 0:
            self.attempt_hp = self.hp
        key = self.keys[self.stage]
        self.pressed_at = now
        self.stage += 1
        if self.stage >= len(self.keys):
            self.stage = 0
            self.attempts += 1
            self.attempt_end = now
        return press(key, f"{reason} {self.stage or len(self.keys)}/{len(self.keys)}")

    def observe(self, *, hp, action_state=None, now: float = 0.0) -> dict:
        """Record what the world did. Returns the measured delta and settles a finished attempt."""
        delta = {"hp": None, "state_changed": None, "hit": False, "whiff": False}
        if hp is not None:
            self.hp = hp
            if self.attempt_hp is not None:
                delta["hp"] = round(float(hp) - float(self.attempt_hp), 2)
                delta["hit"] = delta["hp"] < 0
        if action_state is not None:
            if self.action_state is not None and action_state != self.action_state:
                delta["state_changed"] = True
                self.stage_transitions += 1
            else:
                delta["state_changed"] = False
            self.action_state = action_state
        if delta["hit"]:
            self.hits += 1
            self.whiffs = 0
            self.attempt_hp = hp
            self.attempt_end = None
        elif self.attempt_end is not None and now - self.attempt_end > self.grace_s:
            delta["whiff"] = True
            self.whiffs += 1
            self.attempt_hp = hp
            self.attempt_end = None
        return delta

    def give_up(self) -> bool:
        return self.whiffs >= self.whiff_limit

    def reset(self) -> None:
        self.stage = 0
        self.whiffs = 0
        self.attempt_hp = None
        self.attempt_end = None
        self.hp = None
        self.action_state = None


# ---------------------------------------------------------------------------------------------------------------------
# The world interface and the live session adapter
# ---------------------------------------------------------------------------------------------------------------------
class World(Protocol):
    def observe(self) -> dict: ...
    def act(self, action: Action, deadline: float) -> None: ...
    def release(self) -> None: ...


class SessionWorld:
    """`World` over gBox's session channel: `rpc state`, `rpc read_memory`, and controller input.

    Input goes through the app's **session input queue** (`POST /api/sessions/{sid}/input`), which is measured at
    **15 ms** round trip and moved the character 7.8 units on the first try, with the `session_op` job path (measured
    at 0.53-1.22 s per job) as the fallback. That distinction is the whole difference between a bot that takes one
    step a second and one that takes several: a hold no longer pays a second of queue latency for the down and
    another for the release, and an operator takeover is released in 15 ms rather than after the in-flight job.

    `call(path, payload=None, method="GET", timeout=60)` is injected so this adapter is testable without a running
    gBox. Each event batch carries its down and its up together, because splitting a press across jobs was measured
    to make the hold depend on job latency and to leave keys held when a release was lost.
    """

    def __init__(self, sid: str, call: Callable, *, worker: str | None = None, poll_s: float = 0.05,
                 sleep: Callable[[float], None] = time.sleep, fast_input: bool = True,
                 settle_s: float = 0.12) -> None:
        self.sid = sid
        self.call = call
        self.worker = worker or sid.split("-")[0]
        self.poll_s = float(poll_s)
        self.sleep = sleep
        self.fast_input = bool(fast_input)
        # The queue acknowledges in ~15 ms, before the worker has applied the events. Without this settle the
        # post-state read is the *previous* state: measured live, every tap then looked like it moved 0 units, the
        # motion model kept re-probing, and the routed walk drifted 160 units off its waypoints.
        self.settle_s = float(settle_s)
        self.sent = 0
        self.fast_sent = 0
        self.job_sent = 0

    def observe(self, player_only: bool = False) -> dict:
        args = {"player_only": True} if player_only else {}
        state = self.call(f"/api/sessions/{self.sid}/rpc", {"op": "state", "args": args}, "POST", 25)
        return state if isinstance(state, dict) else {}

    def read(self, address: int, length: int) -> bytes:
        raw = self.call(f"/api/sessions/{self.sid}/rpc",
                        {"op": "read_memory", "args": {"address": address, "length": length}}, "POST", 25)
        try:
            return bytes.fromhex(raw) if isinstance(raw, str) else b""
        except ValueError:
            return b""

    def act(self, action: Action, deadline: float) -> str:
        """Apply one action. Returns the delivery state: queued / succeeded / failed / timeout / no-job."""
        events = action.events()
        if not events:
            self.sleep(max(0.0, action.seconds))
            return "succeeded"
        state = self._apply(events, deadline)
        if action.kind == "hold":
            remaining = deadline - time.monotonic()
            if remaining > 0:
                self.sleep(min(action.seconds, remaining))
            self.release()                     # a hold always ends with every direction released
        self.sent += 1
        return state

    def release(self) -> None:
        self._apply(RELEASE.events(), time.monotonic() + 2.0)

    def _apply(self, events: list, deadline: float) -> str:
        if self.fast_input:
            queued = self.call(f"/api/sessions/{self.sid}/input", {"events": events}, "POST", 10)
            if isinstance(queued, dict) and "queued" in queued:
                self.fast_sent += 1
                if self.settle_s > 0:
                    self.sleep(self.settle_s)
                return "queued"
        self.job_sent += 1
        return self._job(events, deadline)

    def _job(self, events: list, deadline: float) -> str:
        job = self.call("/api/jobs", {"tool": "session_op", "require_worker": self.worker,
                                      "input": {"session_id": self.sid, "op": "send_input",
                                                "args": {"events": events}}}, "POST", 30)
        job_id = job.get("id") if isinstance(job, dict) else None
        if not job_id:
            return "no-job"
        while time.monotonic() < deadline:
            row = self.call("/api/jobs/" + job_id)
            if isinstance(row, dict) and row.get("state") in ("succeeded", "failed", "cancelled"):
                return str(row.get("state"))
            self.sleep(self.poll_s)
        # Deadline passed: the job is not cancelled, but the tick has to yield. A hold's release still happens in
        # `act`, so the pad is never left down - the invariant the old two-writer session broke.
        return "timeout"


# ---------------------------------------------------------------------------------------------------------------------
# The tick loop
# ---------------------------------------------------------------------------------------------------------------------
@dataclass
class Pending:
    """A movement action issued by one tick and measured by the next one's state read."""
    action: Action
    objective: Objective | None
    before: dict
    started: float
    index: int


@dataclass
class Tick:
    index: int
    started: float
    ended: float
    outcome: str                 # acted | preempted | stall | no-player | failed | stopped
    action: Action | None = None
    objective: Objective | None = None
    moved: float = 0.0
    elapsed: float = 0.0
    note: str = ""

    @property
    def duration(self) -> float:
        return round(self.elapsed, 3)

    def as_dict(self) -> dict:
        return {"index": self.index, "outcome": self.outcome, "elapsed": self.duration,
                "action": self.action.as_dict() if self.action else None,
                "objective": self.objective.as_dict() if self.objective else None,
                "moved": round(self.moved, 2), "note": self.note}


class Automaton:
    """One objective, one bounded action, one measured result, one ledger line - per tick.

    The tick order is fixed and is the point of the whole module: operator ownership is checked first, then the
    watchdog (movement *and* objective progress), then a plan, then exactly one action with a deadline, then the
    post-state. No branch can run before the watchdog, and no branch can issue two actions.
    """

    def __init__(self, world: World, *, ledger: Ledger, mode: RunMode = RunMode.NORMAL,
                 policy: ProgressionPolicy | None = None, motion=None, combat: ComboSequencer | None = None,
                 watchdog: Watchdog | None = None, operator: OperatorGuard | None = None,
                 bounds: Bounds | None = None, clock: Clock | None = None,
                 fixture_path=None, combos: Iterable[str] = ("a", "a", "a"),
                 flag_address: int | None = None, flag_length: int = 576) -> None:
        self.world = world
        self.ledger = ledger
        self.mode = mode
        self.bounds = bounds or Bounds()
        self.policy = policy or ProgressionPolicy()
        self.motion = motion or HeadingMotion()
        self.combat = combat or ComboSequencer(keys=combos)
        self.watchdog = watchdog or Watchdog(max_recoveries=self.bounds.max_recoveries,
                                            hard_progress_s=self.bounds.hard_progress_s)
        self.operator = operator or OperatorGuard()
        self.clock = clock or MonotonicClock()
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.flag_address = flag_address
        self.flag_length = int(flag_length)
        self.ticks = 0
        self.actions = 0
        self.overruns = 0
        self.history = deque(maxlen=80)
        self.pressed = {}
        self.switch_presses = {}
        self.switch_misses = {}
        self.switch_ok = set()
        self.avoid = {}
        self.stopped = ""
        self.failures = []
        self.last_objective: Objective | None = None
        self.objective_key = None
        self.objective_since = 0
        self.best_distance = None
        self.no_close = 0
        self.escapes = 0
        self.no_close_since = 0.0
        self.objective_since_at = 0.0
        self.entities = []
        self.room = None
        self.room_candidate = None
        self.room_count = 0
        self.pending = None

    # -- public -----------------------------------------------------------------------------------------------------
    def run_for(self, seconds: float) -> list:
        """Tick until `seconds` of wall clock have passed. The only loop here, and it owns nothing."""
        ticks, deadline = [], self.clock.now() + float(seconds)
        while self.clock.now() < deadline and not self.stopped:
            ticks.append(self.tick())
        last = self.flush()
        if last is not None:
            ticks.append(last)
        return ticks

    def tick(self) -> Tick:
        self.ticks += 1
        started = self.clock.now()
        phase = {"t0": time.monotonic(), "observe": 0.0, "plan": 0.0, "act": 0.0, "after": 0.0, "account": 0.0}
        if self.stopped:
            return self._finish(started, "stopped", note=self.stopped)
        if self.operator.active(started):
            # Cancellation: the operator gets the pad immediately, and the bot does nothing else this tick.
            self.world.release()
            self._record("preempted", None, None, None, note="operator owns the pad; inputs released")
            return self._finish(started, "preempted", note="operator takeover")

        before = self._observe(full=(self.ticks % max(1, self.bounds.full_read_every) == 1 or not self.entities))
        phase["observe"] = time.monotonic() - phase["t0"]
        player = before.get("player") or {}
        if player.get("ptr") is None:
            self._record("no-player", None, before, None, note="no player in the profile")
            return self._finish(started, "no-player", note="transition, menu or loading screen")

        # A movement action is measured by the *next* tick's read. Measured: a state read taken immediately after an
        # input takes 0.65-1.0 s on this worker (the input pump is serviced first), while the same read one tick later
        # takes 0.03 s. Deferring the read is what turns ~1 tick/s into 4-6, and it measures a settled position
        # instead of a half-applied one.
        concluded = None
        if self.pending is not None:
            concluded = self._conclude(self.pending, before, started)
            self.pending = None

        stall = self.watchdog.observe(player, started)
        if stall is not None:
            action = self.watchdog.recovery()
            self._execute(action, started)
            self._record("stall", action, before, None, extra=stall.to_dict)
            if self.watchdog.exhausted():
                return self._fail(started, f"stalled {stall.seconds:.0f}s at {stall.position} and every recovery "
                                           f"failed", before, action)
            return self._finish(started, "stall", action=action, note=f"no movement for {stall.seconds:.0f}s")

        if self.watchdog.overdue(started):
            return self._fail(started, f"no objective progress for {self.watchdog.progress_age(started):.0f}s "
                                      f"(last: {self.watchdog.progress_kind})", before, None)

        objective = self.policy.choose(before, started, pressed=self.pressed, avoid=self.avoid)
        action = self._plan(objective, before, started)
        phase["plan"] = time.monotonic() - phase["t0"] - phase["observe"]
        if action is None:
            action = WAIT if objective is not None else self._explore(player, started)
        escape_due = (started - (self.no_close_since or started)) >= max(1.5, float(self.bounds.max_no_close_s) / 6)
        if objective is not None and escape_due and self.escapes < self.bounds.max_escapes:
            # Moving but not closing: taps are the wrong size for this pocket. Try a hold before reporting failure.
            action = self._escape()
            self.no_close = 0
            self.escapes += 1
        action = action.clipped(self.bounds)

        # An interaction button is verified now; a direction tap is a movement and is measured next tick. Both are
        # "press" actions, so the kind alone cannot tell them apart - the key can.
        interaction = action.kind == "press" and action.key not in DIRECTIONS
        press_tick = interaction and objective is not None and objective.kind == "switch" and action.key == "a"
        if press_tick and self.world_supports_flags():
            before = self._with_flags(before)
        self._execute(action, started)
        phase["act"] = time.monotonic() - phase["t0"] - phase["observe"] - phase["plan"]

        # The mandate asks for the takeover check *after* every input as well as before it: one action is at most
        # half a second, and this is what makes that half second the longest the operator can be ignored.
        if self.operator.active(self.clock.now()):
            self.world.release()
            self._record("preempted", action, before, None, note="operator took the pad during the action; released")
            return self._finish(started, "preempted", action=action, objective=objective,
                                note="operator takeover after the input")

        if interaction:
            # An interaction is verified now: the press is the evidence, and a flag write or HP delta must be read
            # before the next action can change them. Movement is measured at the start of the next tick instead,
            # because a state read taken right after an input costs 0.65-1.0 s on this worker.
            after = self._observe(full=False)
            if press_tick and self.world_supports_flags():
                after = self._await_flag_change(after, before)
            phase["after"] = time.monotonic() - phase["t0"] - phase["observe"] - phase["plan"] - phase["act"]
            self.phases = phase
            if hasattr(self.motion, "learn"):
                self.motion.learn(action, player, self._player(after))
            moved, failure = self._account(objective, action, before, after, started)
            self._record("tick", action, before, after, note=objective.why if objective else "no objective in reach",
                         extra={"objective": objective.as_dict() if objective else None,
                                "flag_access": press_tick and self.world_supports_flags()})
            self.last_objective = objective
            if failure:
                return self._fail(started, failure, after, action)
            return self._finish(started, "acted", action=action, objective=objective, moved=moved,
                                note=objective.why if objective else "explored")

        self.pending = Pending(action, objective, before, started, self.ticks)
        if concluded is not None:
            return concluded
        return self._finish(started, "issued", action=action, objective=objective,
                            note="action issued; measured next tick")

    def flush(self):
        """Conclude the action still pending when a run ends, so its evidence is not lost."""
        if self.pending is None:
            return None
        pending, self.pending = self.pending, None
        after = self._observe(full=False)
        return self._conclude(pending, after, self.clock.now())

    def _conclude(self, pending, after: dict, now: float) -> Tick:
        action, objective, before = pending.action, pending.objective, pending.before
        if hasattr(self.motion, "learn"):
            self.motion.learn(action, self._player(before), self._player(after))
        moved, failure = self._account(objective, action, before, after, now)
        self._record("tick", action, before, after,
                     note=objective.why if objective else "no objective in reach",
                     extra={"objective": objective.as_dict() if objective else None,
                            "flag_access": False, "measured": "next tick"})
        self.last_objective = objective
        if failure:
            return self._fail(now, failure, after, action)
        return self._finish(pending.started, "acted", action=action, objective=objective, moved=moved,
                            note=objective.why if objective else "explored")

    # -- planning ---------------------------------------------------------------------------------------------------
    def _plan(self, objective: Objective | None, snap: dict, now: float) -> Action | None:
        player = snap.get("player") or {}
        if objective is None:
            return None
        target = objective.point
        arrive = float(getattr(self.motion, "arrive", 12.0))
        # Range checks use the distance to the actual entity, never to a route waypoint (see Objective.target_distance).
        reach = objective.distance if objective.target_distance is None else objective.target_distance
        if objective.kind == "wave":
            if reach <= self.policy.attack_range:
                return self.combat.next_action(now, reason=f"combo on {objective.cls}") or WAIT
            return self.motion.step(player, target, f"{objective.cls} at {reach:.0f} units")
        if objective.kind == "switch":
            if reach <= self.policy.press_range:
                self.switch_presses[objective.ptr] = self.switch_presses.get(objective.ptr, 0) + 1
                return press("a", f"press {objective.cls} at {reach:.1f} units "
                                  f"(attempt {self.switch_presses[objective.ptr]})")
            return self.motion.step(player, target, f"switch {objective.cls}")
        if objective.kind == "door":
            # A door is walked through, not pressed. Aim past it so the doorway's volume is crossed rather than stood
            # beside - which is why pressing A on a door at 12 units proved nothing about the door.
            point = self._through_point(player, target, 16.0) if objective.distance <= arrive else target
            return self.motion.step(player, point, f"door {objective.cls}")
        if objective.kind == "warp":
            point = self._through_point(player, target, 12.0) if objective.distance <= arrive else target
            return self.motion.step(player, point, f"warp {objective.cls}")
        if objective.kind == "container":
            if reach <= self.policy.attack_range:
                return self.combat.next_action(now, reason="break a container") or WAIT
            return self.motion.step(player, target, "optional container")
        if objective.kind == "walk":
            return None if objective.distance <= arrive else self.motion.step(player, target, "walk target")
        return None

    def _explore(self, player: dict, now: float) -> Action:
        """A deterministic bounded sweep when nothing in the dependency chain is in reach."""
        room = str(player.get("room") or "0").strip()
        direction = DIRECTIONS[int(room) % 4] if room.isdigit() else "up"
        return press(direction, f"explore room {room}: one step {direction}")

    def _account(self, objective: Objective | None, action: Action, before: dict, after: dict, now: float):
        """Turn the observed delta into progression, and feed it back to the policy and the watchdog.

        Returns (distance moved, failure reason or ""). A failure is reported rather than retried: one objective may
        not consume the session.
        """
        delta = diff(before, after)
        progressed, kind = False, "none"
        room = (after.get("player") or {}).get("room")
        if self._room_settled(room) is not None:
            # A room value that alternates every tick is a boundary flicker, not a transition: measured at
            # (7..14, 180..192) the room flipped 10 -> 11 -> 10 nine times and each flip reset the progress clocks,
            # which is how a character can bounce on a threshold while everything reports progress.
            progressed, kind = True, "room"
        elif delta["enemies"]:
            progressed, kind = True, "enemy-hp"
        elif delta["entities"]["vanished"]:
            progressed, kind = True, "entity-vanished"
        elif delta["stage_flags"] and delta["stage_flags"][0] != delta["stage_flags"][1]:
            progressed, kind = True, "stage-flag"
        elif objective is not None and objective.kind in ("walk", "door", "warp") \
                and self._arrived(objective, self._player(after)):
            # Arriving is progress only when arrival *is* the objective. Standing 8 units from a container or a switch
            # is not progress, and counting it as progress would reset the very streak that suppresses optional work.
            progressed, kind = True, "arrived"
        if progressed:
            self.watchdog.note_progress(now, kind)
        failure = ""
        if objective is not None:
            self.policy.note(objective.kind, progressed)
            failure = self._budget(objective, progressed, now) or self._closing(objective, after, now)
            if objective.kind == "switch":
                failure = failure or self._verify_switch(objective, action, before, after, now)
            if objective.kind == "wave":
                hp = next((row.get("hp") for row in (after.get("entities") or {}).get("enemy", [])
                           if str(row.get("ptr")) == objective.ptr), None)
                self.combat.observe(hp=hp, now=now)
                if self.combat.give_up():
                    self.avoid[objective.ptr] = now
                    self.combat.reset()
        return delta["moved"], failure

    def _verify_switch(self, objective: Objective, action: Action, before: dict, after: dict, now: float) -> str:
        """A press is not a success. Only a changed stage-flag bit is, and a repeated no-change is a failure.

        The old loop called a switch pressed as soon as A was sent (`INTERACT: pressed A on TObjLazerFenceNorm at
        11.9 units`) and then kept walking into a door that had never opened. Here the press is verified against the
        native stage-flag array; three presses with no bit change end the run with the switch named in a fixture,
        and a world that cannot read flags never claims a success at all.
        """
        if not (action.kind == "press" and action.key == "a"):
            return ""                                  # this tick was not a switch press
        if not self.world_supports_flags():
            presses = self.switch_presses.get(objective.ptr, 0)
            if presses >= self.bounds.max_switch_attempts:
                self.pressed[objective.ptr] = now      # stop pressing an unverifiable switch; the ledger says why
            return ""
        first, second = before.get("stage_flags"), after.get("stage_flags")
        if not (first and second):
            return ""
        if first.get("sha256") != second.get("sha256"):
            self.switch_ok.add(objective.ptr)
            self.pressed[objective.ptr] = now
            self.switch_misses.pop(objective.ptr, None)
            return ""
        misses = self.switch_misses.get(objective.ptr, 0) + 1
        self.switch_misses[objective.ptr] = misses
        if misses >= self.bounds.max_switch_attempts:
            return (f"pressed {objective.cls} at {objective.ptr} {misses} times and no stage-flag bit changed; "
                    f"the array may already be saturated by an earlier full-group write, or this switch is not wired "
                    f"to a flag in this group")
        return ""

    def _closing(self, objective: Objective, after: dict, now: float) -> str:
        """Distance closed is the progress signal for a point objective; oscillation is not.

        The budget is in **seconds**, not ticks. The same loop runs at 1 tick/s while the worker stalls and at 5 tick/s
        when it does not (both measured), so a 40-tick budget is 40 seconds in one run and 8 in the next. How long a
        walk may fail to close is a property of the game, not of the loop's speed.
        """
        if objective.kind == "wave":
            return ""                                   # a moving enemy is closed by HP, handled by the combat path
        player = self._player(after)
        if not player:
            return ""
        token = None
        getter = getattr(self.policy, "progress_token", None)
        if callable(getter):
            try:
                token = getter()
            except Exception:                              # noqa: BLE001 - a policy hook must never stop the loop
                token = None
        if token is not None and token != getattr(self, "_progress_token", None):
            self._progress_token = token
            self.best_distance = None
            self.no_close = 0
            self.no_close_since = now
        distance = math.hypot(float(player.get("x") or 0) - objective.point[0],
                              float(player.get("z") or 0) - objective.point[1])
        if self.best_distance is None or distance < self.best_distance - 2.0:
            self.best_distance = distance
            self.no_close = 0
            self.no_close_since = now
            return ""
        self.no_close += 1
        stalled = now - (self.no_close_since or now)
        if stalled > float(self.bounds.max_no_close_s):
            if self.escapes < self.bounds.max_escapes:
                self.no_close = 0
                self.no_close_since = now
                return ""                                # the escape in tick() gets another budget
            return (f"{objective.kind} {objective.cls or objective.ptr} not closed for {stalled:.0f}s after "
                    f"{self.escapes} hold escapes (still {distance:.0f} units away); the character is moving without "
                    f"approaching it")
        return ""

    def _escape(self) -> Action:
        """A hold in a rotating direction, used when the character moves but cannot close on the objective.

        Measured: taps move ~8 units and a hold moves ~33, and pockets that swallow taps do not swallow holds. The
        no-close budget therefore tries escapes before it reports a failure - three of them, each mirrored in the
        ledger, and only then the fixture.
        """
        plan = ("down", "left", "right", "up")
        key = plan[self.escapes % len(plan)]
        return hold(key, 0.45, f"escape {self.escapes + 1}/{self.bounds.max_escapes}: hold {key} out of a pocket "
                               f"that swallowed {self.bounds.max_no_close_ticks} taps")

    def _room_settled(self, room):
        """Return (previous, current) only when the room has actually settled, two consecutive ticks on one value."""
        if room is None:
            return None
        if room == self.room_candidate:
            self.room_count += 1
        else:
            self.room_candidate, self.room_count = room, 1
        if self.room_count >= 2 and room != self.room:
            previous, self.room = self.room, room
            return previous, room
        return None

    def _budget(self, objective: Objective, progressed: bool, now: float) -> str:
        """One objective may not consume the session: bounded attempts, then a fixture instead of a loop.

        Time-bounded for the same reason as `_closing`: a tick budget means a different number of seconds on every run.
        """
        key = (objective.kind, objective.ptr)
        if key != self.objective_key:
            self.objective_key = key
            self.objective_since = self.ticks
            self.objective_since_at = now
            self.best_distance, self.no_close = None, 0
            self.no_close_since = now
            return ""
        if progressed:
            self.objective_since = self.ticks
            self.objective_since_at = now
            return ""
        spent = now - (getattr(self, "objective_since_at", now) or now)
        if spent > float(self.bounds.max_objective_s):
            return (f"{objective.kind} {objective.cls} at {objective.ptr} consumed {spent:.0f}s without progress")
        return ""

    @staticmethod
    def _arrived(objective: Objective, player) -> bool:
        return math.hypot(float(player.get("x") or 0) - objective.point[0],
                          float(player.get("z") or 0) - objective.point[1]) <= 14.0

    @staticmethod
    def _through_point(player: dict, target: tuple, beyond: float) -> tuple:
        px, pz = float(player.get("x") or 0), float(player.get("z") or 0)
        ux, uz = _unit(target[0] - px, target[1] - pz)
        if (ux, uz) == (0.0, 0.0):
            return target
        return (target[0] + ux * beyond, target[1] + uz * beyond)

    # -- observation and evidence -----------------------------------------------------------------------------------
    def world_supports_flags(self) -> bool:
        return self.flag_address is not None and hasattr(self.world, "read")

    def _observe(self, *, full: bool = True) -> dict:
        """Read the state; the full entity table is expensive and barely changes between ticks.

        Measured: a full state read takes 31 ms when idle but **0.5-1.0 s** while the worker is applying input, which
        was 0.7 s of every tick. The player changes every tick and the entity table does not, so the player is read
        every tick and the entities every `full_read_every` ticks (the cached table is merged back in).
        """
        if full:
            state = self.world.observe() or {}
            self.entities = state.get("entities") or []
        else:
            state = self.world.observe(player_only=True) or {}
            state = {**state, "entities": self.entities}
        return snapshot(state)

    def _with_flags(self, snap: dict) -> dict:
        try:
            raw = self.world.read(int(self.flag_address), self.flag_length)
        except Exception:                                  # noqa: BLE001 - evidence must never stop the loop
            return snap
        return with_flags(snap, raw) if raw else snap

    def _await_flag_change(self, after: dict, before: dict) -> dict:
        """Poll the stage-flag array for a beat after a press: the input is queued and the game writes the flag later.

        Measured: the press that set floor 1 bit 7 was recorded as three attempts, because the array still matched
        the pre-press digest 0.12 s after the second press and only showed the change on the third. Two failed
        verifications would have ended the switch after three attempts even though the switch had worked.
        """
        wait = float(self.bounds.flag_wait_s)
        deadline = self.clock.now() + wait
        snap = after
        original = (before.get("stage_flags") or {}).get("sha256")
        while True:
            snap = self._with_flags(snap)
            current = (snap.get("stage_flags") or {}).get("sha256")
            if current and original and current != original:
                return snap
            if self.clock.now() >= deadline:
                return snap
            self.clock.sleep(0.08)

    @staticmethod
    def _player(snap: dict) -> dict:
        return (snap or {}).get("player") or {}

    def _execute(self, action: Action, now: float) -> None:
        deadline = now + self.bounds.tick_s
        self.world.act(action, deadline)
        elapsed = self.clock.now() - now
        self.actions += 1
        if elapsed > self.bounds.tick_s + 1e-6:
            # The scheduler measures the branch instead of trusting it: a world adapter that ignores its deadline is
            # a defect, and it goes in the ledger as one rather than silently extending the tick.
            self.overruns += 1
            self._record("overrun", action, None, None,
                         note=f"the adapter took {elapsed:.2f}s against a {self.bounds.tick_s:.2f}s tick bound")

    def _record(self, kind: str, action, before, after, *, note: str = "", extra=None) -> None:
        self.ledger.record(kind, action=action.as_dict() if isinstance(action, Action) else action,
                           before=before, after=after, note=note,
                           extra={"mode": self.mode.value, **(extra or {})})

    def _fail(self, started: float, reason: str, snap: dict, action) -> Tick:
        self._record("failed", action, snap, None, note=reason)
        fixture = failure_fixture(snap, list(self.history), reason=reason,
                                  note=self.last_objective.why if self.last_objective else "")
        if self.fixture_path is not None:
            self.fixture_path.parent.mkdir(parents=True, exist_ok=True)
            self.fixture_path.write_text(json.dumps(fixture, indent=1, sort_keys=True), encoding="utf-8")
        self.failures.append(fixture)
        self.stopped = reason
        self.world.release()
        return self._finish(started, "failed", action=action, note=reason)

    def _finish(self, started, outcome, *, action=None, objective=None, moved=0.0, note="") -> Tick:
        ended = self.clock.now()
        tick = Tick(self.ticks, started, ended, outcome, action, objective, moved, ended - started, note)
        self.history.append(tick.as_dict())
        return tick

    def stats(self) -> dict:
        return {"ticks": self.ticks, "actions": self.actions, "overruns": self.overruns,
                "stalls": self.watchdog.stalls, "recoveries": self.watchdog.recoveries,
                "escapes": self.escapes, "no_close": self.no_close,
                "progress_kind": self.watchdog.progress_kind,
                "progress_age": round(self.watchdog.progress_age(self.clock.now()), 1),
                "combos": {"attempts": self.combat.attempts, "hits": self.combat.hits,
                           "whiffs": self.combat.whiffs, "stage_transitions": self.combat.stage_transitions},
                "stopped": self.stopped, "failures": len(self.failures)}
