"""#9560: the RE4 never-stand step walks forward, it does not turn on the spot.

Operator 2026-11-10 on the RE4 first-room wall: "never stand step also rotates" - the stand-break step
(re4_walk.Walker.step) used to return pure-turn keys for every heading between the arc and the quick turn,
so the bot spun in place at the wall, one on-the-spot rotation per break, with no ground gained. The step now
walks while it turns: every stand-break pulse carries FORWARD (or BACK + RUN past the quick turn), so a stand
break always moves him along open floor.
"""
import math

from gbox.mercs.titles import re4_walk as W

EAST = math.pi / 2

FALLBACK = 7  # the fallback candidates around his facing: 0, -45, +45, -90, +90, -135, +135 degrees


def _walker(pos, rot=0.0, now=0.0):
    w = W.Walker({})
    w.observe({"player": {"pos": tuple(pos), "rot": rot, "hp": 1000, "hp_max": 1000}, "enemies": [],
               "nav": None, "timer": 90.0, "kills": 0, "combo": 0, "combo_timer": 0.0}, now)
    return w


def test_every_stand_break_step_moves_him_no_pure_turns():
    # No mesh (no open-floor probe) and no route point: step() falls back to cycling the turn candidates around
    # his facing. Old behaviour returned (turn,) - a spin with no ground - for every candidate past the arc;
    # the step now walks while it turns, so every stand-break key set carries a ground key.
    w = _walker((1000.0, 0.0, 2600.0), rot=EAST)
    for n in range(FALLBACK):
        keys = w.step()
        assert "lup" in keys or "ldown" in keys, f"stand break {n} stands and turns on the spot: {keys}"
        assert not set(keys) <= {"lleft", "lright"}, f"stand break {n} is a pure rotation: {keys}"


def test_the_moderate_turn_step_walks_while_it_turns():
    # Fallback candidate order (0, -45, +45, -90, +90, ...): the -90 and +90 candidates are the branch that used
    # to spin on the spot (a pure turn key, no ground gained).
    w = _walker((1000.0, 0.0, 2600.0), rot=EAST)
    assert w.step() == ("lup",)                # straight on: walk
    assert w.step() == ("lup", "lright")       # -45: the arc walks
    assert w.step() == ("lup", "lleft")        # +45
    assert w.step() == ("lup", "lright")       # -90: walk while turning (was ("lright",) - a spin)
    assert w.step() == ("lup", "lleft")        # +90: walk while turning (was ("lleft",) - a spin)


def test_the_stand_break_in_never_stand_carries_forward():
    # End to end through the backstop: stand still, no ground, the stand break fires and its hold moves him.
    w = W.Walker({})
    for k in range(9):
        w.observe({"player": {"pos": (1000.0, 0.0, 2600.0), "rot": EAST, "hp": 1000, "hp_max": 1000},
                   "enemies": [], "nav": None, "timer": 90.0, "kills": 0, "combo": 0, "combo_timer": 0.0}, 0.5 * k)
        act = w.never_stand({"hold": set()})
    assert w.stats["stand_breaks"] == 1
    assert {"lup", "ldown"} & set(act["hold"]), f"the stand break's hold does not move him: {act['hold']}"
    assert not set(act["hold"]) <= {"lleft", "lright"}
