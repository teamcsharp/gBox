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
    assert recoveries and all(action.kind == "hold" for action in recoveries), \
        "the escape must be a hold: 40 taps moved 0.0 units in a corner where one 0.45 s hold moved 33"

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
    """A policy whose only objective is one coordinate."""

    def __init__(self, point):
        self.point = point

    def choose(self, snap, now, *, pressed=None, avoid=None):
        player = snap.get("player") or {}
        distance = math.hypot(self.point[0] - float(player.get("x") or 0),
                              self.point[1] - float(player.get("z") or 0))
        return B.Objective(0, "walk", self.point, distance, "coordinate", "", None, "walk target")

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

    assert box.room is None, "a room that alternates every tick must never settle into a transition"
    assert box.watchdog.progress_kind != "room"


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
    world.entities = [entity("TObjDoor", "80DAD5C0", 40.0, 0.0)]
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
    world.entities = [entity("TObjDoor", "doorA", 100.0, 0.0), entity("TObjDoor", "doorB", 101.0, 0.0)]
    policy = B.ProgressionPolicy()
    first = policy.choose(world.observe() and B.snapshot(world.observe()), clock.now())
    assert first.ptr == "doorA"
    world.pos = [5.0, 0.0]                     # now doorB is nearer
    second = policy.choose(B.snapshot(world.observe()), clock.now())
    assert second.ptr == "doorA", "a same-rank rival must not steal the objective"


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
    box = automaton(world, workdir, motion=B.HeadingMotion(arrive=10.0))
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
    assert posts[0] == [{"key": "up", "down": True}]
    assert all(event["down"] is False for event in posts[-1]), "a hold always ends released"
    assert {event["key"] for event in posts[-1]} == set(B.DIRECTIONS)


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

    assert jobs[0]["events"] == [{"key": "up", "down": True}]
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
