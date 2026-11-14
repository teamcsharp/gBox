"""The bounded controller must be bounded. These tests are the proof, not the description.

Every test drives `gbox.pso_bounded` through a simulated world. The simulated world is adversarial on purpose: keys
map to different world directions as the camera turns, forward can be blocked, an enemy can refuse to take damage,
and the operator can grab the pad mid-action. The assertions are the mandate's Day-1 requirements:

* exactly one action per tick, never longer than the bound, and a tick that overruns is *detected*;
* the operator's takeover releases the pad before anything else happens, and is checked again after every input;
* a wedged character is recovered a bounded number of times and then produces a failure fixture - not a loop;
* progression objectives outrank containers, and containers cannot starve progression;
* a switch press is recorded with a stage-flag delta (and with "no change" when nothing changed);
* a combo is three spaced presses verified by HP, and a target that cannot be hurt is abandoned.
"""
import json
import math
import os
import pathlib
import shutil
import tempfile
import time
import uuid

import pytest

from gbox import pso_bounded as B
from gbox import pso_evidence as E


# ---------------------------------------------------------------------------------------------------------------------
# A simulated world with a camera that turns and geometry that blocks
# ---------------------------------------------------------------------------------------------------------------------
class FakeClock:
    def __init__(self, start=1000.0):
        self.t = float(start)

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(0.0, float(seconds))


class FakeWorld:
    def __init__(self, clock, *, mode="tank", speed=14.0, heading=0.0):
        self.clock = clock
        self.mode = mode
        self.speed = float(speed)
        self.pos = [0.0, 0.0]
        self.facing = float(heading)
        self.room = 1
        self.hp = 76
        self.entities = []
        self.actions = []
        self.log = []
        self.releases = 0
        self.blocked = set()
        self.flags = bytearray(576)
        self.flag_reads = []
        self.switch_delay = 0            # reads to serve the old array for, after a switch press
        self.attack_lands = True
        self.attack_damage = 9.0
        self.attack_range = 30.0
        self.press_range = 25.0
        self.tap_units = 8.0             # measured live: every direction tap moved 7.8-8.0 units
        self.tap_seconds = 0.6           # and cost one input-job round trip, ~0.6 s
        self.door = None
        self.door_locked = False
        self.switch_works = True
        self.tick_seconds = 0.0          # extra time an action "takes" (for the overrun test)

    # -- World protocol -------------------------------------------------------------------------------------------
    def observe(self, player_only=False):
        player = {"ptr": "80DA62A0", "class": "TObjPlayer", "room": self.room,
                  "x": round(self.pos[0], 3), "y": 0.0, "z": round(self.pos[1], 3),
                  "heading_deg": round(math.degrees(self.facing) % 360.0, 1),
                  "hp": self.hp, "hp_max": 76}
        if player_only:
            return {"player": player, "entities": []}
        return {"player": player, "entities": [dict(entity) for entity in self.entities]}

    def act(self, action, deadline):
        self.actions.append(action)
        self.log.append((self.clock.now(), action))
        if action.kind == "release":
            self.releases += 1
        elif action.kind == "wait":
            self.clock.t += action.seconds
        elif action.kind == "hold":
            self._move(action.key, action.seconds)
            self.clock.t += action.seconds
        elif action.kind == "press":
            if action.key in B.DIRECTIONS:
                self._move(action.key, self.tap_units / self.speed)   # a tap: one calibrated step
                self.clock.t += self.tap_seconds                  # a tap costs one job round trip
            else:
                self._press(action.key)
                self.clock.t += 0.05
        self.clock.t += self.tick_seconds

    def read(self, address, length):
        raw = bytes(self.flags[:length])
        self.flag_reads.append(raw)
        if self.switch_delay:
            # The game writes the flag on a later frame than the input: model that as "not yet" for N reads.
            if self.switch_delay > 0:
                self.switch_delay -= 1
                return bytes(576)
        return raw

    def release(self):
        self.releases += 1

    # -- world mechanics ------------------------------------------------------------------------------------------
    def _move(self, key, seconds):
        if key in self.blocked:
            return
        step = self.speed * seconds
        if self.mode == "tank":
            # Heading convention: 0 = +z, 90 = +x, so a LEFT tap lowers the heading (measured live: -45 degrees).
            if key == "left":
                self.facing -= math.pi / 4
                return
            if key == "right":
                self.facing += math.pi / 4
                return
            if key == "down":
                # A backward tap turns the character around (it faces the way it moves), then it advances.
                self.facing += math.pi
                self.pos[0] += math.sin(self.facing) * step
                self.pos[1] += math.cos(self.facing) * step
                return
            self.pos[0] += math.sin(self.facing) * step
            self.pos[1] += math.cos(self.facing) * step
        else:
            vectors = {"up": (0.0, 1.0), "down": (0.0, -1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}
            dx, dz = vectors[key]
            self.pos[0] += dx * step
            self.pos[1] += dz * step
        if self.door is not None and math.dist(self.pos, self.door) <= 5.0 and not self.door_locked:
            self.room += 1
            self.door = None

    def _press(self, key):
        for entity in list(self.entities):
            distance = math.hypot(entity["x"] - self.pos[0], entity["z"] - self.pos[1])
            if entity.get("kind") == "enemy" and distance <= self.attack_range and self.attack_lands:
                entity["hp"] = max(0.0, float(entity["hp"]) - self.attack_damage)
                if entity["hp"] <= 0:
                    self.entities.remove(entity)
            elif entity.get("kind") == "gate" and distance <= self.press_range:
                if entity.get("class") in B.SWITCH_CLASSES and self.switch_works:
                    self.flags[3 * 32 + 2] |= 0x04        # group 3, index 21: a switch's linked flag
                    self.door_locked = False


@pytest.fixture()
def workdir():
    """A scratch directory that does not depend on pytest's temp machinery.

    `tempfile.mkdtemp` (which pytest's `tmp_path` uses) creates its directory with mode 0o700, and on this Windows
    host such a directory carries a DACL the confined test process cannot even list, so a test that takes
    `tmp_path` fails before it runs. This fixture creates an ordinary directory in the same temp area instead.
    """
    path = pathlib.Path(tempfile.gettempdir()) / f"pso-bounded-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def automaton(world, workdir, **overrides):
    clock = world.clock
    options = dict(ledger=E.Ledger(workdir / "ledger.jsonl", clock=clock.now, run="test"),
                   clock=clock, motion=B.VectorMotion(arrive=10.0), policy=B.ProgressionPolicy(engage=40.0),
                   watchdog=B.Watchdog(stall_s=2.0, max_recoveries=2),
                   bounds=B.Bounds(max_objective_ticks=60),
                   fixture_path=workdir / "failure.json",
                   flag_address=0x80515CC8, flag_length=576)
    options.update(overrides)
    return B.Automaton(world, **options)


def entity(cls, ptr, x, z, *, kind="gate", hp=None, room=1, slot=0):
    row = {"class": cls, "ptr": ptr, "entity_id": slot, "kind": kind, "room": room, "slot": slot,
           "x": float(x), "y": 0.0, "z": float(z)}
    if hp is not None:
        row["hp"] = float(hp)
    return row


# ---------------------------------------------------------------------------------------------------------------------
# Actions are bounded, and a tick issues exactly one
# ---------------------------------------------------------------------------------------------------------------------
def test_tick_issues_exactly_one_action_and_never_exceeds_the_bound(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 120.0, 0.0)]
    box = automaton(world, workdir, motion=B.VectorMotion(arrive=10.0, step_s=0.3),
                    bounds=B.Bounds(max_objective_ticks=200))
    ticks = box.run_for(30.0)

    assert ticks, "the loop must tick"
    # One action per tick: a movement action is issued by one tick and measured by the next, so the last action is
    # concluded by flush() without issuing a new one. Never two actions in one tick.
    assert len(world.actions) <= len(ticks), "never more than one world action per tick"
    assert len(world.actions) >= len(ticks) - 2
    assert all(action.seconds <= box.bounds.action_s for action in world.actions)
    assert all(tick.elapsed < box.bounds.tick_s for tick in ticks)
    assert box.overruns == 0
    assert box.stats()["actions"] >= len(ticks) - 2


