"""RE5 Switch No Mercy survival (gbox.mercs.titles.re5_switch): the inventory read from RAM, the heal (PS3 rules: under
40 %, nobody within 4 m or under 25 % anyway; D-pad equip, use, confirmation, the gun back), the escape from a ring of
Majini through the widest gap, and the burst-then-back-off rhythm against a crowd in front."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch as R
from tests.test_re5_switch import round_guest

GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
SPRAY = {"slot": 5, "id": 0x304, "type": 3, "item": 0x04, "rounds": 1, "cap": 1, "grid": 7, "hand": False}


@pytest.fixture(autouse=True)
def _fresh_laser_caches(monkeypatch):
    for cache in (R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    monkeypatch.setattr(R, "HEAL_ENABLED", True)
    yield


def test_healing_stays_off_until_its_use_key_is_verified(monkeypatch):
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    b = R.Bot(stats={}, clock=lambda: 0.0)
    assert "tap" not in b.tick(snap(hp=200)) and b.stats["heal_starts"] == 0


def snap(hp=1000, enemies=(), inv=(GUN, SPRAY), rot=0.0, laser=None):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": rot, "hp": hp, "hp_max": 1000, "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": pos, "hp": 800, "hp_max": 800} for i, pos in enumerate(enemies)],
            "inventory": [dict(s) for s in inv], "laser": laser or {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def brain():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def test_the_inventory_is_read_from_the_player():
    g = round_guest()
    p = R.snapshot(g)["player"]["ptr"]
    for k, (idw, rounds, grid, hand) in enumerate([(0x201, 50, 0, 0), (0x102, 50, 3, 1), (0x304, 1, 7, 0),
                                                   (0x100, 0, 11, 0)]):
        slot = p + R.P_INV + R.INV_SLOT * k
        g.put(slot + R.INV_ID, struct.pack("<I", idw))
        g.put(slot + R.INV_ROUNDS, struct.pack("<ii", rounds, rounds))
        g.put(slot + R.INV_GRID, struct.pack("<ii", grid, hand))
    inv = R.snapshot(g)["inventory"]
    assert [(s["id"], s["type"], s["item"], s["rounds"], s["grid"], s["hand"]) for s in inv] == [
        (0x201, 2, 0x01, 50, 0, False), (0x102, 1, 0x02, 50, 3, True), (0x304, 3, 0x04, 1, 7, False)]   # 0x100: empty


def test_a_heal_equips_the_spray_uses_it_confirms_and_rearms():
    b, clock = brain()
    assert b.tick(snap(hp=300)) == {"tap": "ddown"} and b.stats["heal_starts"] == 1   # the spray from its D-pad slot
    clock[0] = 0.5
    in_hand = [dict(GUN, hand=False), dict(SPRAY, hand=True)]
    assert b.tick(snap(hp=300, inv=in_hand)) == {"tap": R.HEAL_USE_KEY}             # used
    clock[0] = 0.6
    assert b.tick(snap(hp=300, inv=in_hand)) == {"hold": ()}                        # the next press waits its gap
    clock[0] = 0.5 + R.HEAL_USE_EVERY_S
    assert b.tick(snap(hp=300, inv=in_hand)) == {"tap": R.HEAL_USE_KEY}
    clock[0] = 2.0
    used = [dict(GUN, hand=False)]                                                  # the spray is gone ...
    assert b.tick(snap(hp=1000, inv=used)) == {"tap": "dleft"}                     # ... the gun comes back
    assert b.stats["heals"] == 1 and b.stats["heal_status"] == "healed" and b.healing is None


def test_a_heal_waits_for_a_safe_moment_unless_critical():
    b, clock = brain()
    act = b.tick(snap(hp=350, enemies=[at(300, 0)]))                                # 35 %, one within 4 m: fight
    assert "tap" not in act and b.stats["heal_starts"] == 0 and "1 Majini within 4 m" in b.stats["heal_deferred"]
    b, clock = brain()
    assert b.tick(snap(hp=200, enemies=[at(300, 0)])) == {"tap": "ddown"}         # 20 %: heal anyway
    b, clock = brain()
    assert "tap" not in b.tick(snap(hp=500))                                      # 50 %: no heal


def test_a_heal_that_does_not_take_gives_up_and_rearms():
    b, clock = brain()
    b.tick(snap(hp=300))
    in_hand = [dict(GUN, hand=False), dict(SPRAY, hand=True)]
    for k in range(1, 20):
        clock[0] = 0.25 * k
        act = b.tick(snap(hp=300, inv=in_hand))
        if b.healing is None:
            break
    assert b.stats["heal_failures"] == 1 and act == {"tap": "dleft"}
    clock[0] += 0.1
    assert "tap" not in b.tick(snap(hp=300, inv=in_hand))                         # HEAL_RETRY_S before the next try


def test_a_ring_is_left_through_its_widest_gap():
    b, clock = brain()
    ring = [at(150, 10), at(150, 130), at(150, -110)]                              # 3 within 1.8 m, no gap of 150 deg
    act = b.tick(snap(enemies=ring, inv=()))
    assert b.stats["escapes"] == 1
    out = b.escape[0]
    gaps = sorted(math.degrees(R.wrap(x)) for x in (math.radians(70), math.radians(-170), math.radians(-50)))
    assert any(abs(math.degrees(out) - g) < 1 for g in gaps)                       # the middle of a gap
    assert act["hold"][:2] == R.RUN or act["hold"] == ("ldown",)                   # run, or the quick turn first
    b, clock = brain()
    open_side = [at(150, 0), at(150, 30), at(150, 60)]                             # a 300 deg gap: not a ring
    b.tick(snap(enemies=open_side, inv=()))
    assert b.stats["escapes"] == 0


@pytest.mark.parametrize("enemies,hp,escapes", [
    ([at(200, 10), at(200, 130), at(200, -110)], 1000, 0),                         # loose (3 within 2 m), healthy: fight
    ([at(200, 10), at(200, 130), at(200, -110)], 500, 1),                          # the same ring, hurt (50 %): escape
    ([at(230, 0), at(230, 90), at(230, 180), at(230, -90)], 1000, 1)])             # 4 within 2.5 m: tight
def test_only_a_tight_ring_or_a_hurt_player_escapes(enemies, hp, escapes):
    b, clock = brain()
    b.tick(snap(enemies=enemies, hp=hp, inv=()))
    assert b.stats["escapes"] == escapes


def test_escapes_are_capped_each_round():
    b, clock = brain()
    ring = [at(150, 10), at(150, 130), at(150, -110)]
    for k in range(40):
        clock[0] = k * (R.ESCAPE_GAP_S + R.ESCAPE_S + 1)
        b.escape = None
        b.quick, b.quick_at = 0, -1e9
        b.tick(snap(enemies=ring, inv=()))
    assert b.stats["escapes"] == R.ESCAPES_MAX


def test_an_escape_runs_for_its_time_then_fights_again():
    b, clock = brain()
    ring = [at(200, 0), at(200, 120), at(200, -120)]
    b.escape, b.escape_at = (math.radians(180), 1.2), 0.0
    clock[0] = 0.5
    act = b.tick(snap(enemies=ring, inv=(), rot=math.radians(180)))
    assert act["hold"][:2] == R.RUN                                                # still running out
    clock[0] = 1.3
    act = b.tick(snap(enemies=ring, inv=(), rot=math.radians(180)))
    assert b.escape is None and b.stats["escapes"] == 0                            # done; no new escape so soon


def test_a_crowd_in_front_gets_a_burst_then_a_back_off():
    b, clock = brain()
    crowd = [(0.0, 0.0, 180.0), (40.0, 0.0, 200.0)]                                # two in front within 2.2 m
    on = {"from": (0.0, 140.0, 40.0), "at": (0.0, 110.0, 170.0), "up": True}      # the dot on the first one
    b.tick(snap(enemies=crowd, inv=()))                                            # the gun comes up
    clock[0] = 0.3
    assert "zr" in b.tick(snap(enemies=crowd, inv=(), laser=on))["hold"]          # the burst begins
    clock[0] = 0.5
    off = dict(on, at=(-60.0, 110.0, 170.0))                                      # off him, inside the aim cone
    assert "zr" not in b.tick(snap(enemies=crowd, inv=(), laser=off))["hold"]     # between two targets: no pull ...
    clock[0] = 0.3 + R.BURST_S
    act = b.tick(snap(enemies=crowd, inv=(), laser=dict(on, at=(0.0, 111.0, 170.0))))
    assert act == {"hold": ("ldown",)} and b.stats["burst_backoffs"] == 1          # ... the burst still ends on time
    clock[0] += 0.2
    assert b.tick(snap(enemies=crowd, inv=()))["hold"][0] == "ldown"               # still backing off
