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


def test_near_majini_keeps_the_rotten_eggs_flying_instead_of_repositioning(tmp_path):
    # operator 2026-10-24: "They need to be bombarding enemies with rotten eggs when rotten egg mode is active"
    memory,state=scene(0x36)
    state['enemies'][0]['pos']=(0.,0.,600.)
    supported_laserless(state)
    state['camera']['at']=(0.,110.,600.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    tick(combat,state,1.)
    throws=sum('r1' in tick(combat,state,1.+i*.1)['hold'] for i in range(1,60))
    assert not combat.needs_firing_position and throws>=10


def test_bow_vertical_error_keeps_aim_and_never_turns_away_by_body_heading(tmp_path):
    memory,state=scene()
    state['player']['rot']=math.radians(50)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    actions=[]
    for now,height in ((1.,210.),(1.1,110.),(1.2,210.),(1.3,110.)):
        state['camera']['at']=(0.,height,1000.)
        actions.append(tick(combat,state,now)['hold'])
    assert all('l1' in keys and not ({'rleft','rright'} & keys) for keys in actions)
    assert 'rdown' in actions[0] and 'r1' not in actions[0]
    assert 'r1' in actions[1] and 'r1' in actions[3]
    assert combat.stats['bow_body_error_deg']==-50.
    assert combat.stats['bow_aim_error_deg']==[0.,0.]


def test_bow_small_camera_yaw_error_ignores_opposite_body_turn_direction(tmp_path):
    memory,state=scene()
    state['player']['rot']=math.radians(50)
    # Body would request right, but the actual camera aim needs a small left correction.
    state['camera']['at']=(-math.tan(math.radians(3))*1000,110.,1000.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    keys=tick(combat,state,1.)['hold']
    assert 'l1' in keys and 'rleft' in keys and 'rright' not in keys
    assert 'r1' not in keys


def test_bow_large_turn_has_hysteresis_across_camera_pose_changes(tmp_path):
    memory,state=scene()
    state['player']['rot']=math.radians(90)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    actions=[]
    for i,(body,camera) in enumerate(((90,80),(70,55),(20,20),(50,50))):
        state['player']['rot']=math.radians(body)
        state['camera']['at']=(math.tan(math.radians(camera))*1000,110.,1000.)
        actions.append(tick(combat,state,1.+i*.1)['hold'])
    assert all('rright' in keys and 'l1' not in keys for keys in actions[:2])
    assert all('l1' in keys for keys in actions[2:])
    assert not any('r1' in keys for keys in actions)


def test_bow_waits_for_native_aim_before_using_orbit_camera(tmp_path):
    memory,state=scene()
    state['player']['action']=0
    state['camera']['at']=(1000.,500.,0.)
    memory.put(ACT,'>I',0)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert tick(combat,state,1.)=={'hold':{'l1'}}
    assert tick(combat,state,1.9)=={'hold':{'l1'}}
    assert not combat.needs_firing_position
    state['player']['action']=2
    state['camera']['at']=(0.,110.,1000.)
    assert {'l1','r1'}<=tick(combat,state,1.95)['hold']
    assert combat.stats['bow_aim_phase']=='tracking with aim held'


def test_bow_native_pose_wait_is_bounded_and_does_not_invent_shots(tmp_path):
    memory,state=scene()
    state['player']['action']=0
    memory.put(ACT,'>I',0)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert tick(combat,state,1.)=={'hold':{'l1'}}
    assert tick(combat,state,2.1)=={'hold':set()}
    assert combat.needs_firing_position and combat.stats['shots']==0
    combat.needs_firing_position=False  # driver has completed its supported reposition
    assert tick(combat,state,3.2)=={'hold':{'l1'}}


def test_bow_owned_fire_pose_keeps_tracking_through_non_aim_action_byte(tmp_path):
    memory,state=scene()
    state['player']['action']=6
    memory.put(ACT,'>I',C.FIRE_VT)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert {'l1','r1'}<=tick(combat,state,1.)['hold']
    assert combat.stats['bow_aim_phase']=='tracking with aim held'


def test_bow_retains_live_target_when_nearby_enemies_trade_nearest_distance(tmp_path):
    memory,state=scene()
    first=state['enemies'][0]
    first['pos']=(0.,0.,160.)
    second={**first,'ptr':first['ptr']+0x1000,'slot':1,'pos':(150.,0.,80.)}
    state['enemies']=[first,second]
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert combat.choose_target(state,state['player'],state['enemies'],1.) is first
    second['pos']=(140.,0.,50.)  # now closer by11cm, but still on the opposite side of the aim
    assert combat.choose_target(state,state['player'],state['enemies'],1.1) is first
    first['pos']=(0.,0.,178.)
    assert combat.choose_target(state,state['player'],state['enemies'],1.2) is first
    assert combat.stats.get('bow_target_changes',0)==0
    first['hp']=0
    assert combat.choose_target(state,state['player'],state['enemies'],1.3) is second
    assert combat.stats['bow_target_changes']==1


def test_bow_target_retention_yields_to_contact_threat_and_blocked_target(tmp_path):
    memory,state=scene()
    first=state['enemies'][0]
    first['pos']=(0.,0.,200.)
    second={**first,'ptr':first['ptr']+0x1000,'slot':1,'pos':(250.,0.,0.)}
    state['enemies']=[first,second]
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert combat.choose_target(state,state['player'],state['enemies'],1.) is first
    second['pos']=(90.,0.,0.)
    assert combat.choose_target(state,state['player'],state['enemies'],1.1) is second
    assert 'contact threat' in combat.stats['bow_target_policy']
    combat.blocked_until[second['ptr']]=10.
    assert combat.choose_target(state,state['player'],state['enemies'],1.2) is first


def test_gun_nearest_target_policy_is_unchanged_by_bow_retention(tmp_path):
    memory,state=scene(0x12)
    first=state['enemies'][0]
    first['pos']=(0.,0.,160.)
    second={**first,'ptr':first['ptr']+0x1000,'slot':1,'pos':(170.,0.,0.)}
    state['enemies']=[first,second]
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert combat.choose_target(state,state['player'],state['enemies'],1.) is first
    second['pos']=(150.,0.,0.)
    assert combat.choose_target(state,state['player'],state['enemies'],1.1) is second


def test_committed_bow_turn_finishes_after_lowering_leaves_ready_pose(tmp_path):
    memory,state=scene()
    state['player']['rot']=math.radians(90)
    state['camera']['at']=(1000.,110.,0.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert tick(combat,state,1.)=={'hold':{'rright'}}
    # The game leaves READY/FIRE after releasing L1. The orbit camera then
    # swings independently; it cannot force another premature raise.
    state['player']['action']=0
    memory.put(ACT,'>I',0)
    for now,body in ((1.1,70),(1.2,40)):
        state['player']['rot']=math.radians(body)
        state['camera']['at']=(-1000.,500.,0.)
        assert tick(combat,state,now)=={'hold':{'rright'}}
        assert combat.stats['aim_feedback']=='current body heading; orbit camera withheld'
    state['player']['rot']=math.radians(20)
    assert tick(combat,state,1.3)=={'hold':{'l1'}}
    state['player']['action']=2
    state['camera']['at']=(0.,110.,1000.)
    assert {'l1','r1'}<=tick(combat,state,1.4)['hold']


@pytest.mark.parametrize('change',['stalled','target','crossed'])
def test_committed_bow_turn_is_bounded_and_cancels_when_its_goal_changes(tmp_path,change):
    memory,state=scene()
    state['player']['rot']=math.radians(90)
    state['camera']['at']=(1000.,110.,0.)
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert tick(combat,state,1.)=={'hold':{'rright'}}
    state['player']['action']=0
    memory.put(ACT,'>I',0)
    now=1.1
    if change=='stalled': now=1.8
    if change=='target': state['enemies'][0]['ptr']+=0x1000
    if change=='crossed': state['player']['rot']=math.radians(-30)
    action=tick(combat,state,now)
    assert 'rright' not in action['hold'] and 'rleft' not in action['hold']
    if change=='stalled':
        assert action=={'hold':set()} and combat.needs_firing_position
    else:
        assert action=={'hold':{'l1'}}
