"""Placement must buy a measured departure, not permission to stop shooting beside a bomb."""
import math
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_mines as M, re5_ps3 as R
from gbox.mercs.titles.re5_nav import Traversal
from test_re5_mine_survival import state
from test_re5_mercs import Mem, world, with_prompt, PLAYER, ENEMIES


def controller(monkeypatch):
    ground = {}
    config = dict(M.DEFAULT, interval_s=3)
    monkeypatch.setattr(M, 'ground_mines', lambda _: ground)
    monkeypatch.setattr(M, 'settings', lambda: dict(config))
    c = M.Controller(SimpleNamespace(), {}, lambda *args: None)
    mine = {'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':True}
    snap = {'player':{'ptr':PLAYER,'pos':(0.,0.,0.),'hp':1000,'action':0},
            'inventory':[mine], 'mine_placement_safe':True}
    return c, snap, mine, ground, config


def test_preflight_rejects_a_broken_later_segment_and_short_exit(tmp_path, monkeypatch):
    bot = R.Bot(learn_dir=tmp_path)
    snap, _ = state()
    snap['enemies'] = []
    origin = snap['player']['pos']
    route = [(400.,0.,0.), (1000.,0.,0.)]
    calls = []
    monkeypatch.setattr(snap['nav'], 'retreat', lambda *args, **kw: calls.append(args[2]) or route)
    monkeypatch.setattr(snap['nav'], 'floor_segment', lambda a,b: a == origin)
    assert not bot._mine_placement_preflight(snap,0.)
    assert calls == [900.] and snap['mine_escape_route'] is None
    monkeypatch.setattr(snap['nav'], 'floor_segment', lambda a,b: True)
    assert bot._mine_placement_preflight(snap,.1)
    assert snap['mine_escape_route'] == route
    route[:] = [(origin[0]+849.,0.,0.)]
    assert not bot._mine_placement_preflight(snap,.2)
    route[:] = [Traversal((1000.,0.,0.),origin,(900.,0.,0.))]
    assert not bot._mine_placement_preflight(snap,.3)
    route[:] = [(400.,0.,0.),(200.,0.,0.),(1000.,0.,0.)]
    assert not bot._mine_placement_preflight(snap,.4)  # a floor route may still turn back toward the placement


def test_new_blocked_link_invalidates_preflight_cache(tmp_path,monkeypatch):
    bot=R.Bot(learn_dir=tmp_path)
    snap,_=state(); snap['enemies']=[]
    calls=[]
    monkeypatch.setattr(snap['nav'],'retreat',lambda *a,**kw:calls.append(kw) or [(1000.,0.,0.)])
    assert bot._mine_placement_preflight(snap,0.)
    bot.blocked_links.add((0,1))
    assert bot._mine_placement_preflight(snap,.1)
    assert len(calls)==2


@pytest.mark.parametrize('scan',[None, M.GroundMines()])
def test_incomplete_ground_observation_cannot_authorize_a_plant(tmp_path, scan):
    bot = R.Bot(learn_dir=tmp_path)
    snap,_ = state()
    snap.update(enemies=[],ground_mines=scan)
    assert not bot._mine_placement_preflight(snap,0.)
    assert 'incomplete' in bot.stats['mine_placement_safety_reason']


def test_controller_requires_explicit_preflight_and_six_meter_enemy_margin(monkeypatch):
    c,snap,mine,ground,_ = controller(monkeypatch)
    snap.pop('mine_placement_safe')
    c.tick(snap,0.)
    assert c.tick(snap,3.) is None and c.pending is None
    snap['mine_placement_safe'] = True
    snap['enemies'] = [{'hp':100,'pos':(500.,0.,0.)}]
    assert c.tick(snap,4.) is None and c.pending is None
    assert c.stats.get('mine_attempts',0) == 0


def test_controller_rechecks_corridor_when_native_ground_scan_changes(monkeypatch):
    c,snap,mine,ground,_=controller(monkeypatch)
    snap['mine_escape_route']=[(1000.,0.,0.)]
    c.tick(snap,0.)
    ground[9]={'pos':(900.,0.,0.),'arming_s':0.,'detonating':False}
    assert c.tick(snap,3.) is None and c.pending is None
    assert 'corridor' in c.stats['mine_status']


def test_failed_second_ground_scan_releases_pending_place_button(monkeypatch):
    c,snap,mine,ground,_=controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    assert snap['mine_placement_safe'] is True
    monkeypatch.setattr(M,'ground_mines',lambda _:M.GroundMines())
    assert c.tick(snap,3.1)=={'hold':set()} and c.pending is not None
    assert c.stats.get('mines_placed',0)==0