def test_a_tick_that_overruns_its_bound_is_detected_and_recorded(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 300.0, 0.0)]
    world.tick_seconds = 5.0                 # a world adapter that ignores its deadline
    box = automaton(world, workdir)
    tick = box.tick()

    assert tick.elapsed >= 5.0
    assert box.overruns == 1
    assert any(entry["kind"] == "overrun" for entry in _entries(box))


def test_action_validation_rejects_unknown_inputs():
    with pytest.raises(ValueError):
        B.Action("press", "select", 0.0, "not on this pad")
    with pytest.raises(ValueError):
        B.Action("teleport", None, 0.0, "not an action")
    assert B.hold("up", 9.0, "too long").clipped(B.Bounds(action_s=0.5)).seconds == 0.5


# ---------------------------------------------------------------------------------------------------------------------
# Operator ownership: checked before and after every input
# ---------------------------------------------------------------------------------------------------------------------
def test_a_stale_operator_flag_does_not_block_the_bot(workdir):
    """The flag's mtime is an epoch, the tick clock is monotonic: comparing them made every leftover flag fresh forever.

    Measured live: a 141-second-old `operator-playing.flag` still produced "operator owns the pad" for a whole run.
    """
    flag = workdir / "operator-playing.flag"
    flag.write_text("operator pad relay", encoding="ascii")
    guard = B.OperatorGuard(flag, stale_s=15.0)
    assert guard.active(1234.0) is True, "a fresh flag means hands off, whatever clock the caller passes"
    old = time.time() - 300.0
    os.utime(flag, (old, old))
    assert guard.active(1234.0) is False, "a dead relay's flag is not a playing operator"


