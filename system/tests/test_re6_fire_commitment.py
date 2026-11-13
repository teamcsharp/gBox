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


def test_blocked_bomb_escape_keeps_gun_raised_to_clear_the_crowd():
    bot, snap = crowd()
    p = snap['player']
    p['bomb'] = {'out': True, 'armed': True}
    bot.bomb_at = (0, 200)
    bot.aim_since = 1.
    bot._bomb_walk = lambda *a, **kw: None  # the escape corridor needs fighting first
    for now in (1.1, 1.2, 1.3):
        assert bot._bomb_escape(p, snap, now) is None
        assert bot._bomb(p, snap['enemies'], lambda e: 100, 0, snap, now) is None
        assert bot.aim_since == 1.


def test_waiting_remote_bombs_do_not_prevent_a_loaded_crowd_shotgun_switch(monkeypatch):
    bot, snap = crowd(weapon=12)
    monkeypatch.setattr(R, 'AUTO_SWITCH', True)
    p = snap['player']
    p.update(equipped=0, guns={0x10C: 0, 0x104: 1}, gun_ammo={0: 20, 1: 10},
             bomb={'out': True, 'armed': True})
    snap['enemies'] *= 3
    bot.bomb_phase = 'wait'
    bot._equip_result = {'state': 'requested'}
    bot._equip_keys = lambda player, wanted: {'hold': ()}
    assert bot._weapon_switch(p, 10.) is not None
    assert bot.stats['weapon_switches'] == 1


def test_unblocked_bomb_escape_keeps_loaded_firearm_and_merges_retreat(monkeypatch):
    bot,snap=crowd(weapon=12)
    p=snap['player'];p.update(equipped=0,bomb={'out':True,'armed':True})
    bot.bomb_at=(0,200);bot.aim_since=1.
    bot._open_heading=lambda *a,**kw:math.pi
    for now in (1.1,1.2,1.3):
        assert bot._bomb_escape(p,snap,now) is None
        assert bot.aim_since==1.
        assert bot._crowd_control(snap['enemies'],lambda e:100,lambda e:0,now) is None
        out=bot._escape_fire_inputs(snap,{'hold':('zl','zr','rright','lup')})
        assert 'zl' in out['hold'] and 'zr' in out['hold'] and 'rright' in out['hold']
        assert 'lup' not in out['hold'] and 'ldown' in out['hold']
    assert bot.stats['bomb_kicks']==0


def test_retreat_merge_never_invents_trigger_or_interrupts_healing():
    bot,snap=crowd();snap['player']['equipped']=0
    bot._combat_escape_move=('ldown',)
    assert 'zr' not in bot._escape_fire_inputs(snap,{'hold':('zl',)})['hold']
    heal={'tap':'r'}
    assert bot._escape_fire_inputs(snap,heal)==heal
    snap['player']['equipped']=R.BOMB_INDEX
    out={'hold':('zl',)}
    assert bot._escape_fire_inputs(snap,out)==out


def test_grab_never_turns_single_far_bomb_position_into_a_detonator_press():
    bot,snap=crowd();p=snap['player']
    p.update(equipped=R.BOMB_INDEX,bomb={'out':True,'armed':True})
    snap['bomb_pos']=(0,0,5000)
    snap['throwables']=[{'kind':'remote','pos':(0,0,5000)},{'kind':'remote','pos':(0,0,50)}]
    bot._mind_ok=lambda now:True
    calls=[]
    def mind(s):
        calls.append(s)
        return {'verified':False,'reason':'owned bomb inside clearance'}
    bot.mind=mind
    assert bot._grab_detonate(p,snap) is False
    assert len(calls)==1 and bot.stats['grab_det_presses']==0
    assert 'inside clearance' in bot.stats['grab_native_refusal']
    bot._grab_mind_at=-1e9
    bot.mind=lambda s:{'verified':True}
    assert bot._grab_detonate(p,snap) is False
    assert bot.stats['grab_native_detonations']==1


def test_arsenal_prefers_loaded_shotgun_for_crowds():
    from gbox.mercs import weapon_swap as W
    from dataclasses import replace
    profile=replace(W.PROFILES['re6'],enabled=True)
    assert W.decide(profile,loaded_families=['launcher','magnum','shotgun'],crowd_count=5,now=2.,state={})=='shotgun'
