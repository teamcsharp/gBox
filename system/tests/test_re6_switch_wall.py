import math

import pytest

from gbox.mercs.titles import re6_switch as R


def setup(monkeypatch, doing="walk", hold=("lup",)):
    clock = [0.]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    state = {"mercenaries_phase": R.PHASE_PLAYING,
             "player": {"ptr": 123, "pos": (0., 0., 0.), "rot": 0., "hp": 900, "hp_max": 900,
                        "equipped": 0, "action": None}, "enemies": [], "bonuses": []}
    monkeypatch.setattr(bot, "_tick", lambda s, now: bot._go(doing, "test", {"hold": hold}, "test"))
    return bot, clock, state


def test_walk_turns_with_the_stick_and_never_calls_the_ram_writer(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    state["camera"] = {"yaw": 0.}
    state["aim_cam"] = {"addr": 1234, "pitch": 0.}
    writes = []
    bot.ram = lambda *args: writes.append(args) or True
    assert bot._walk_keys(state["player"], math.pi / 2, state) == ("rleft",)
    state["camera"]["yaw"] = math.pi / 2
    assert bot._walk_keys(state["player"], math.pi / 2, state) == ("lup",)
    bot.ram = None
    state["camera"]["yaw"] = 0.
    assert "lup" not in bot._walk_keys(state["player"], math.pi / 2, state)
    assert writes == []


def test_navigation_turns_pass_through_the_spin_governor(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    writes = []
    state.update(camera={"yaw": 0.}, aim_cam={"addr": 1234, "pitch": 0.})
    bot.ram = lambda *args: writes.append(args) or True
    monkeypatch.setattr(bot, "_tick", lambda s, now: bot._go("walk", "test",
                        {"hold": bot._walk_keys(s["player"], math.pi / 2, s)}, "test"))
    clock[0] = 1.
    bot._rot_prev = (.95, -math.pi / 2)
    assert bot.tick(state)["hold"] == ()
    assert bot.stats["whips"] == 1
    clock[0] += .08
    assert bot.tick(state)["hold"] == ("rleft",)
    assert writes == []


def test_final_forward_without_progress_is_released_and_failed_bonus_deferred(monkeypatch):
    bot, clock, state = setup(monkeypatch, doing="bonus")
    bot.run_target = 456
    for k in range(8):
        clock[0] = k * .08
        out = bot.tick(state)
    assert "lup" not in out["hold"]
    assert bot.stats["movement_blocks"] == 1 and bot.bonus_skip[456] > clock[0]
    assert bot.run_target is None and bot.stats.get("movement_recoveries", 0) == 0


def test_boosted_action_suppression_does_not_count_as_wall_pressure(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    state["player"]["action"] = next(iter(R.BOOSTED_ACTIONS))
    for k in range(12):
        clock[0] = k * .08
        assert "lup" not in bot.tick(state)["hold"]
    assert bot.stats.get("movement_blocks", 0) == 0


@pytest.mark.parametrize("doing,hold", [("held", ("a",)), ("prompt", ("y",)), ("tablet", ()),
                                       ("fire", ("zl", "zr")), ("bomb", ("ldown",))])
def test_emergency_or_combat_actions_interrupt_recovery(monkeypatch, doing, hold):
    bot, clock, state = setup(monkeypatch)
    for k in range(8):
        clock[0] = k * .08
        bot.tick(state)
    monkeypatch.setattr(bot, "_tick", lambda s, now: bot._go(doing, "test", {"hold": hold}, "test"))
    clock[0] += .08
    assert bot.tick(state) == {"hold": hold}
    assert bot.stats.get("movement_recoveries", 0) == 0


def test_known_no_route_does_not_become_direct_forward_pursuit(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    class Mesh:
        def path(self, start, goal):
            return None
    state["navmesh"] = Mesh()
    state["enemies"] = [{"ptr": 456, "pos": (0., 0., 1500.), "hp": 100}]
    assert bot._pursue(state["player"], state, 0.) is None
    assert bot._walk_skip[456] > 0.


def test_occluded_enemy_with_known_no_route_never_uses_blind_detour(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    class Mesh:
        def path(self, start, goal):
            return None
    enemy = {"ptr": 456, "pos": (0., 0., 1500.), "hp": 100}
    state.update(navmesh=Mesh(), enemies=[enemy])
    monkeypatch.setattr(bot, "is_blocked", lambda e, now: True)
    for name in ("_held_item", "_bonus_run", "_green_save", "_taunt", "_bomb", "_nade", "_crowd_control", "_bonus"):
        monkeypatch.setattr(bot, name, lambda *args: None)
    out = bot._decide(state["player"], [enemy], lambda e: 1500., enemy, 1500., state, 0.)
    assert "lup" not in out["hold"] and "lleft" not in out["hold"] and "lright" not in out["hold"]


def test_direct_bonus_run_faces_before_walking_without_a_mesh(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    state["bonuses"] = [{"ptr": 456, "pos": (1500., 0., 0.), "kind": "time"}]
    out = bot._bonus_run(state["player"], [], lambda e: 1500., state, 0.)
    assert "lup" not in out["hold"]
    state["player"]["rot"] = math.pi / 2
    out = bot._bonus_run(state["player"], [], lambda e: 1500., state, .08)
    assert "lup" in out["hold"]


@pytest.mark.parametrize("committed", [False, True])
def test_bonus_with_known_failed_route_is_deferred_without_forward(monkeypatch, committed):
    bot, clock, state = setup(monkeypatch)
    class Mesh:
        def path(self, start, goal):
            return None
    state.update(navmesh=Mesh(), bonuses=[{"ptr": 456, "pos": (0., 0., 1500.), "kind": "time"}])
    if committed:
        bot.run_target, bot.run_since = 456, 0.
    assert bot._bonus_run(state["player"], [], lambda e: 1500., state, 0.) is None
    assert bot.bonus_skip[456] > 0. and bot.run_target is None
    assert bot.stats["bonus_skips"] == 1


def test_real_displacement_is_required_for_recovery_and_resets_forward_effort(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    for k in range(12):
        clock[0] = k * .08
        state["player"]["pos"] = (0., 0., k * 5.)
        bot.tick(state)
    assert bot.stats.get("movement_blocks", 0) == 0
    for k in range(8):
        clock[0] += .08
        bot.tick(state)
    assert bot.stats["movement_blocks"] == 1 and bot.stats.get("movement_recoveries", 0) == 0
    state["player"]["pos"] = (20., 0., 55.)
    clock[0] += .08
    bot.tick(state)
    assert bot.stats["movement_recoveries"] == 1


def test_governor_suppressed_final_input_does_not_accumulate_wall_effort(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    monkeypatch.setattr(bot, "_govern", lambda s, out, now: {"hold": ()})
    for k in range(12):
        clock[0] = k * .08
        bot.tick(state)
    assert bot.stats.get("movement_blocks", 0) == 0


def test_failed_probe_has_fixed_turn_heading_and_does_not_claim_success(monkeypatch):
    bot, clock, state = setup(monkeypatch)
    for k in range(22):
        clock[0] = k * .08
        out = bot.tick(state)
    assert bot.stats.get("movement_recoveries", 0) == 0
    assert bot.stats["movement_recovery_failures"] == 1
    assert "lup" not in out["hold"]
    state["player"]["rot"] = math.pi
    clock[0] += .08
    out = bot.tick(state)
    assert not {"rleft", "rright"} & set(out["hold"])
