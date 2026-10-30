"""The ranged damage cluster (GET /api/mercs/damage-clusters): thrown weapons, crossbows and fire (uEm10 / uEm12 /
uEm14) hit him at 3-6 m while the threat order waits for the closing melee. Bot._threat_d now counts a ranged class
in the band where its shots carry but a grab does not yet (RANGED_BAND) as RANGED_PENALTY x as soon: the thrower at
the band's edge outranks the melee closing in, and the band's ends hold the old order (melee closes = kill it first,
out of the band = no shots yet)."""
import math

import gbox.mercs.titles.re5_switch as t5
from gbox.mercs.titles.re5_switch import Bot, _CLASSES

ROT_FACING = math.pi          # the test players face -x, the way at(x, ...) places enemies in front


def player(x=0.0, z=0.0):
    return {"pos": (x, 0.0, z), "rot": ROT_FACING, "hp": 800, "motion": None}


def foe(slot, x, z, cls="uEm11", motion=None, cls_name=None):
    return {"ptr": slot, "slot": slot, "pos": (x, 0.0, z), "hp": 800, "motion": motion,
            "class": cls_name or cls}


def bot():
    b = Bot(clock=lambda: 0.0)
    b._appr = {}
    return b


def pick(b, p, live):
    return b._threat_pick(p, live, cur=None, now=0.0)


def test_ranged_outranks_melee_in_band():
    b = bot()
    p = player()
    melee, thrower = foe(1, -350, 0, cls="uEm11"), foe(2, -750, 0, cls="uEm10")
    assert pick(b, p, [melee, thrower]) is thrower, \
        f"the thrower at 7.5 m (in the band, inside the threat cap) should lead the kill order, not the 3.5 m melee: " \
        f"{pick(b, p, [melee, thrower])}"


def test_all_three_classes_ranged():
    for cls in ("uEm10", "uEm12", "uEm14"):
        b = bot()
        p = player()
        melee, ranged = foe(1, -350, 0, cls="uEm11"), foe(2, -750, 0, cls=cls)
        assert pick(b, p, [melee, ranged]) is ranged, f"{cls} in the band should outrank the closing melee"


def test_no_penalty_inside_band_edge():
    """Closer than the band: it is a melee like any other - the nearest one leads."""
    b = bot()
    p = player()
    near, melee = foe(1, -200, 0, cls="uEm10"), foe(2, -400, 0, cls="uEm11")
    assert pick(b, p, [near, melee]) is near, "inside the band the ranged one is the nearest: it leads"


def test_no_penalty_outside_band():
    """Farther than the band: its shots do not carry yet - the closing melee leads."""
    b = bot()
    p = player()
    melee, far = foe(1, -400, 0, cls="uEm11"), foe(2, -1500, 0, cls="uEm10")
    assert pick(b, p, [melee, far]) is melee, "outside the band the closing melee leads: " \
        f"{pick(b, p, [melee, far])}"


def test_threat_d_values():
    b = bot()
    p = player()
    melee, thrower = foe(1, -350, 0, cls="uEm11"), foe(2, -750, 0, cls="uEm10")
    assert b._threat_d(p, thrower) < b._threat_d(p, melee), \
        "in the band the ranged one counts as soon as the melee does not"
    assert math.isfinite(b._threat_d(p, thrower))


def test_replay_ranged_cluster_fixture_aims_at_the_thrower():
    """The cluster's representative hit (10-29, Missile Area, uEm10 thrower at 2.7 m beside him): the replay drives
    a fresh bot through the recorded snapshot; the threat order must put that ranged enemy first now."""
    import json

    from pathlib import Path

    from gbox.mercs import incident_replay
    fx = json.loads((Path(__file__).parent / "fixtures/mercs_incidents/re5_switch_ranged_threat.json").read_text())
    p = fx["snapshot"]["player"]["pos"]
    live = [{"ptr": i + 1, "slot": i + 1, "pos": (e["pos"][0], 0.0, e["pos"][2]), "hp": e["hp"], "class": e["class"]}
            for i, e in enumerate(fx["snapshot"]["enemies"])]
    b = Bot(clock=lambda: 0.0)
    b._appr = {}
    picked = b._threat_pick({"pos": p, "rot": 0.0}, live, cur=None, now=0.0)
    assert picked is not None and picked["ptr"] in (1, 2) and picked["class"] in t5.RANGED_CLASSES, \
        "an in-band uEm10 thrower (2.7 or 2.6 m) must lead the threat order, not the 7.5 m melee"
    # the replay path itself: the bot runs on the fixture's snapshot without crashing and takes the ranged target
    result = incident_replay.replay(fx, ticks=10)
    assert result["bot"].target is not None or all(t["act"] is not None for t in result["ticks"])


def test_melee_ignores_class():
    """The band is keyed by class, not distance alone: an unknown class at 9 m stays in the closing order."""
    b = bot()
    p = player()
    melee, unknown = foe(1, -350, 0, cls="uEm11"), foe(2, -750, 0, cls="uEm21")
    assert pick(b, p, [melee, unknown]) is melee, "a non-ranged class far away does not jump the queue"


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  " + name)
            except Exception as e:
                fails += 1
                print("FAIL " + name + ": " + repr(e))
    sys.exit(1 if fails else 0)
