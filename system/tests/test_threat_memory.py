"""Who hurt the bot (gbox.mercs.threat_memory; operator 2026-11-10: "I am seeing the bot get hurt by the same threats
over and over. He should not be standing under a hammer who is charging up over and over in the same match"): each hit
put on the enemy that landed it, its class's attack motions and reach learned and kept across rounds and sessions, and
the RE5 Switch bot acting on it - the hammer's charge stepped out of, the one that hurt him shot first."""
import math

import pytest

from gbox.mercs import threat_memory as T
from gbox.mercs.titles import re5_switch as R

HAMMER, WALK, CHARGE = "uEm20", 4, 120


def row(i, pos, motion=WALK, hp=2000, cls=HAMMER, act=0):
    return {"ptr": 10 + i, "pos": pos, "hp": hp, "hp_max": 2000, "motion": motion, "act": act, "class": cls}


def at(dist, deg=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


ORIGIN = (0.0, 0.0, 0.0)


def charge_then_hit(tm, t0, dist=420.0, hp=(2000, 2000), other=True):
    """A hammer walks, begins CHARGE at t0, lands at t0 + 1.2; a town Majini walks beside him all along."""
    town = [row(1, at(250, 40), motion=WALK, cls="uEm10", hp=300)] if other else []
    tm.observe(t0 - 1.0, [row(0, at(dist), WALK, hp[0])] + town, ORIGIN)
    tm.observe(t0, [row(0, at(dist), CHARGE, hp[0])] + town, ORIGIN)
    tm.observe(t0 + 1.0, [row(0, at(dist), CHARGE, hp[1])] + town, ORIGIN)
    return tm.hurt(t0 + 1.2, ORIGIN, 300)


def test_the_hit_goes_on_the_one_that_began_its_attack_not_the_nearer_walker(tmp_path):
    tm = T.ThreatMemory(tmp_path / "t.json")
    rec = charge_then_hit(tm, 10.0)
    assert rec["attacker"] == 10 and rec["class"] == HAMMER and CHARGE in rec["motions"]
    assert tm.grudge(row(0, at(420))) == 1 and tm.grudge(row(1, at(250))) == 0
    assert tm.data["classes"][HAMMER]["hits"][str(CHARGE)] == 1


def test_one_hit_makes_the_charge_lethal_for_the_rest_of_the_round_and_two_for_good(tmp_path):
    path = tmp_path / "t.json"
    tm = T.ThreatMemory(path)
    charge_then_hit(tm, 10.0)
    assert tm.lethal(row(0, at(420), CHARGE)), "the same match: at once"
    assert not tm.lethal(row(0, at(420), WALK))
    tm.new_round()
    assert not tm.lethal(row(0, at(420), CHARGE)), "one hit is not yet a lesson for every round"
    charge_then_hit(tm, 50.0)
    tm.new_round()                                                   # saved at the round's start
    again = T.ThreatMemory(path)                                     # the next session
    assert again.lethal(row(5, at(400), CHARGE)) and not again.lethal(row(5, at(400), WALK))


def test_a_motion_seen_often_near_him_without_hits_is_not_learned(tmp_path):
    tm = T.ThreatMemory(tmp_path / "t.json")
    for k in range(20):                                              # the walk begins near him twenty times, harmless
        tm.observe(k * 2.0, [row(0, at(250), motion=7)], ORIGIN)
        tm.observe(k * 2.0 + 1.0, [row(0, at(250), motion=WALK)], ORIGIN)
    for t in (100.0, 200.0):
        tm.observe(t - 1.0, [row(0, at(250), motion=7)], ORIGIN)
        tm.observe(t - 0.5, [row(0, at(250), motion=WALK)], ORIGIN)
        tm.hurt(t, ORIGIN)
        tm.new_round()
    assert not tm.lethal_motion(HAMMER, WALK)                        # 2 hits of 22 starts: under LEARN_RATE


def test_the_reach_is_learned_and_an_attack_through_his_shots_is_unstoppable(tmp_path):
    tm = T.ThreatMemory(tmp_path / "t.json", default_reach_cm=300.0)
    charge_then_hit(tm, 10.0, dist=480.0, hp=(2000, 1700))           # his shots hurt it during the charge
    assert tm.reach(HAMMER, 300.0) == pytest.approx(480.0 * T.REACH_MARGIN + T.REACH_PAD_CM)
    assert tm.reach("uEm10", 300.0) == 300.0
    assert tm.unstoppable(row(0, at(480))) and tm.last_hit["through"]


def test_nobody_in_reach_is_an_unattributed_hit(tmp_path):
    tm = T.ThreatMemory(tmp_path / "t.json")
    tm.observe(1.0, [row(0, at(2000))], ORIGIN)
    assert tm.hurt(1.5, ORIGIN) is None and tm.stats["tm_hits_unattributed"] == 1


def test_named_attack_evidence_does_not_teach_flash_reactions_as_attacks():
    tm = T.ThreatMemory(attack_required=True, held_needs_flag=True)
    for t, m in [(0, 'Walk'), (.2, 'DmgFlash'), (.4, 'DeadErase')]:
        tm.observe(t, [row(0, at(100), motion=m)], ORIGIN, attacking=lambda e: False)
    assert tm.hurt(.5, ORIGIN, 200) is None
    assert not tm.round_hits and tm.stats['tm_hits_unattributed'] == 1


def test_only_attacking_motions_in_the_damage_window_are_learned():
    tm = T.ThreatMemory(attack_required=True, held_needs_flag=True)
    for t, m in [(0, 'Walk'), (.2, 'AtkKnife'), (.4, 'DmgFlash')]:
        tm.observe(t, [row(0, at(100), motion=m)], ORIGIN,
                   attacking=lambda e: e['motion'] == 'AtkKnife')
    assert tm.hurt(.5, ORIGIN, 200)['motions'] == ['AtkKnife']
    assert not tm.lethal_motion(HAMMER, 'DmgFlash')


# --- the RE5 Switch bot ------------------------------------------------------------------------------------------
@pytest.fixture
def switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def snap(enemies, hp=1000):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": 0, "aim_pitch": None},
            "enemies": enemies, "inventory": [], "kills": 0,
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_bot_steps_out_of_a_charge_that_hurt_him_through_his_shots(switch_fight):
    b, clock = bot()
    hammer = lambda m, hp: row(0, at(420), m, hp)
    for t, m, hp, php in ((1.0, WALK, 2000, 1000), (2.0, CHARGE, 2000, 1000), (3.0, CHARGE, 1700, 1000),
                          (3.2, CHARGE, 1700, 700)):                 # charged, shot, landed anyway
        clock[0] = t
        b.tick(snap([hammer(m, hp)], hp=php))
    assert b.stats["tm_hits_attributed"] == 1 and b.stats["tm_last_hit"]["class"] == HAMMER
    assert b.stats["threats"][HAMMER]["through"] == 1
    before = b.stats["lethal_backoffs"]                              # (the charge that hit him: out of it already)
    for t, m in ((8.0, WALK), (9.0, CHARGE)):                        # the same hammer charges again, 4.2 m away
        clock[0] = t
        act = b.tick(snap([hammer(m, 1700)], hp=700))
    assert b.doing == "backoff" and b.stats["lethal_backoffs"] == before + 1
    assert "zr" not in act.get("hold", ()) and any(k in act.get("hold", ()) for k in ("ldown", "lleft", "lright"))
    clock[0] = 9.0 + R.LETHAL_BACKOFF_MAX_S + 0.5                    # cornered for too long: he fights it
    b.tick(snap([hammer(CHARGE, 1700)], hp=700))
    assert b.doing != "backoff"


def test_the_one_that_hurt_him_is_the_next_target_before_a_nearer_calm_one(switch_fight):
    b, clock = bot()
    first = lambda m: row(0, at(500, 20), m, 300, cls="uEm10")
    calm = row(1, at(300, -10), WALK, 300, cls="uEm10")
    for t, m, php in ((1.0, WALK, 1000), (1.5, 81, 1000), (2.2, 81, 850)):
        clock[0] = t
        b.tick(snap([first(m), calm], hp=php))
    assert b._tm.grudge(first(WALK)) == 1
    clock[0] = 4.0
    b.tick(snap([first(WALK), calm], hp=850))
    assert b._grudge_e is not None and b._grudge_e["ptr"] == 10
