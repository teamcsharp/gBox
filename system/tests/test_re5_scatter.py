"""The RE5 scatter barrage: a cone of native grenades toward the threats, nothing equipped.

No live game: the fake emulator from the class-pair tests records every native call and every position write, so the
geometry, the kinds, the explosive-kind safety floor and the receipt are all checked on synthetic memory.
"""
import math
import random

import pytest

from gbox.mercs import grenade_ring as RULE
from gbox.mercs.native.re5_ebffdb22 import classes as C
from gbox.mercs.titles import re5_switch_native as N
from test_re5_class_pair import EXPLODE, HAND_VT, SPAWN, ring_controller

P1 = (1000.0, 800.0, -2000.0)


def placements(ctl):
    """{unit: (x, y, z)} from the position writes the ring's relocation makes."""
    out = {}
    for at, data in ctl.writes:
        for unit in ctl.spawns:
            if at == unit + N.RING_UNIT_POS:
                out[unit] = struct_unpack(data)
    return out


def struct_unpack(data):
    import struct
    return struct.unpack("<3f", data)


def test_a_random_barrage_is_a_flash_cone_from_near_to_far_at_chest_height():
    ctl = ring_controller()
    toward = [(P1[0] + 900.0, P1[2])]                    # a threat due east
    result = ctl.grenade_scatter("random", count=5, toward=toward, rng=random.Random(7))
    assert result["state"] == "confirmed" and result["verified"] is True
    assert result["op"] == "grenade_scatter" and result["kind"] == "random"
    assert result["requested"] == 5 and result["detonated"] == 5
    assert result["kinds"] == ["flash"] and "probe" not in result
    assert result["self_damage"] == 0 and result["hp_before"] == result["hp_after"] == 1000
    assert result["axis_deg"] == pytest.approx(90.0, abs=0.5)       # east, in this heading convention
    placed = list(placements(ctl).values())
    assert len(placed) == 5
    assert all(y == pytest.approx(P1[1] + N.SCATTER_CHEST_CM, abs=0.01) for _x, y, _z in placed)
    dists = [math.hypot(x - P1[0], z - P1[2]) for x, _y, z in placed]
    assert min(dists) >= N.flash_place_min_cm() == 400.0             # checkpoint 0.3: a flash under 4 m can stun him
    assert dists == sorted(dists)                                    # near to far
    assert all(d <= result["far_cm"] + 300.0 for d in dists)
    # every round goes through the verified wrappers with the flash's own DTI
    spawns = [a for o, a in ctl.calls if o == SPAWN]
    assert all(args[2] == C.CLASSES["flash"].dti for args in spawns)


def test_an_explicit_class_is_the_probe_and_carries_its_class_arguments():
    ctl = ring_controller(unit_vtable=HAND_VT)
    result = ctl.grenade_scatter("hand", count=2, toward=[(P1[0] + 800.0, P1[2] + 100.0)], rng=random.Random(3))
    assert result["state"] == "confirmed" and result["probe"] is True
    assert result["kinds"] == ["hand"] and result["effect"] == "native_hand_scatter"
    spawns = [a for o, a in ctl.calls if o == SPAWN]
    assert all(args[2] == C.CLASSES["hand"].dti for args in spawns)
    detonations = [a for o, a in ctl.calls if o == EXPLODE]
    assert all(args[4] == ctl.base + HAND_VT and args[5] == 0x106 for args in detonations)


def test_an_explosive_probe_never_lands_inside_the_learned_reach():
    ctl = ring_controller(unit_vtable=HAND_VT)
    result = ctl.grenade_scatter("hand", count=3, toward=[(P1[0] + 500.0, P1[2])], safe_cm=1600.0,
                                 rng=random.Random(11))
    assert result["state"] == "confirmed"
    dists = [math.hypot(x - P1[0], z - P1[2]) for x, _y, z in placements(ctl).values()]
    assert dists and min(dists) >= 1600.0