def test_far_native_actor_reused_near_attempt_requires_escape_without_false_credit(monkeypatch):
    c,snap,mine,ground,_=controller(monkeypatch)
    ground[9]={'pos':(2000.,0.,0.),'arming_s':0.,'detonating':False}
    c.tick(snap,0.); c.tick(snap,3.)
    ground[9]['pos']=(200.,0.,0.)
    mine['rounds']=4
    assert c.tick(snap,3.1)=={'hold':set()}
    assert c.escape['pos']==(200.,0.,0.) and c.stats.get('mines_placed',0)==0
    c.tick(snap,9.)
    assert c.escape is not None and c.pending is None


def test_actual_offset_and_all_observed_positions_own_departure_even_after_disappearance(monkeypatch):
    c,snap,mine,ground,_ = controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    for actor,x in ((9,240.), (10,-240.)):
        ground[actor] = {'pos':(x,0.,0.),'arming_s':3.,'detonating':False}
    assert c.tick(snap,3.2)=={'hold':set()}  # actors observed before the consumption counter changes
    assert c.escape is not None and c.stats.get('mines_placed',0)==0
    ground.clear()
    mine['rounds'] = 4
    c.tick(snap,3.3)
    assert c.escape['pos'] == (240.,0.,0.) and len(c.escape['hazards']) == 2
    assert not c.clear_escape(4.,(650.,0.,0.))  # 650 from attempt, only 410 from actual actor
    assert not c.clear_escape(4.,(-650.,0.,0.)) # the second actor matters too
    assert not c.clear_escape(4.,(math.nan,0.,0.))
    assert c.clear_escape(5.,(900.,0.,0.))
    assert c.stats['mine_retreat_distance'] == 660.


def test_disabling_during_placement_keeps_acknowledgement_and_escape(monkeypatch):
    c,snap,mine,ground,config = controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    config['enabled'] = False
    mine['rounds'] = 4
    ground[9] = {'pos':(200.,0.,0.),'arming_s':3.,'detonating':False}
    c.tick(snap,5.1)
    assert c.escape['pos'] == (200.,0.,0.) and c.pending is None
    assert c.stats['mine_escape_active'] and not c.stats['mine_placement_pending']
    assert not c.clear_escape(6.,(650.,0.,0.))


def test_pending_placement_acknowledges_during_mandatory_prompt_without_owning_input(monkeypatch):
    c,snap,mine,ground,_ = controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    snap['prompt'] = 'stick:rotate'
    mine['rounds'] = 4
    ground[9] = {'pos':(0.,0.,0.),'arming_s':3.,'detonating':False}
    assert c.tick(snap,3.1) is None
    assert c.escape is not None and c.stats['mines_placed'] == 1


def test_reused_pointer_old_event_or_failed_scan_cannot_release_retained_hazard(monkeypatch):
    c,snap,_,ground,_ = controller(monkeypatch)
    c.escape = {'actor':9,'pos':(0.,0.,0.),'at':5.}
    c.events = [{'kind':'detonation_observed','actor':9,'at':1.}]
    c.detonating = {9}
    ground[9] = {'pos':(1000.,0.,0.),'arming_s':0.,'detonating':True}
    c.tick(snap,6.)
    ground.clear()
    c.tick(snap,7.)
    assert not c.escape.get('removal_recorded') and not c.escape.get('detonation_observed')
    c.escape['detonation_observed'] = True
    monkeypatch.setattr(M,'ground_mines',lambda _:M.GroundMines())
    c.tick(snap,8.)
    assert not c.escape.get('removal_recorded') and not c.clear_escape(8.,(599.,0.,0.))


@pytest.mark.parametrize('fault',['cycle','invalid_pointer','nonfinite','truncated','short_flag'])
def test_ground_reader_marks_corrupt_or_incomplete_observation_unverified(fault):
    m = Mem()
    manager, actor = 0x30400000,0x30500000
    m.u32(R.S_UNIT,manager)
    m.u32(manager+R.UNIT_LINES+10*R.LINE_STRIDE+R.LINE_FIRST,actor)
    m.u32(actor,next(iter(M.MINE_VTABLES)))
    m.put(actor+M.PLACED,b'\x01')
    m.put(actor+0x30,struct.pack('>3f',0.,0.,0.))
    m.put(actor+M.ARMING,struct.pack('>f',3.))
    m.u32(actor+R.UNIT_NEXT,0)
    # Use the real reader; this test has no mocked world scan.
    if fault=='cycle': m.u32(actor+R.UNIT_NEXT,actor)
    elif fault=='invalid_pointer': m.u32(actor+R.UNIT_NEXT,0xDEADBEEF)
    elif fault=='nonfinite': m.put(actor+0x30,struct.pack('>f',math.nan))
    else:
        read=m.rd
        broken=actor+(M.PLACED if fault=='short_flag' else M.ARMING)
        m.rd=lambda address,n: b'' if address==broken else read(address,n)
    assert not M.ground_mines(m).verified