def test_operator_takeover_before_the_tick_releases_and_presses_nothing(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    state = {"playing": True}
    box = automaton(world, workdir, operator=B.OperatorGuard(source=lambda: state["playing"]))
    tick = box.tick()

    assert tick.outcome == "preempted"
    assert world.actions == []
    assert world.releases == 1
    assert _entries(box)[-1]["kind"] == "preempted"


def test_operator_takeover_after_an_input_is_detected_and_the_pad_is_released(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TLazerFenceSw", "80DADF10", 300.0, 0.0)]
    calls = {"n": 0}

    def operator():
        calls["n"] += 1
        return calls["n"] > 1                 # not playing at the start of the tick, playing right after the action

    box = automaton(world, workdir, operator=B.OperatorGuard(source=operator))
    tick = box.tick()

    assert tick.outcome == "preempted"
    assert len(world.actions) == 1             # the action in flight completed
    assert world.releases == 1                 # and was released immediately afterwards
    assert "after the input" in tick.note


# ---------------------------------------------------------------------------------------------------------------------
# The watchdog: bounded recovery, then a failure fixture instead of a loop
# ---------------------------------------------------------------------------------------------------------------------
def test_a_wedged_character_is_recovered_a_bounded_number_of_times_then_fixtured(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.blocked = set(B.DIRECTIONS)          # nothing moves: the measured (487, 0) wedge
    world.entities = [entity("TObjDoor", "80DAD5C0", 40.0, 0.0)]
    box = automaton(world, workdir, watchdog=B.Watchdog(stall_s=2.0, max_recoveries=2),
                    bounds=B.Bounds(max_recoveries=2, max_objective_ticks=60))
    ticks = box.run_for(120.0)
    recoveries = [action for action in world.actions if "watchdog recovery" in action.reason]
    assert recoveries, "a wedge must be recovered, not silently looped"
    # The escape alternates a turn and a short hold: the stick is camera-relative, so in a corner all four directions
    # can point into the same wall (measured at (310,540): holds moved 0.0 for 70 s, one turn plus the same hold moved
    # 7 units), and a hold is still what produces the displacement (40 taps moved 0.0 where one hold moved 33).
    assert any(action.kind == "press" for action in recoveries), "a turn comes first, to change the frame"
    assert any(action.kind == "hold" for action in recoveries), "and a hold produces the movement"

    assert box.stopped, "a wedge must end in a reported failure, not a silent loop"
    assert box.watchdog.stalls >= 1
    assert ticks[-1].outcome == "failed"
    fixture = json.loads((workdir / "failure.json").read_text(encoding="utf-8"))
    assert "stalled" in fixture["reason"]
    assert fixture["state"]["player"]["x"] == 0.0
    assert fixture["history"], "the fixture carries the ticks that led to it"
    assert len(ticks) < 60, "bounded: it must not spend the session discovering the same wedge"
    assert box.world.releases >= 1


class DriftingWorld(FakeWorld):
    """Every action moves the character, but the movement never approaches the target: the plaza oscillation."""

    def __init__(self, clock, **kwargs):
        super().__init__(clock, **kwargs)
        self.side = 1.0

    def act(self, action, deadline):
        super().act(action, deadline)
        self.side = -self.side
        self.pos[0] += 4.0 * self.side
        self.pos[1] += 6.0          # always away from the origin, so the (0,0) target is never closed


class _FixedWalk:
    """A policy whose only objective is one coordinate (kind='door' walks through it)."""

    def __init__(self, point, kind="walk"):
        self.point = point
        self.kind = kind

    def choose(self, snap, now, *, pressed=None, avoid=None):
        player = snap.get("player") or {}
        distance = math.hypot(self.point[0] - float(player.get("x") or 0),
                              self.point[1] - float(player.get("z") or 0))
        return B.Objective(0, self.kind, self.point, distance, "coordinate", "", None, "walk target")

    def note(self, kind, progressed):
        pass


def test_a_walk_that_moves_without_closing_escalates(workdir):
    clock = FakeClock()
    world = DriftingWorld(clock)
    box = automaton(world, workdir, policy=_FixedWalk((0.0, 0.0)),
                    bounds=B.Bounds(max_no_close_ticks=10))
    box.run_for(60.0)

    assert box.stopped, "moving without approaching the target must not be accepted as progress"
    assert "not closed" in box.stopped
    assert (workdir / "failure.json").exists()


class FlickerWorld(FakeWorld):
    """The room flips every tick, as it did at the Forest room 10/11 boundary."""

    def act(self, action, deadline):
        super().act(action, deadline)
        self.room = 11 if self.room == 10 else 10


def test_a_room_that_flicks_back_and_forth_is_not_progress(workdir):
    clock = FakeClock()
    world = FlickerWorld(clock)
    world.entities = [entity("TObjDoorKey", "80DB5650", 200.0, 0.0)]
    box = automaton(world, workdir, bounds=B.Bounds(max_no_close_s=6.0))
    box.run_for(30.0)

    assert box.watchdog.progress_kind != "room", "a flickering room is not progress"
    # The character in this world never gets anywhere either, and that is now visible: the watchdog's net-window
    # verdict fires even though every individual tap "moved".
    assert box.watchdog.stalls >= 1, "a character that moves but goes nowhere is a stall"


class SlowFlickerWorld(FakeWorld):
    """The room flips and holds each value for two ticks - long enough to 'settle' - while the character cannot move."""

    def __init__(self, clock):
        super().__init__(clock)
        self.flips = 0

    def act(self, action, deadline):
        x, z = list(self.pos)
        super().act(action, deadline)
        self.pos = [x, z]                         # pinned: the inputs move nothing
        self.flips += 1
        if self.flips % 2 == 0:
            self.room = 11 if self.room == 10 else 10


def test_a_settled_room_only_counts_when_the_character_moved(workdir):
    """Room 10/8 boundary: the value settles on each side while the character is pinned. Counting that as progress kept
    every clock alive and the bot sat in place for a whole run (347 actions, 60 s at (604,-151))."""
    clock = FakeClock()
    world = SlowFlickerWorld(clock)
    world.entities = [entity("TObjDoorKey", "80DB5650", 200.0, 0.0)]
    box = automaton(world, workdir, bounds=B.Bounds(max_no_close_s=4.0))
    box.run_for(20.0)

    assert box.watchdog.progress_kind != "room", "a settled room with no movement is not progress"


def test_a_room_that_settles_is_progress(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TObjDoorKey", "80DB5650", 200.0, 0.0)]
    box = automaton(world, workdir, bounds=B.Bounds(max_no_close_s=6.0))
    room = {"value": 10}

    def act(action, deadline, _act=world.act):
        _act(action, deadline)
        room["value"] = 11 if box.ticks > 2 else 10
        world.room = room["value"]

    world.act = act
    box.run_for(10.0)
    assert box.room == 11, "a room held for two ticks is a real transition"


def test_no_objective_progress_for_the_limit_ends_the_run_with_a_fixture(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TLazerFenceSw", "80DAD5C0", 40.0, 0.0)]
    # A long no-close budget isolates the objective-progress deadline: this test is about the second clock.
    box = automaton(world, workdir, bounds=B.Bounds(max_objective_s=2.0, max_no_close_s=1000.0))
    box.run_for(60.0)

    assert box.stopped
    assert "without progress" in box.stopped
    assert (workdir / "failure.json").exists()


def test_the_watchdog_does_not_treat_rotation_as_liveness():
    """Every blocked tap in the plaza still rotated the character ~90 degrees, so rotation cannot mean "alive".

    Measured: 138 taps at a railing, every one reported `moved 0.0`, every one rotated the character, and the
    watchdog counted zero stalls because rotating was treated as liveness. Translation is the only signal.
    """
    watchdog = B.Watchdog(stall_s=5.0)
    still = {"x": 0.0, "z": 0.0, "heading_deg": 0.0}
    assert watchdog.observe(still, 1000.0) is None
    assert watchdog.observe({**still, "heading_deg": 90.0}, 1001.0) is None, "first sample sets the baseline"
    assert watchdog.observe({**still, "heading_deg": 180.0}, 1003.0) is None, "still short of stall_s"
    stall = watchdog.observe({**still, "heading_deg": 270.0}, 1006.0)
    assert stall is not None, "a character turning in place without translating is stuck"
    assert watchdog.stalls == 1


def test_no_player_tick_presses_nothing(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.observe = lambda: {"player": {}, "entities": []}
    box = automaton(world, workdir)
    tick = box.tick()
    assert tick.outcome == "no-player"
    assert world.actions == []


# ---------------------------------------------------------------------------------------------------------------------
# Progression order and container starvation
# ---------------------------------------------------------------------------------------------------------------------
def test_the_policy_sticks_to_its_current_objective_when_a_rival_is_the_same_rank(workdir):
    """Two doors at similar range must not swap every tick: each swap re-planned the route (measured at 1 tick/s)."""
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TLazerFenceSw", "doorA", 100.0, 0.0), entity("TLazerFenceSw", "doorB", 101.0, 0.0)]
    policy = B.ProgressionPolicy()
    first = policy.choose(world.observe() and B.snapshot(world.observe()), clock.now())
    assert first.ptr == "doorA"
    world.pos = [5.0, 0.0]                     # now doorB is nearer
    second = policy.choose(B.snapshot(world.observe()), clock.now())
    assert second.ptr == "doorA", "a same-rank rival must not steal the objective"


def test_a_verified_switch_is_never_targeted_again(workdir):
    """Verification is permanent for the session: the demote window compared a persisted timestamp against a
    monotonic clock, so a switch verified at t=1e6 became 'due' again once 60 s of monotonic time had passed, and the
    bot walked 111 units back to a switch whose flag bit was already set."""
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TObjDoorKey", "80DB5650", 40.0, 0.0)]
    policy = B.ProgressionPolicy()
    snap = B.snapshot(world.observe())
    assert policy.choose(snap, 1000.0).kind == "switch"
    later = policy.choose(snap, 1000.0 + 3600.0, pressed={"80DB5650": 1000.0})
    assert later is None, "a switch whose flag changed is done, however long ago that was"


def test_a_door_is_a_passage_not_an_objective(workdir):
    """Making a door an objective ping-ponged the character through it (280 ticks around one door): it crossed, the
    aim-past point was then behind it, and it crossed back. Doors are crossed by routes; only switches are goals."""
    world = FakeWorld(FakeClock())
    world.entities = [entity("TObjDoor", "doorA", 20.0, 0.0), entity("TLazerFenceSw", "keyA", 300.0, 0.0)]
    snapshot = B.snapshot(world.observe())
    objective = B.ProgressionPolicy(door_state={"doorA": "open"}).choose(snapshot, 1000.0)
    assert objective.kind == "switch", "a door is never a destination, even when it is known to be open"
    only_door = B.snapshot(FakeWorld(FakeClock()).observe() | {"entities": [entity("TObjDoor", "doorB", 20.0, 0.0)]})
    assert B.ProgressionPolicy().choose(only_door, 1000.0) is None, "a room with only a door has no objective"


def test_an_anchor_inside_the_margin_is_skipped_not_ground_on(workdir):
    """A grid cell in the eroded margin can be unreachable from the character's side, and the follower used to grind on
    it until the run failed ("still 13 units away" for 20 s, room 8). It now gives an anchor a fixed patience and moves
    on."""

    class Router:
        def __init__(self, points):
            self.points = points

        def route(self, start, goal):
            return list(self.points)

    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (40.0, 0.0)]
    follower = B.RouteFollower(Router(points), arrive=6.0, spacing=0.0, anchor_patience=3)
    # The character sits at the first anchor and never moves: the second anchor is 10 away and can never be reached.
    seen = []
    for _ in range(12):
        point = follower.waypoint({"x": 0.0, "z": 0.0}, (40.0, 0.0))
        seen.append(point)
    assert follower.skipped >= 1, "the unreachable anchor is given up on"
    assert seen[-1] != (10.0, 0.0), "and the follower is no longer aiming at it"


def test_a_switch_outranks_a_nearer_container(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TObjContainerItem", "80DAD830", 8.0, 0.0, kind="object"),
                      entity("TLazerFenceSw", "80DADF10", 60.0, 0.0)]
    box = automaton(world, workdir)
    objective = box.policy.choose(box._observe(), clock.now())
    assert objective.kind == "switch", "the dependency chain outranks loot even when the loot is closer"


def test_containers_are_optional_and_cannot_starve_progression(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TObjContainerItem", "80DAD830", 8.0, 0.0, kind="object")]
    box = automaton(world, workdir, motion=B.VectorMotion(arrive=10.0))
    box.run_for(40.0)

    chosen = [entry["extra"]["objective"]["kind"] for entry in _entries(box)
              if entry["kind"] == "tick" and entry["extra"].get("objective")]
    assert "container" in chosen, "loot is allowed when nothing in the chain is reachable"
    assert box.policy.optional_streak >= box.policy.optional_limit
    late = [entry for entry in _entries(box)[-6:] if entry["kind"] == "tick"]
    assert all(entry["extra"]["objective"] is None for entry in late), \
        "after the optional budget the controller explores instead of farming containers"


def test_an_enemy_wave_outranks_a_switch_and_a_warp_outranks_both(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TObjEneBeast", "80DB6F40", 20.0, 0.0, kind="enemy", hp=40.0),
                      entity("TLazerFenceSw", "80DADF10", 15.0, 0.0),
                      entity("TObjWarpForest", "80DB7000", 200.0, 0.0)]
    box = automaton(world, workdir)
    assert box.policy.choose(box._observe(), clock.now()).kind == "warp"
    del world.entities[2]
    assert box.policy.choose(box._observe(), clock.now()).kind == "wave"
    del world.entities[0]
    assert box.policy.choose(box._observe(), clock.now()).kind == "switch"


# ---------------------------------------------------------------------------------------------------------------------
# Switch causality: a press is recorded with the flag delta, and "no change" is reported as such
# ---------------------------------------------------------------------------------------------------------------------
def test_switch_press_records_the_stage_flag_delta(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TLazerFenceSw", "80DADF10", 10.0, 0.0)]
    box = automaton(world, workdir)
    tick = box.tick()

    assert tick.objective.kind == "switch"
    assert tick.action.kind == "press" and tick.action.key == "a"
    entry = [row for row in _entries(box) if row["kind"] == "tick"][-1]
    assert entry["extra"]["flag_access"] is True
    assert entry["delta"]["stage_flags"][0] != entry["delta"]["stage_flags"][1], \
        "the flag array must actually differ across the press"
    raw_before, raw_after = world.flag_reads[0], world.flag_reads[1]
    changed = E.changed_bits(raw_before, raw_after)
    assert changed["turned_on"] == [{"group": 3, "index": 21}]
    assert "80DADF10" in box.pressed, "a verified press is what marks a switch done - not the press itself"
    assert "80DADF10" in box.switch_ok


def test_a_press_waits_for_the_flag_write_instead_of_counting_a_false_miss(workdir):
    """The flag write lands a frame or two after the input; the verifier must wait for it.

    Measured live: the press that set Forest 1 bit 7 was read as three attempts because the array still matched the
    pre-press digest 0.12 s later. Two such false misses would have ended a switch that had actually worked.
    """
    clock = FakeClock()
    world = FakeWorld(clock)
    world.switch_delay = 3              # the flag appears only on the third read after the press
    world.entities = [entity("TLazerFenceSw", "80DADF10", 10.0, 0.0)]
    box = automaton(world, workdir)
    box.tick()

    assert box.switch_ok == {"80DADF10"}, "the verifier must see the late flag write as success"
    assert box.switch_misses == {}
    assert box.switch_presses["80DADF10"] == 1


def test_a_switch_that_changes_nothing_is_reported_as_no_change(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.switch_works = False
    world.entities = [entity("TLazerFenceSw", "80DADF10", 10.0, 0.0)]
    box = automaton(world, workdir)
    box.tick()

    entry = [row for row in _entries(box) if row["kind"] == "tick"][-1]
    assert entry["delta"]["stage_flags"][0] == entry["delta"]["stage_flags"][1], \
        "pressing A is not evidence of a flag change, and the ledger must say so"
    assert box.switch_misses["80DADF10"] == 1
    assert "80DADF10" not in box.switch_ok


def test_a_switch_that_never_changes_a_flag_ends_in_a_named_fixture(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.switch_works = False
    world.entities = [entity("TLazerFenceSw", "80DADF10", 10.0, 0.0)]
    box = automaton(world, workdir)
    box.run_for(30.0)

    assert box.stopped, "three unverified presses must stop the run, not become a habit"
    assert "no stage-flag bit changed" in box.stopped
    assert box.switch_presses["80DADF10"] == box.bounds.max_switch_attempts
    fixture = json.loads((workdir / "failure.json").read_text(encoding="utf-8"))
    assert "80DADF10" in fixture["reason"]


def test_an_unverifiable_switch_is_never_claimed_as_success(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.entities = [entity("TLazerFenceSw", "80DADF10", 10.0, 0.0)]
    box = automaton(world, workdir, flag_address=None)      # this world cannot read the flag array

    for _ in range(box.bounds.max_switch_attempts + 2):
        box.tick()

    assert box.switch_ok == set()
    assert "80DADF10" not in box.switch_ok
    assert box.switch_presses["80DADF10"] >= box.bounds.max_switch_attempts
    assert "80DADF10" in box.pressed, "an unverifiable switch is set aside rather than pressed forever"


# ---------------------------------------------------------------------------------------------------------------------
# Combat: three spaced presses, verified by HP; unkillable targets are abandoned
# ---------------------------------------------------------------------------------------------------------------------
def test_a_combo_is_three_spaced_presses_verified_by_enemy_hp(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.attack_damage = 9.0
    world.entities = [entity("TObjEneBeast", "80DB6F40", 5.0, 0.0, kind="enemy", hp=200.0)]
    box = automaton(world, workdir, bounds=B.Bounds(max_objective_ticks=200))
    box.run_for(6.0)

    presses = [action for _, action in world.log if action.kind == "press" and action.key == "a"]
    assert len(presses) >= 3
    times = [when for when, action in world.log if action.kind == "press" and action.key == "a"]
    gaps = [round(b - a, 2) for a, b in zip(times, times[1:])]
    assert any(gap >= box.combat.gap_s for gap in gaps), "the combo must respect the cancel window gap"
    assert box.combat.attempts >= 1
    assert box.combat.hits >= 1
    assert box.combat.stage_transitions == 0, "no action-state reader in this world, so none may be claimed"


def test_an_enemy_that_takes_no_damage_is_abandoned_after_bounded_attempts(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.attack_lands = False
    world.entities = [entity("TObjEneBeast", "80DB6F40", 5.0, 0.0, kind="enemy", hp=200.0)]
    box = automaton(world, workdir, bounds=B.Bounds(max_objective_ticks=200))
    box.run_for(25.0)

    assert box.combat.attempts >= box.combat.whiff_limit
    assert "80DB6F40" in box.avoid, "a target that cannot be hurt is avoided, not swung at forever"
    objective = box.policy.choose(box._observe(), clock.now(), pressed=box.pressed, avoid=box.avoid)
    assert objective is None or objective.ptr != "80DB6F40"


# ---------------------------------------------------------------------------------------------------------------------
# Motion reaches a target even while the camera turns; a door is crossed, not pressed
# ---------------------------------------------------------------------------------------------------------------------
def test_vector_motion_closes_on_a_switch_and_presses_it_in_range(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 60.0, 20.0)]
    box = automaton(world, workdir, motion=B.VectorMotion(arrive=10.0, step_s=0.4),
                    bounds=B.Bounds(max_objective_ticks=200))
    box.run_for(40.0)

    assert box.switch_ok == {"80DADF10"}, "the switch should have been reached and its flag change verified"
    entry = [row for row in _entries(box) if row["kind"] == "tick" and row["extra"].get("flag_access")][-1]
    assert entry["delta"]["stage_flags"][0] != entry["delta"]["stage_flags"][1]
    assert box.overruns == 0


def test_a_door_is_walked_through_and_the_room_change_is_the_progress(workdir):
    clock = FakeClock()
    world = FakeWorld(clock)
    world.door = (30.0, 0.0)
    world.entities = [entity("TObjDoor", "80DAD5C0", 30.0, 0.0)]
    box = automaton(world, workdir, policy=_FixedWalk((30.0, 0.0), kind="door"),
                    motion=B.HeadingMotion(arrive=10.0))
    for _ in range(80):
        box.tick()
        if world.room != 1:
            break
    box.flush()          # the crossing movement is measured by the next read, so conclude it before asserting

    assert world.room == 2, "walking into the door must change the room; pressing A is not the mechanism"
    assert any(entry["kind"] == "tick" and entry["delta"]["room"] == [1, 2] for entry in _entries(box))
    presses = [action for action in world.actions if action.kind == "press"]
    assert presses == [], "a door is not an A-press interaction"


class StraightRouter:
    """A router that places a waypoint every 5 units along the line: enough to exercise following and re-planning."""

    def __init__(self, *, offset=0.0):
        self.calls = []
        self.offset = offset

    def route(self, start, goal):
        self.calls.append((tuple(start), tuple(goal)))
        dx, dz = goal[0] - start[0], goal[1] - start[1]
        length = math.hypot(dx, dz)
        steps = max(2, int(length / 5.0))
        return [(start[0] + dx * i / steps + self.offset, start[1] + dz * i / steps) for i in range(1, steps + 1)]


def test_a_routed_waypoint_never_makes_a_distant_switch_look_reachable(workdir):
    """A route waypoint 8 units ahead must not be mistaken for the switch 70 units away.

    Measured live in Forest 1: the routed policy pressed `TObjDoorKey` at tick 3 because the first waypoint was close,
    while the switch itself was 70 units away, and three presses from there changed no flag.
    """
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TObjDoorKey", "80DB54C0", 120.0, 0.0)]
    router = StraightRouter()
    box = automaton(world, workdir, policy=B.RoutedPolicy(_ProgressionWrapper(), router, arrive=10.0),
                    motion=B.VectorMotion(arrive=6.0, primitive="tap"),
                    bounds=B.Bounds(max_objective_ticks=400))
    for _ in range(3):
        box.tick()

    presses = [action for _, action in world.log if action.kind == "press" and action.key == "a"]
    assert presses == [], "the switch is 120 units away: the first three ticks must walk, not press"
    assert box.switch_presses == {}


class _ProgressionWrapper:
    """The real progression policy, with the switch as the only candidate."""

    def __init__(self):
        self.policy = B.ProgressionPolicy()

    @property
    def press_range(self):
        return self.policy.press_range

    @property
    def attack_range(self):
        return self.policy.attack_range

    def choose(self, snap, now, *, pressed=None, avoid=None):
        return self.policy.choose(snap, now, pressed=pressed, avoid=avoid)

    def note(self, kind, progressed):
        self.policy.note(kind, progressed)


def test_a_routed_policy_follows_waypoints_instead_of_a_straight_line(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    router = StraightRouter()
    box = automaton(world, workdir, policy=B.RoutedPolicy(_FixedWalk((80.0, 0.0)), router, arrive=6.0),
                    motion=B.VectorMotion(arrive=6.0, primitive="tap"),
                    bounds=B.Bounds(max_objective_ticks=400))
    box.run_for(40.0)

    assert router.calls, "the policy must ask the router for a route"
    assert math.hypot(80.0 - world.pos[0], world.pos[1]) <= 12.0, \
        f"the follower should reach the goal (at {world.pos[0]:.0f},{world.pos[1]:.0f})"


def test_carving_a_doorway_turns_a_static_wall_into_a_passage():
    """The disc's collision mesh has every door closed, so a doorway is wall in the static grid.

    Two rooms, a solid wall between them, and a door in the wall: the route is impossible until the doorway is carved,
    and after carving it crosses exactly there.
    """
    cell = 2.5
    cells = {(x, z) for x in range(0, 20) for z in range(0, 40)} | \
            {(x, z) for x in range(22, 42) for z in range(0, 40)}
    router = _GridRouter(cells, cell)
    assert router.route((25.0, 50.0), (75.0, 50.0), limit=50000) is None, "the wall blocks the route"

    carved = B.carve_doorways(cells, [(55.0, 50.0)], radius=6.0, cell=cell)
    router = _GridRouter(carved, cell)
    route = router.route((25.0, 50.0), (75.0, 50.0), limit=50000)
    assert route, "carving the doorway must open the route"
    crossed = any(abs(point[0] - 55.0) <= 8.0 for point in route)
    assert crossed, "the route must pass through the carved doorway"


class _GridRouter:
    """A tiny 4-neighbour A* over integer cells, enough to prove a passage exists."""

    def __init__(self, cells, cell=2.5):
        self.safe = {(int(x), int(z)) for x, z in cells}
        self.cell = cell

    def _nearest(self, point):
        base = (int(math.floor(point[0] / self.cell)), int(math.floor(point[1] / self.cell)))
        best = None
        for radius in range(1, 20):
            for dx in range(-radius, radius + 1):
                for dz in (-radius, radius):
                    for candidate in ((base[0] + dx, base[1] + dz), (base[0] + dz, base[1] + dx)):
                        if candidate in self.safe:
                            distance = math.hypot(candidate[0] - base[0], candidate[1] - base[1])
                            if best is None or distance < best[0]:
                                best = (distance, candidate)
            if best:
                return best[1]
        return None

    def route(self, start, goal, limit=50000):
        start_cell, goal_cell = self._nearest(start), self._nearest(goal)
        if start_cell is None or goal_cell is None:
            return None
        frontier = [start_cell]
        came = {start_cell: None}
        while frontier and len(came) < limit:
            current = frontier.pop(0)
            if current == goal_cell:
                path = [current]
                while came[path[-1]] is not None:
                    path.append(came[path[-1]])
                return [((x + 0.5) * self.cell, (z + 0.5) * self.cell) for x, z in reversed(path)]
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = (current[0] + dx, current[1] + dz)
                if neighbour in self.safe and neighbour not in came:
                    came[neighbour] = current
                    frontier.append(neighbour)
        return None


def test_route_following_advances_only_when_the_current_anchor_is_reached(workdir):
    """The anchor must not move because a *nearer* waypoint exists; it moves on arrival. The nearest-waypoint rule
    oscillated: 167 ticks ending 381 units from a target it started 390 away from."""
    route = [(float(x), 0.0) for x in range(0, 61, 2)]
    follower = B.RouteFollower(type("R", (), {"safe": set(), "route": lambda self, a, b: route})(),
                              arrive=5.0, spacing=12.0)
    goal = (60.0, 0.0)
    assert follower.waypoint({"x": 0.0, "z": 0.0}, goal) == (12.0, 0.0), "resampled to 12-unit anchors"
    assert follower.waypoint({"x": 13.0, "z": 0.0}, goal) == (24.0, 0.0), "advance exactly one anchor, no jumping"
    assert follower.waypoint({"x": 30.0, "z": 0.0}, goal) == (36.0, 0.0), "the next anchor, not the nearest one"
    assert follower.waypoint({"x": 59.0, "z": 0.0}, goal) is None, "the goal itself ends the route"


def test_a_blocked_leg_is_replanned_rather_than_pushed(workdir):
    router = StraightRouter()
    follower = B.RouteFollower(router, arrive=6.0, replan_after=2)
    player = {"x": 0.0, "z": 0.0}
    follower.waypoint(player, (60.0, 0.0))
    assert follower.plans == 1
    follower.note_progress(False)
    follower.note_progress(False)
    assert follower.stalls >= 2, "the follower must notice that it is not closing"
    follower.replan(player)
    assert follower.plans == 2, "a blocked leg must produce a new route, not a longer push"
    assert len(router.calls) == 2


def test_motion_can_use_the_calibrated_tap_primitive_and_never_holds_a_key(workdir):
    """A tap is one job, self-releasing, and its distance does not depend on release latency.

    Measured live 2026-11-13: every direction tap moved 7.8-8.0 units, while a 0.30 s hold moved 38.9 units because
    the release job landed about a second later. So the tap is the predictable primitive, and movement must not hold.
    """
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 48.0, 0.0)]
    box = automaton(world, workdir, motion=B.VectorMotion(arrive=6.0, primitive="tap"),
                    bounds=B.Bounds(max_objective_ticks=200))
    box.run_for(30.0)

    moves = [action for _, action in world.log if action.key in B.DIRECTIONS]
    assert moves, "the controller must move"
    assert all(action.kind == "press" for action in moves), "tap motion must never hold a direction key"
    assert box.switch_ok == {"80DADF10"}


def test_relative_motion_converges_in_a_turn_and_step_world(workdir):
    """The character faces the way it moves, so the controller steers from its last displacement.

    This is the shape the live city walk failed in: 138 taps that ended 244 units from a 230-unit target, because a
    world-frame key table goes stale as the character turns. The relative controller keeps facing = last movement.
    """
    clock = FakeClock()
    world = FakeWorld(clock, mode="tank")
    for x, z in ((60.0, 40.0), (-50.0, 70.0), (30.0, -60.0)):
        world.pos = [0.0, 0.0]
        world.facing = 0.0
        motion = B.RelativeTapMotion(arrive=6.0, turn_deg={"left": -45.0, "right": 45.0})
        for _ in range(60):
            action = motion.step(world.observe()["player"], (x, z), "test")
            if action is None:
                break
            before = world.observe()["player"]
            world.act(action, clock.now() + 3.0)
            motion.learn(action, before, world.observe()["player"])
        remaining = math.hypot(x - world.pos[0], z - world.pos[1])
        assert remaining <= 10.0, f"target ({x},{z}) left {remaining:.1f} units away"


def test_relative_motion_uses_the_character_frame_not_a_world_table(workdir):
    """In a camera-relative world the same key changes world direction as the character turns.

    `RelativeTapMotion` is built for that world; `VectorMotion` is the fixed-vector model and is tested separately.
    """
    clock = FakeClock()
    world = FakeWorld(clock, mode="tank")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 50.0, 0.0)]
    box = automaton(world, workdir, motion=B.RelativeTapMotion(arrive=6.0),
                    bounds=B.Bounds(max_objective_ticks=200))
    box.run_for(40.0)

    assert box.switch_ok == {"80DADF10"}
    moves = [action for _, action in world.log if action.key in B.DIRECTIONS]
    assert moves and all(action.kind == "press" for action in moves)


class ShiftingWorld(FakeWorld):
    """A world whose key mapping changes every few taps: the camera-following frame that caused the 1,050-unit orbit."""

    def __init__(self, clock, **kwargs):
        super().__init__(clock, mode="vector", **kwargs)
        self.log_every = 3
        self.taps = 0
        self.rotation = 0

    def act(self, action, deadline):
        if action.kind == "press" and action.key in B.DIRECTIONS:
            self.taps += 1
            if self.taps % self.log_every == 0:
                self.rotation = (self.rotation + 90) % 360
        super().act(action, deadline)

    def _move(self, key, seconds):
        vectors = {"up": (0.0, 1.0), "down": (0.0, -1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}
        dx, dz = vectors[key]
        radians = math.radians(self.rotation)
        rdx = dx * math.cos(radians) - dz * math.sin(radians)
        rdz = dx * math.sin(radians) + dz * math.cos(radians)
        step = self.speed * seconds
        self.pos[0] += rdx * step
        self.pos[1] += rdz * step


def test_commit_motion_learns_a_rotating_frame_and_gets_there(workdir):
    """The key -> direction map rotates while walking (the camera snaps on every move), so a motion must learn it live.

    The world here rotates the mapping by 90 degrees every 12 taps and blocks one direction with a wall; the committing
    motion still reaches the target, because it re-learns each key's direction from the displacement it just saw.
    """
    frame = {"rot": 0}

    def effect(key, rot):
        base = {"up": (0.0, 8.0), "down": (0.0, -8.0), "left": (-8.0, 0.0), "right": (8.0, 0.0)}[key]
        return B._rotate_world(base[0], base[1], rot)

    def travel(motion, limit=400):
        pos = [0.0, 0.0]
        seen = 0
        for _ in range(limit):
            action = motion.step({"x": pos[0], "z": pos[1]}, (0.0, 120.0))
            if action is None:
                return tuple(pos)
            seen += 1
            if seen % 12 == 0:
                frame["rot"] = (frame["rot"] + 90) % 360
            dx, dz = effect(action.key, frame["rot"])
            nxt = (pos[0] + dx, pos[1] + dz)
            if abs(nxt[0]) > 6.0:                       # a wall either side, leaving a corridor along z
                continue
            pos = [nxt[0], nxt[1]]
        return tuple(pos)

    got = travel(B.CommitMotion(arrive=6.0))
    assert math.dist(got, (0.0, 120.0)) <= 10.0, f"reached the target through a rotating frame, ended at {got}"


def test_wall_follow_steps_around_a_wall_where_hill_climb_grinds(workdir):
    """A wall dead ahead is not a gain-table problem: every key that closes the distance hits the wall, so the hill
    climber grinds in place - which is exactly what the bot did in Forest 1 room 4. The wall follower aims sideways for
    a few taps, then resumes the target."""
    effects = {"up": (8.0, 0.0), "down": (-8.0, 0.0), "left": (0.0, 8.0), "right": (0.0, -8.0)}

    def blocked(here, nxt):
        # A wall at x = 40 spanning z -20..20: east is blocked, north/south is free.
        return here[0] < 40.0 <= nxt[0] and -20.0 <= nxt[1] <= 20.0

    def travel(motion, limit=120):
        """The closest the motion gets to the target within `limit` taps (a wall can trap it far away)."""
        pos = [0.0, 0.0]
        best = math.dist(pos, (100.0, 0.0))
        for _ in range(limit):
            action = motion.step({"x": pos[0], "z": pos[1]}, (100.0, 0.0))
            if action is None:
                break
            dx, dz = effects[action.key]
            nxt = (pos[0] + dx, pos[1] + dz)
            if not blocked(tuple(pos), nxt):
                pos = [nxt[0], nxt[1]]
            best = min(best, math.dist(pos, (100.0, 0.0)))
        return best

    assert travel(B.HillClimbMotion(arrive=6.0)) > 20.0, "the wall leaves the hill climber short, as it did live"
    assert travel(B.WallFollowMotion(arrive=6.0, effects=effects)) <= 8.0, "the wall follower gets around it to the target"


def test_hill_climbing_finds_the_closing_key_when_the_frame_keeps_shifting(workdir):
    """The frame is unknowable here: the mapping rotates 90 degrees every three taps, so no inferred frame survives.

    The controller must instead notice that a key stopped closing and switch to one that does.
    """
    clock = FakeClock()
    world = ShiftingWorld(clock)
    motion = B.HillClimbMotion(arrive=6.0)
    for _ in range(120):
        action = motion.step(world.observe()["player"], (90.0, 40.0), "target")
        if action is None:
            break
        world.act(action, clock.now() + 3.0)
    remaining = math.hypot(90.0 - world.pos[0], 40.0 - world.pos[1])
    assert remaining <= 12.0, f"the hill climber should reach the target (at {remaining:.0f} units)"
    assert motion.switches >= 2, "it must have changed keys as the frame shifted"


def test_heading_motion_turns_with_bounded_taps_then_steps(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    world.entities = [entity("TLazerFenceSw", "80DADF10", 0.0, 60.0)]
    motion = B.HeadingMotion(arrive=10.0)
    action = motion.step(world.observe()["player"], (0.0, 60.0), "switch")
    assert action.kind == "hold" and action.key == "up", "already facing the target: take a step, do not turn"


# ---------------------------------------------------------------------------------------------------------------------
# Calibration: measure the primitives before trusting a motion model
# ---------------------------------------------------------------------------------------------------------------------
def test_calibration_measures_a_vector_key_build(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="vector")
    ledger = E.Ledger(workdir / "cal.jsonl", clock=clock.now, run="cal")
    calibration = B.calibrate(world, ledger=ledger, clock=clock)

    assert calibration.model == "vector", "four translating keys are a vector keypad, not a turn-and-step build"
    assert calibration.effects["up"] == (0.0, pytest.approx(8.0, abs=0.01))
    assert calibration.effects["right"] == (pytest.approx(8.0, abs=0.01), 0.0)
    assert calibration.speed > 0
    ok, why = ledger.verify()
    assert ok, why
    assert [entry["kind"] for entry in _entries(ledger) if entry["kind"] == "calibration"] == ["calibration"]
    assert _entries(ledger)[-1]["extra"]["model"] == "vector"


def test_calibration_recognises_a_turning_build(workdir):
    clock = FakeClock()
    world = FakeWorld(clock, mode="tank")
    calibration = B.calibrate(world, ledger=E.Ledger(workdir / "cal.jsonl", clock=clock.now))

    assert calibration.model == "heading", "left/right that only rotate are a turn-and-step build"
    assert calibration.effects["left"] == (0.0, 0.0) and calibration.effects["right"] == (0.0, 0.0)
    assert abs(calibration.turn["left"]) >= 12.0
    assert abs(calibration.turn["up"]) < 12.0


# ---------------------------------------------------------------------------------------------------------------------
# The live session adapter: a hold always ends released, even when the job outlives the tick
# ---------------------------------------------------------------------------------------------------------------------
def test_session_world_prefers_the_fast_input_queue_and_never_leaves_a_hold_down():
    """The app input queue answers in 15 ms; the job queue in ~1 s. A hold must still end with every key released."""
    posts, jobs = [], []

    def call(path, payload=None, method="GET", timeout=60):
        if path.endswith("/input"):
            posts.append(payload["events"])
            return {"queued": len(payload["events"])}
        if path == "/api/jobs":
            jobs.append(payload)
            return {"id": "job1"}
        return {}

    world = B.SessionWorld("abc-123", call, sleep=lambda seconds: None)
    world.act(B.hold("up", 0.3, "test hold"), deadline=time.monotonic() + 3.0)

    assert jobs == [], "the fast path must not fall back to a job when the queue accepted the input"
    assert posts[0] == [{"key": "Up", "down": True}], "pad names are translated to the keyboard keys the app presses"
    assert all(event["down"] is False for event in posts[-1]), "a hold always ends released"
    assert {event["key"] for event in posts[-1]} == {B.SessionWorld.PAD_TO_KEYBOARD[k] for k in B.DIRECTIONS}


def test_session_world_falls_back_to_the_job_queue_when_the_input_queue_refuses():
    jobs, releases = [], []

    def call(path, payload=None, method="GET", timeout=60):
        if path.endswith("/input"):
            return {"err": "Unsupported"}
        if path == "/api/jobs":
            events = payload["input"]["args"]["events"]
            job_id = f"job{len(jobs) + 1}"
            jobs.append({"id": job_id, "events": events})
            if all(not event["down"] for event in events):
                releases.append(events)
            return {"id": job_id}
        if path.startswith("/api/jobs/"):
            return {"state": "succeeded"} if path.endswith("job2") else {"state": "running"}
        return {}

    world = B.SessionWorld("abc-123", call, sleep=lambda seconds: None, poll_s=0.0)
    world.act(B.hold("up", 0.3, "test hold"), deadline=time.monotonic() + 0.05)

    assert jobs[0]["events"] == [{"key": "Up", "down": True}], "the job path carries the same translated key"
    assert releases and all(event["down"] is False for event in releases[-1])
    assert world.job_sent >= 1


# ---------------------------------------------------------------------------------------------------------------------
# Evidence: deterministic snapshots and a tamper-evident ledger
# ---------------------------------------------------------------------------------------------------------------------
def _entries(box):
    path = box.ledger.path if hasattr(box, "ledger") else box.path
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_snapshot_is_deterministic_and_independent_of_entity_order():
    state = {"player": {"ptr": "80DA62A0", "x": 1.23456, "z": -2.0, "room": 4, "hp": 76},
             "entities": [entity("TObjDoor", "80DAD5C0", 4.0, 5.0),
                          entity("TObjContainerItem", "80DAD830", 9.0, 8.0, kind="object")]}
    shuffled = {"player": dict(state["player"]),
                "entities": list(reversed(state["entities"]))}
    assert E.snapshot(state)["digest"] == E.snapshot(shuffled)["digest"]
    assert E.snapshot(state)["player"]["x"] == 1.235
    assert E.snapshot(state)["entities"]["gate"][0]["distance"] == round(math.hypot(4.0 - 1.235, 7.0), 3)


def test_ledger_is_hash_chained_and_detects_tampering(workdir):
    clock = FakeClock()
    ledger = E.Ledger(workdir / "l.jsonl", clock=clock.now)
    state = {"player": {"ptr": "80DA62A0", "x": 0.0, "z": 0.0, "room": 1},
             "entities": [entity("TObjDoor", "80DAD5C0", 1.0, 1.0)]}
    first = E.snapshot(state)
    state["player"]["x"] = 5.0
    second = E.snapshot(state)
    ledger.record("tick", action={"kind": "press", "key": "a"}, before=first, after=second, note="x")
    ledger.record("tick", action={"kind": "press", "key": "b"}, before=second, after=second, note="y")
    ok, why = ledger.verify()
    assert ok, why
    assert ledger.summary()["entries"] == 2

    lines = (workdir / "l.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["note"] = "the switch opened the door"
    lines[0] = E.canonical(tampered)
    (workdir / "l.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, why = ledger.verify()
    assert not ok and "hash" in why


def test_diff_reports_enemy_hp_room_and_flag_changes():
    before = E.snapshot({"player": {"ptr": "p", "x": 0.0, "z": 0.0, "room": 1},
                         "entities": [entity("TObjEneBeast", "e1", 3.0, 0.0, kind="enemy", hp=40.0)]})
    after = E.snapshot({"player": {"ptr": "p", "x": 6.0, "z": 0.0, "room": 2},
                        "entities": [entity("TObjEneBeast", "e1", 3.0, 0.0, kind="enemy", hp=31.0)]})
    delta = E.diff(before, after)
    assert delta["moved"] == 6.0
    assert delta["room"] == [1, 2]
    assert delta["enemies"][0]["hp"] == [40.0, 31.0] and delta["enemies"][0]["delta"] == -9.0
    assert delta["enemies"][0]["died"] is False

def test_step_motion_takes_attack_steps_and_refuses_a_lock_point():
    """The attack step is the fastest movement found (8.5 units per press), but it ignores walking collisions, so it
    has to be refused when the landing is a known lock point - (604,-151) in Forest 1 room 8 froze the character exactly
    that way after six presses with no movement and no heading change."""
    motion = B.StepMotion(arrive=6.0, lock_points=[(360.0, 100.0)], lock_radius=16.0)
    # heading 90 degrees is +x, so from (0,0) a step lands at (8.5, 0)
    north = {"x": 0.0, "z": 0.0, "heading_deg": 90.0}
    action = motion.step(north, (200.0, 0.0))
    assert action is not None and action.key == "a", "a clear step toward the target is taken"
    assert math.dist(motion.landing(north), (8.5, 0.0)) < 1e-6, "heading 90 degrees is +x"

    # a step that would land on the lock point is refused, and taps take over
    blocked = {"x": 351.5, "z": 100.0, "heading_deg": 90.0}
    action = motion.step(blocked, (600.0, 100.0))
    assert action is not None and action.key != "a", "the step that would land on (360,100) is refused"
    assert motion.refused == 1

    # once inside the arrive radius the motion stops
    assert motion.step({"x": 100.0, "z": 50.0, "heading_deg": 0.0}, (100.0, 44.0)) is None

def test_probe_motion_measures_then_moves_and_never_livelocks():
    """Four probes, then the key whose result came closest - the behaviour that crossed the plaza, where the committing
    motion wandered 187 units off its first waypoint."""
    effects = {"up": (0.0, 8.0), "down": (0.0, -8.0), "left": (-8.0, 0.0), "right": (8.0, 0.0)}
    motion = B.ProbeMotion(arrive=6.0)
    pos = [0.0, 0.0]
    keys = []
    for _ in range(80):
        action = motion.step({"x": pos[0], "z": pos[1]}, (40.0, 0.0))
        if action is None:
            break
        keys.append(action.key)
        if action.kind == "press":
            dx, dz = effects[action.key]
            pos[0] += dx
            pos[1] += dz
    assert math.dist(pos, (40.0, 0.0)) <= 6.0, f"the motion reaches its target, ended at {pos}"
    assert keys[:4] == ["up", "down", "left", "right"], "it measures all four directions first"
    assert keys.count("a") == 0


def test_probe_motion_holds_when_nothing_helps_instead_of_turning_forever():
    motion = B.ProbeMotion(arrive=6.0, hold_every=4)
    # a world where no key moves at all: the motion must turn, then hold, not spin
    kinds = []
    for _ in range(24):
        action = motion.step({"x": 0.0, "z": 0.0}, (100.0, 0.0))
        if action is None:
            break
        kinds.append(action.kind)
    assert "hold" in kinds, "a hold appears rather than an endless turn"
    assert motion.turns >= 3

def test_probe_motion_never_sends_the_same_direction_key_twice_in_a_row():
    """Measured: a repeated direction key is ignored (three `up` presses moved the character once), and a probe cycle
    ends by pressing the key it probed last, so the move was silently swallowed."""
    motion = B.ProbeMotion(arrive=2.0)
    keys = []
    for _ in range(12):
        action = motion.step({"x": 0.0, "z": 0.0}, (100.0, 0.0))
        if action is None:
            break
        keys.append(action.key)
    for a, b in zip(keys, keys[1:]):
        assert a != b, f"two {a} presses in a row: {keys}"
