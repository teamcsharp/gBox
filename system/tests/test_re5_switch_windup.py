"""RE5 Switch wind-ups first (operator 19:25: "tell who is transitioning into an attack animation and be able to
prioritize deactivating them with an attack"): a Majini's own motion (+0x8F8: 80 / 81 the grab's lunge, 60 / 91 the
swings) or his attack flag (+0xA23 0x40) makes him the target before any other; the counters."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def foe(i, pos, motion=4, act=0, hp=800):
    return {"ptr": 10 + i, "pos": pos, "hp": hp, "hp_max": 800, "motion": motion, "act": act}


def snap(enemies, hp=1000, motion=0, dot=None):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": enemies, "inventory": [], "kills": 0,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_one_winding_up_is_the_target_before_a_nearer_calm_one():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(280, -20), motion=80)]))
    assert b.target == 11 and b.stats["windup_seen"] == 1 and b.stats["windup_picks"] >= 1


def test_the_attack_flag_counts_as_a_wind_up():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(280, -20), act=0x40)]))
    assert b.target == 11


def test_in_the_crowd_fire_the_wind_up_is_the_one_fired_on():
    b, clock = bot()
    ring = [foe(0, at(200, 5)), foe(1, at(300, 40)), foe(2, at(260, -30), motion=60)]
    b.tick(snap(ring))
    assert b.target == 12 and b._ramp is not None


def test_a_wind_up_that_lands_is_counted_one_his_shots_hurt_is_an_interrupt():
    b, clock = bot()
    b.tick(snap([foe(0, at(250, 0), motion=80)]))
    clock[0] = 0.5
    b.tick(snap([foe(0, at(120, 0), motion=80)], hp=800))         # it lands: his health falls
    clock[0] = 1.3
    b.tick(snap([foe(0, at(120, 0), motion=4)], hp=800))
    assert b.stats["hits_after_windup"] == 1 and b.stats["windup_interrupts"] == 0
    b2, clock2 = bot()
    b2.tick(snap([foe(0, at(250, 0), motion=80)]))
    clock2[0] = 0.4
    b2.tick(snap([foe(0, at(240, 0), motion=86, hp=500)]))         # shot: staggered, hurt
    clock2[0] = 1.3
    b2.tick(snap([foe(0, at(240, 0), motion=4, hp=500)]))
    assert b2.stats["windup_interrupts"] == 1 and b2.stats["hits_after_windup"] == 0


def test_a_wind_up_behind_beats_a_calm_one_nearer_in_front_for_the_quick_turn():
    b, clock = bot()
    b.tick(snap([foe(0, at(150, 0)), foe(1, at(220, 170), motion=81)]))
    assert b.quick == 2 and b.target == 11 and b.stats["behind_turns"] == 1


def test_a_far_wind_up_is_no_concern():
    b, clock = bot()
    b.tick(snap([foe(0, at(200, 10)), foe(1, at(900, -20), motion=80)]))
    assert b.target == 10 and b.stats["windup_seen"] == 0


def learned_threat(bot, motions):
    bot._tm.data = {'version':1, 'classes':{'uEm10':{
        'starts':{str(m):10 for m in motions}, 'hits':{str(m):5 for m in motions},
        'hit_count':20, 'through':10, 'reach_cm':700}}}


def test_old_walking_damage_correlations_do_not_lower_the_gun(monkeypatch):
    monkeypatch.setattr(R, 'THREAT_FILE', None)
    b, clock = bot()
    learned_threat(b, [42])
    enemy = dict(foe(0, at(140, 0), motion=42), **{'class':'uEm10', 'generation':1})
    scene = snap([enemy], motion=R.MOTION_AIMED, dot=(0, 140, 140))
    assert b._tm.lethal(enemy) and b._tm.unstoppable(enemy)  # reproduce the contaminated saved evidence
    assert not b._winding(enemy)
    assert b._lethal_tick(scene['player'], [enemy], lambda e:140, 0) is None
    b.tick(scene)
    assert b.doing != 'backoff' and b.stats['lethal_backoffs'] == 0


def test_native_attack_animation_changes_cannot_restart_backoff_forever(monkeypatch):
    monkeypatch.setattr(R, 'THREAT_FILE', None)
    b, clock = bot()
    learned_threat(b, [60, 80, 81])
    enemy = dict(foe(0, at(140, 0), motion=60, act=R.E_ATTACKING), **{'class':'uEm10', 'generation':1})
    player = snap([enemy])['player']
    assert b._lethal_tick(player, [enemy], lambda e:140, 0) is not None
    enemy['motion'] = 80
    assert b._lethal_tick(player, [enemy], lambda e:140, 1) is not None
    enemy['motion'] = 81
    assert b._lethal_tick(player, [enemy], lambda e:140, R.LETHAL_BACKOFF_MAX_S+.1) is None
    assert b.stats['lethal_backoffs'] == 1


def test_different_enemies_and_one_quiet_tick_do_not_extend_escape(monkeypatch):
    monkeypatch.setattr(R, 'THREAT_FILE', None)
    b, clock = bot()
    learned_threat(b, [60, 81])
    first = dict(foe(0, at(140, 0), motion=60), **{'class':'uEm10'})
    second = dict(foe(1, at(140, 90), motion=81), **{'class':'uEm10'})
    player = snap([first])['player']
    # Verified windup anticipates a strike before its attack flag appears.
    assert b._lethal_tick(player, [first], lambda e:140, 0) is not None
    assert b._lethal_tick(player, [second], lambda e:140, 1) is not None
    assert b._lethal_tick(player, [], lambda e:140, 1.1) is None
    assert b._lethal_tick(player, [first], lambda e:140, 2) is None
    assert b.stats['lethal_backoffs'] == 1
    b._lethal_tick(player, [], lambda e:140, 3)
    b._lethal_tick(player, [], lambda e:140, 3.7)
    assert b._lethal_tick(player, [second], lambda e:140, 4) is not None
    assert b.stats['lethal_backoffs'] == 2