def test_a_partial_barrage_is_never_reported_confirmed():
    ctl = ring_controller(spawn_fail_at=2)
    result = ctl.grenade_scatter("random", count=4, toward=[(P1[0] + 800.0, P1[2])], rng=random.Random(5))
    assert result["state"] == "uncertain" and result["verified"] is False
    assert result["detonated"] == 2 and result["requested"] == 4 and result["reason"]
    assert ctl.failed and ctl.recoverable


def test_an_unknown_kind_is_refused_before_any_native_call():
    ctl = ring_controller()
    with pytest.raises(N.Unavailable, match="unknown grenade kind"):
        ctl.grenade_scatter("nuke")
    assert ctl.calls == []


# --- checkpoint 0.2 / 0.3: no round lands inside its own blast --------------------------------------------------------

def test_a_flash_barrage_never_places_a_round_under_400_cm():
    """The operator: "never let the bot get stunned by their own flash grenades" - even with the threat at 120 cm."""
    ctl = ring_controller()
    result = ctl.grenade_scatter("random", count=4, toward=[(P1[0] + 120.0, P1[2])], rng=random.Random(9))
    assert result["state"] == "confirmed" and result["kinds"] == ["flash"]
    dists = [math.hypot(x - P1[0], z - P1[2]) for x, _y, z in placements(ctl).values()]
    assert min(dists) >= N.flash_place_min_cm() == 400.0
    assert result["floor_cm"] == 400.0 and result["floors_cm"]["flash"] == 400.0


def test_an_explosive_barrage_keeps_the_600_cm_ring_floor_without_a_learned_reach():
    """Checkpoint 0.2: the hand/incendiary probe used to be placed at 300 cm - inside its own blast."""
    ctl = ring_controller(unit_vtable=HAND_VT)
    result = ctl.grenade_scatter("hand", count=3, toward=[(P1[0] + 200.0, P1[2])], rng=random.Random(4))
    assert result["state"] == "confirmed" and result["kinds"] == ["hand"]
    dists = [math.hypot(x - P1[0], z - P1[2]) for x, _y, z in placements(ctl).values()]
    assert min(dists) >= N.RING_EXPLOSIVE_CLEAR_CM == 600.0
    assert result["floor_cm"] == 600.0 and result["floors_cm"]["explosive"] == 600.0


def test_the_rule_runs_on_re5_and_reads_its_own_knobs():
    assert "010018100CD46000" in RULE.SCATTER_TITLES

    class Title:
        SCATTER = False
        SCATTER_EVERY_S = 30.0
        SCATTER_N = 5
    pol = RULE.scatter_policy(Title())
    assert pol["enabled"] is False and pol["cooldown_s"] == 30.0 and pol["count"] == 5


def test_the_shared_hook_offers_re5_a_step():
    step = RULE.control(None, {"map_id": "010018100CD46000", "menus": "gbox.mercs.titles.re5_switch"})
    assert callable(step)
    assert RULE.control(None, {"map_id": "BLUS30491"}) is None          # no PS3 barrage: the rule is Switch work


def test_the_re5_automatic_barrage_is_on_under_the_flash_clock():
    """Checkpoint D: the barrage is back on, and every barrage it can draw is a flash, so it obeys FLASH_MIN_GAP_S."""
    from gbox.mercs.titles import re5_switch as R5
    assert R5.SCATTER is True
    assert R5.SCATTER_FLASH_ONLY is True
    assert R5.scatter_kinds() == ("flash",)
    policy = RULE.scatter_policy(R5)
    assert policy["enabled"] is True and policy["flash_only"] is True
    assert policy["flash_gap_s"] == R5.FLASH_MIN_GAP_S
    assert "010018100CD46000" in RULE.SCATTER_TITLES
    assert callable(getattr(N.Controller, "grenade_scatter", None))     # the probe route and the operator's button
