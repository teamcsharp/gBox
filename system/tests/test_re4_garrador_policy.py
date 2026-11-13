"""RE4 boss aim follows native geometry and refuses blind weakpoint sprays."""
import copy
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re4_garrador_aim as G, re4_switch as R
from gbox.mercs.core import aim_book as A


def scene(tmp_path):
    bot=R.Bot(stats={},director=False)
    bot._aim_book_core=A.AimCore(R.combat_profile(),bot.stats,root=tmp_path,log=False,verified_only=True)
    bot._lock_live=lambda now:True
    bot._aim_since=9.;bot._last_fire=9.
    player={'ptr':100,'id':3,'pos':(0,0,0),'rot':0.,'hp':1000}
    enemy={'ptr':200,'id':4,'pos':(0,0,5000),'rot':0.,'hp':2600,'hp_max':2600,
           'class':G.ENEMY_CLASS,'native_type':10,'key':'garrador','boss':True}
    target=(0,1200,4800)
    enemy['weakpoint']={'owner':200,'owner_id':4,'part_no':37,'native_type':10,
        'point':target,'radius_mm':200,'source':'native Garrador damage sphere','at':10.}
    laser={'from':(0,1450,500),'at':target,'up':True}
    snap={'player':player,'enemies':[enemy],'weapon_class':7,'equipped_id':0x2C,
        'laser':laser,'aim':{'wep':500,'obj':600,'item':0x2C,'sight':200,'pitch':0.,'waist':0.,'sway':(0.,)*4}}
    return bot,player,enemy,snap


def action(bot,p,e,s,now=10.,live=None):
    return bot._ram_aim(p,live or [(5000.,0.,e)],e,5000.,0.,.2,s,now)


def test_plan_uses_actual_live_sphere_and_exact_weapon_partition(tmp_path):
    bot,p,e,s=scene(tmp_path)
    plan,origin=bot._aim_plan(p,e,s,10.)
    assert plan.point0 == e['weakpoint']['point']
    assert plan.point0 != (0,1100,5000)
    assert plan.weapon=='0x002c' and plan.pose=='garrador_back_sphere'
    assert origin==s['laser']['from']


def test_exposed_finite_laser_contact_fires_without_scatter_offset(tmp_path):
    bot,p,e,s=scene(tmp_path)
    act=action(bot,p,e,s)
    assert act.get('tap')==R.FIRE_BTN
    assert bot.stats['weakpoint_aim']['finite_laser_contact'] is True
    assert R.AIM_REQUEST['yaw']==pytest.approx(0.)
    row=bot._aim_core().ledger.open[-1]
    assert row['weapon']=='0x002c' and row['contact'] is True
    assert row.get('discharge_confirmed') is not True
    assert row['weakpoint']['part_no']==37


@pytest.mark.parametrize('change', ['missing','stale','reused','front','no_lock','no_aim'])
def test_unavailable_weakpoint_never_falls_through_to_generic_chest(tmp_path,change):
    bot,p,e,s=scene(tmp_path)
    if change=='missing':e.pop('weakpoint')
    if change=='stale':e['weakpoint']['at']=9.
    if change=='reused':e['id']=9
    if change=='front':p['pos']=(0,0,8000)
    if change=='no_lock':bot._lock_live=lambda now:False
    if change=='no_aim':s.pop('aim')
    act=action(bot,p,e,s)
    assert act is not None and act.get('tap')!=R.FIRE_BTN
    assert bot.stats['weakpoint_aim']['state']=='unavailable'
    assert bot.stats['shots']==0


def test_many_miss_requests_never_emit_a_hundred_blind_shots(tmp_path):
    bot,p,e,s=scene(tmp_path)
    s['laser']['at']=(0,3000,7000)
    for i in range(100):
        now=10.+i*.05;e['weakpoint']['at']=now
        act=action(bot,p,e,s,now)
        assert act.get('tap')!=R.FIRE_BTN
    assert bot.stats['shots']==0
    assert 'weakpoint' in bot.why


def test_same_body_sight_cannot_hide_a_stage_block_before_weakpoint(tmp_path):
    bot,p,e,s=scene(tmp_path)
    s['laser']['at']=(0,1300,3000)  # ray would hit if extended; native laser stops at a wall
    assert action(bot,p,e,s).get('tap')!=R.FIRE_BTN


def test_retargets_valid_nearby_enemy_when_boss_sphere_is_unavailable(tmp_path):
    bot,p,e,s=scene(tmp_path);e.pop('weakpoint')
    ordinary={'ptr':250,'id':5,'pos':(0,0,4000),'hp':400,'class':G.ENEMY_CLASS}
    s['enemies'].append(ordinary);s['aim']['sight']=250;s['laser']['at']=(0,1100,4000)
    bot._may_fire=lambda *args:True
    act=action(bot,p,e,s,live=[(5000.,0.,e),(4000.,0.,ordinary)])
    assert act.get('tap')==R.FIRE_BTN and bot.target==250
    assert bot.stats['weakpoint_aim']['alternative']==250


def test_an_ordinary_sight_switch_to_boss_still_requires_real_weakpoint(tmp_path):
    bot,p,e,s=scene(tmp_path);e.pop('weakpoint')
    ordinary={'ptr':250,'id':5,'pos':(0,0,4000),'hp':400,'class':G.ENEMY_CLASS}
    s['enemies'].append(ordinary)
    bot._may_fire=lambda *args:False
    act=bot._ram_aim(p,[(5000.,0.,e),(4000.,0.,ordinary)],ordinary,4000.,0.,0.,s,10.)
    assert act.get('tap')!=R.FIRE_BTN


def test_alternate_enemy_cannot_recursively_switch_back_to_unavailable_boss(tmp_path):
    bot,p,e,s=scene(tmp_path);e.pop('weakpoint')
    ordinary={'ptr':250,'id':5,'pos':(1000,0,4000),'hp':400,'class':G.ENEMY_CLASS}
    s['enemies'].append(ordinary);bot._may_fire=lambda *args:True
    act=action(bot,p,e,s,live=[(5000.,0.,e),(4100.,.2,ordinary)])
    assert act is not None and bot.target==250
    assert 'aim_ram_error' not in bot.stats
    assert bot._aim_core().ledger.open[-1]['target']==250


def test_reposition_uses_bounded_native_route_not_direct_body_crossing(tmp_path):
    bot,p,e,s=scene(tmp_path);p['pos']=(0,0,8000)
    calls=[]
    walker=SimpleNamespace(mesh=SimpleNamespace(route=lambda start,goal:[goal]),
        approach=lambda goal,**kw:calls.append(goal) or ('lup','B'))
    bot.walker=walker
    assert action(bot,p,e,s).get('hold')=={'ZL'} and not calls
    walker.mesh.route=lambda start,goal:[(4000,0,8000),(4000,0,2000),goal]
    R.AIM_REQUEST.update(ptr=p['ptr'],yaw=3.,steady=True)
    act=action(bot,p,e,s,10.1)
    assert act['hold']=={'lup','B'} and len(calls)==1
    assert not R.AIM_REQUEST
    assert bot.stats['weakpoint_aim']['state']=='rear_reposition'
    act=action(bot,p,e,s,11.6)
    assert act['hold']=={'ZL'} and len(calls)==1


def test_bad_id_and_native_type_are_not_authorized_by_health_alone(tmp_path):
    bot,p,e,s=scene(tmp_path)
    e.pop('weakpoint');e.pop('native_type');e['key']='garrador_armored'
    assert bot._aim_plan(p,e,s,10.)[0] is None
    assert action(bot,p,e,s).get('tap')!=R.FIRE_BTN