def test_unacknowledged_actor_keeps_escape_after_attempt_timeout(monkeypatch):
    c,snap,mine,ground,_=controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    ground[9]={'pos':(200.,0.,0.),'arming_s':3.,'detonating':False}
    assert c.tick(snap,3.1)=={'hold':set()}
    assert c.escape is not None and c.pending is not None
    ground.clear()
    c.tick(snap,9.)
    assert c.pending is None and c.escape is not None
    assert c.stats.get('mines_placed',0)==0
    assert not c.clear_escape(10.,(700.,0.,0.))


def test_exhausted_missing_inventory_stack_cannot_hide_ground_actor(monkeypatch):
    c,snap,mine,ground,_=controller(monkeypatch)
    c.tick(snap,0.); c.tick(snap,3.)
    snap['inventory']=[]
    ground[9]={'pos':(200.,0.,0.),'arming_s':3.,'detonating':False}
    c.tick(snap,3.1)
    assert c.escape['pos']==(200.,0.,0.)
    c.tick(snap,9.)
    assert c.escape is not None and c.pending is None and c.stats.get('mines_placed',0)==0


def test_optional_finisher_is_suppressed_but_enemy_owned_and_grab_inputs_remain():
    memory=with_prompt(world(enemies=[((0.,0.,150.),0,800)]),R.BTN_MELEE,PLAYER,ENEMIES[0])
    stats={'mine_escape_active':True}
    source=R.RE5PS3().prompt_source(memory,stats)
    snap=R.snapshot(memory)
    assert snap['prompt_optional'] and not R.Bot._mine_escape_mandatory(snap)
    assert source() is None
    memory.put(PLAYER+R.P_ACTION,b'\x04')
    assert not R.snapshot(memory)['prompt_optional'] and source()=='square'
    memory.put(PLAYER+R.P_ACTION,b'\x00')
    with_prompt(memory,0,ENEMIES[0],PLAYER)
    assert not R.snapshot(memory)['prompt_optional'] and source()=='mash:square'
    assert R.Bot._mine_escape_mandatory(R.snapshot(memory))


def test_missing_mesh_escape_cannot_fall_through_to_combat(tmp_path):
    bot=R.Bot(learn_dir=tmp_path)
    snap,_=state()
    bot.mines=SimpleNamespace(escape={'actor':9,'pos':(0.,0.,0.)},clear_escape=lambda *a:False)
    snap['nav']=None
    assert bot._mine_retreat(snap['player'],snap,1.)=={'hold':set()}
    assert bot.mines.escape is not None and 'blocked' in bot.stats['mine_retreat_status']


def test_offmesh_recovery_does_not_probe_unverified_floor_beside_a_retained_mine(tmp_path,monkeypatch):
    bot=R.Bot(learn_dir=tmp_path)
    snap,_=state()
    p=snap['player']|{'pos':(1010.,0.,0.),'rot':R.heading(100.,0.)}
    bot.mines=SimpleNamespace(escape={'actor':9,'pos':(900.,0.,0.)},clear_escape=lambda *a:False)
    bot.nav_recovery={'origin':p['pos'],'points':[(1110.,0.,0.)],'index':0,'started':0.,'walking':None}
    monkeypatch.setattr(snap['nav'],'floor_segment',lambda *a,**kw:False)
    assert bot._mine_retreat(p,snap,.1)=={'hold':set()}
    assert 'no verified floor support' in bot.stats['nav_recovery']
    assert bot.mines.escape is not None


@pytest.mark.parametrize('action',[4,5])
def test_escape_does_not_override_native_grab_or_hit_recovery(tmp_path,monkeypatch,action):
    bot=R.Bot(learn_dir=tmp_path)
    snap,_=state()
    snap['player']['action']=action
    bot.mines=SimpleNamespace(escape={'actor':9,'pos':(0.,0.,0.)})
    monkeypatch.setattr(bot,'_mine_retreat',lambda *a:(_ for _ in ()).throw(AssertionError('recovery interrupted')))
    assert bot._tick(snap)=={'hold':set()}


def test_retreat_passes_verified_route_and_retains_missing_actor_hazard(tmp_path,monkeypatch):
    bot=R.Bot(learn_dir=tmp_path)
    snap,_=state()
    origin=snap['player']['pos']
    escape={'actor':9,'pos':origin,'at':0.,'hazards':{9:origin}}
    bot.mines=SimpleNamespace(escape=escape,clear_escape=lambda *a:False)
    calls=[]
    monkeypatch.setattr(bot,'_follow',lambda *a,**kw:calls.append(kw) or {'hold':{'lup'}})
    assert bot._mine_retreat(snap['player'],snap,1.)=={'hold':{'lup'}}
    route=calls[-1]['approved_route']
    assert route and math.dist(route[-1],origin)>=600.
    assert ('retained',9) in bot.nav_dynamic_mines
    assert all(snap['nav'].floor_segment(a,b) for a,b in zip([origin]+route,route))
