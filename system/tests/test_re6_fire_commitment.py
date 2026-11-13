import math

from gbox.mercs.titles import re6_switch as R
from test_re6_switch import BASE, Guest, brain, round_guest, _fresh_caches


def crowd(weapon=4):
    bot, clock, snap = brain(round_guest(enemies=((0., 0., 100., 700), (30., 0., 180., 700))))
    snap['player'].update(weapon_id=weapon, ammo=10)
    bot._p, bot._snap = snap['player'], snap
    bot._cam_yaw = 0.
    return bot, snap


def test_loaded_shotgun_acquires_and_keeps_aim_in_a_close_crowd():
    bot, snap = crowd()
    foes = snap['enemies']
    flat = lambda e: math.hypot(e['pos'][0], e['pos'][2])
    for n in range(12):
        now = 1. + n * .1
        assert bot._crowd_control(foes, flat, lambda e: 0., now) is None
        bot.aim_since = 1.
    assert bot.aim_since == 1.
    assert bot.stats['cc_kicks'] == 0
    assert bot.stats['crowd_fire_commit_ticks'] == 12


def test_new_bomb_setup_waits_for_the_current_firing_commitment():
    bot, snap = crowd()
    p = snap['player']
    p['bomb'] = {'count': 10, 'out': False}
    bot._burst().begin(1.)
    assert bot._bomb(p, snap['enemies'], lambda e: 100., 0., snap, 1.1) is None
    assert bot.stats['bomb_deferred_for_fire'] == 1
    assert bot.bomb_phase is None


def test_complete_native_census_clears_stale_wheel_flag_but_unknown_does_not():
    bot, snap = crowd()
    p = snap['player']
    p['bomb'] = {'out': True, 'armed': True}
    bot.bomb_dropped = True
    snap['throwables'] = None
    assert bot._bomb_out(p)
    snap['throwables'] = []
    assert not bot._bomb_out(p)
    snap['throwables'] = [{'kind': 'remote', 'pos': (0, 0, 2000)}]
    assert bot._bomb_out(p)


def test_empty_gun_does_not_claim_shotgun_firing_priority():
    bot, snap = crowd()
    bot._p['ammo'] = 0
    assert bot._crowd_control(snap['enemies'], lambda e: 100., lambda e: 0., 1.) is not None
    assert bot.stats.get('crowd_fire_commit_ticks', 0) == 0


def test_throwable_census_cannot_miss_a_remote_bomb_on_another_line():
    from gbox.mercs.titles import re6_switch_mods as M
    M._UNIT_NAMES.clear()
    g = Guest()
    player = g.obj('uPlayer')
    bomb = g.unit(8, 'uWp1097', size=0x2000)
    g.q(bomb + M.U_OWNER, player)
    g.i32(bomb + M.U_GENERATION, 3)
    g.f32(bomb + R.P_POS, 0, 0, 200)
    found = R.owned_throwables(g, BASE, player)
    assert len(found) == 1 and found[0]['unit'] == bomb
    g.q(bomb + R.UNIT_NEXT, bomb)
    assert R.owned_throwables(g, BASE, player) is None
