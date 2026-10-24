"""Native firing observations cannot establish arrow count or causal impact calibration."""
import math

import pytest

from gbox.mercs.titles import re5_combat as C, re5_ps3 as R
from test_re5_combat import ACT, supported_laserless
from test_re5_laserless_fire import scene


def tick(combat, state, now):
    return combat.tick(dict(state),state['player'],state['enemies'][0],now)


def fire(memory, combat, state, now):
    memory.put(ACT,'>I',C.FIRE_VT)
    return tick(combat,state,now)


def test_bow_gate_shrinks_with_range_and_rejects_old_five_degree_miss(tmp_path):
    assert all(a>b for a,b in zip(C.bow_tolerance(500),C.bow_tolerance(2000)))
    assert math.degrees(C.bow_tolerance(2000)[0])==pytest.approx(1.5)   # the floor: a far Majini still gets arrows
    memory,state=scene()
    state['camera']['at']=(math.tan(math.radians(5))*1000,110.,1000.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert 'r1' not in tick(combat,state,1.)['hold']
    assert combat.stats['bow_aim_tolerance_deg'][0]<2.5
    assert combat.stats['shots']==0


def test_bow_small_far_error_fires_while_still_correcting_inside_old_gun_deadzone(tmp_path):
    # operator 2026-10-24: "have Sheva rapid firing these arrows" - release on the body, keep tracking meanwhile
    memory,state=scene()
    state['enemies'][0]['pos']=(0.,0.,1990.)
    supported_laserless(state)
    state['camera']['at']=(math.tan(math.radians(.58))*1990,110.,1990.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    action=tick(combat,state,1.)
    assert 'r1' in action['hold'] and {'rleft','rright'} & action['hold']
    assert combat._yaw(math.radians(.58))==set()  # ordinary gun policy unchanged


def test_firing_without_target_damage_does_not_renew_bow_engagement(tmp_path):
    memory,state=scene()
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    tick(combat,state,1.)
    for now in (1.1,2.,3.):
        memory.put(ACT,'>I',C.READY_VT);tick(combat,state,now-.01)
        fire(memory,combat,state,now)
    action=fire(memory,combat,state,4.1)
    assert action=={'hold':set()} and combat.needs_firing_position
    assert combat.stats['bow_ineffective_bursts']==1
    assert combat.stats['bow_firing_observations']>=3
    assert combat.stats['hits']==combat.stats['misses']==0


def test_measured_target_damage_renews_progress_without_claiming_hit(tmp_path):
    memory,state=scene();combat=C.Combat(memory,{},learn_dir=tmp_path)
    tick(combat,state,1.)
    for now in (2.,3.):tick(combat,state,now)
    state['enemies'][0]['hp']=700
    tick(combat,state,3.1)
    tick(combat,state,4.1)
    assert not combat.needs_firing_position
    assert combat.stats['hits']==0
    assert combat.bow_target_damage[state['enemies'][0]['ptr']]==3.1


def test_unknown_bow_observation_retains_context_and_never_becomes_miss_or_tuning(tmp_path):
    memory,state=scene();events=[]
    combat=C.Combat(memory,{},learn_dir=tmp_path,lessons=events.append)
    tick(combat,state,1.);fire(memory,combat,state,1.1)
    combat.observe(dict(state),3.2)
    combat.end_round(3.3)
    row=next(e for e in events if e.get('outcome')=='unknown')
    assert row['native_evidence']=='native_fire_action_entry_or_reset'
    assert row['target']==state['enemies'][0]['ptr'] and row['camera_at']==[0.,110.,1000.]
    assert row['individual_arrow_count'] is None and not row['confirmed_miss'] and not row['confirmed_hit']
    assert not row['calibration_applied']
    assert combat.stats['misses']==combat.stats['hits']==0
    assert combat.stats['accuracy'] is combat.stats['round_accuracy'] is None
    assert not combat.tun.d['weapons'] and not combat.tun.d['rounds']


def test_hp_loss_with_mine_is_confounded_and_does_not_calibrate(tmp_path):
    memory,state=scene();events=[]
    combat=C.Combat(memory,{},learn_dir=tmp_path,lessons=events.append)
    tick(combat,state,1.);fire(memory,combat,state,1.1)
    state['ground_mines']={7:{'pos':(0.,0.,1000.)}}
    state['enemies'][0]['hp']=700
    tick(combat,state,1.2)
    combat.observe(dict(state),3.2)
    observation=next(e for e in events if e['kind']=='bow_damage_observation')
    assert observation['ground_mines_present'] and not observation['calibration_applied']
    row=next(e for e in events if e.get('outcome')=='confounded')
    assert not row['confirmed_hit'] and not row['confirmed_miss']
    assert combat.stats['hits']==combat.stats['misses']==0
    assert combat.stats['bow_confounded_outcomes']==1


def test_bow_outcome_queue_is_bounded_and_round_boundary_resolves_unknown(tmp_path):
    memory,state=scene();events=[]
    combat=C.Combat(memory,{},learn_dir=tmp_path,lessons=events.append)
    tick(combat,state,1.)
    for n in range(40):combat._on_shot(1.+n*.01)
    assert len(combat.bow_pending)==32
    combat.end_round(1.5)
    assert not combat.bow_pending and combat.stats['bow_unconfirmed_impacts']==40
    assert combat.stats['hits']==combat.stats['misses']==0
    combat.start_round(10.)
    assert combat.bow_round_observations==0 and not combat.bow_target_damage


def test_switching_back_to_gun_does_not_publish_mixed_bow_accuracy(tmp_path):
    memory,state=scene();combat=C.Combat(memory,{},learn_dir=tmp_path)
    tick(combat,state,1.);fire(memory,combat,state,1.1)
    state['inventory'][0].update(id=0x112,item=0x12)
    tick(combat,state,1.2)
    assert combat.wid==0x12 and combat.stats['accuracy'] is None
    assert combat.stats['round_accuracy'] is None


def test_bow_reacquisition_gives_driver_real_supported_route_ticks(tmp_path):
    memory,state=scene()
    bot=R.Bot(memory,clock=lambda:10.,learn_dir=tmp_path)
    bot._tick(dict(state))
    bot.clock=lambda:13.1
    assert bot._tick(dict(state))=={'hold':set()}
    assert bot.combat.needs_firing_position
    bot.clock=lambda:13.2
    action=bot._tick(dict(state))
    assert 'lup' in action['hold'] and not ({'l1','r1'} & action['hold'])
    assert bot._following_route and bot.stats['phase']=='pursue'


def test_near_majini_keeps_the_longbow_shooting_instead_of_repositioning(tmp_path):
    # "She is sitting there not even fighting back": no damage measured for 3 s used to end the burst and walk off
    memory,state=scene()
    state['enemies'][0]['pos']=(0.,0.,600.)
    supported_laserless(state)
    state['camera']['at']=(0.,110.,600.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    tick(combat,state,1.)
    triggers=0
    for i in range(1,60):
        now=1.+i*.1
        memory.put(ACT,'>I',C.READY_VT if i%2 else C.FIRE_VT)
        triggers+='r1' in tick(combat,state,now)['hold']
    assert not combat.needs_firing_position and combat.stats.get('bow_ineffective_bursts',0)==0
    assert triggers>=10
