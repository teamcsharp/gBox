"""A policy test is not proof that a native Player 2 input adapter works."""
from copy import deepcopy
import math

import pytest

from gbox.mercs.cooperation import FollowProtect
from gbox.mercs.titles.re5_nav import NavMesh


def world(units_per_m=100.):
    scale=units_per_m/100.
    mesh=NavMesh([(x*scale,y*scale,z*scale) for x,y,z in [(0.,0.,0.),(3000.,0.,0.),(3000.,0.,2000.),(0.,0.,2000.)]],
                 [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    provenance={'native_actor_verified':True,'control_source':'operator_assignment_and_bot_input_fence'}
    human={'id':'p1','slot':1,'actor':101,'control':'human','pos':[1800.*scale,0.,500.*scale],
           'hp':1000,'hp_max':1000,'provenance':dict(provenance)}
    bot={'id':'p2','slot':2,'actor':202,'control':'bot','pos':[300.*scale,0.,500.*scale],
         'hp':1000,'hp_max':1000,'provenance':dict(provenance)}
    snap={'title':'BLUS30491','session_id':'worker-session','player':dict(bot),'players':[human,bot],'enemies':[]}
    proof={'verified':True,'controller2_verified':True,'camera2_verified':True,'prompt2_verified':True,
           'control_player':2,'p1_actor':101,'p2_actor':202,'geometry':mesh.learning_sig,
           'session_id':'worker-session','observed_at':10.,'title':'BLUS30491'}
    return mesh,snap,proof


def plan(policy,mesh,snap,proof,now=10.,**extra):
    return policy.plan(snap,mesh,now,ownership=proof,session_id='worker-session',**extra)


def move(snap,slot,position):
    snap['players'][slot-1]['pos']=list(position)
    if slot==2:snap['player']['pos']=list(position)


def test_follow_returns_a_standoff_route_with_no_inputs_memory_writes_or_p1_mutation():
    mesh,snap,proof=world();before=deepcopy(snap)
    out=plan(FollowProtect(units_per_m=100.,title='BLUS30491'),mesh,snap,proof)
    assert out['state']=='follow' and out['goal']['kind']=='follow_human'
    assert 270.<=math.dist(out['goal']['pos'],snap['players'][0]['pos'])<=350.01
    assert all(mesh.floor_segment(a,b) for a,b in zip([snap['player']['pos']]+out['route'],out['route']))
    assert all(mesh.hazard_segment_clear(a,b,[(snap['players'][0]['pos'],160.)])
               for a,b in zip([snap['player']['pos']]+out['route'],out['route']))
    assert not any(k in out for k in ('hold','tap','buttons','input','ram_writes'))
    assert snap==before and out['provenance']['p2_actor']==202


@pytest.mark.parametrize('flag',['verified','controller2_verified','camera2_verified','prompt2_verified'])
def test_any_missing_player2_native_scope_refuses_without_p1_fallback(flag):
    mesh,snap,proof=world();proof[flag]=False
    out=plan(FollowProtect(units_per_m=100.),mesh,snap,proof)
    assert out['state']=='unavailable' and out['goal'] is None and out['route']==[]


@pytest.mark.parametrize('fault',['session','geometry','title','stale','future','p1_actor','p2_actor','primary','role','provenance','duplicate','position'])
def test_changed_or_stale_context_never_becomes_a_follow_goal(fault):
    mesh,snap,proof=world()
    if fault=='session':proof['session_id']='another-session'
    if fault=='geometry':proof['geometry']='another-topology'
    if fault=='title':proof['title']='BH6'
    if fault=='stale':proof['observed_at']=9.
    if fault=='future':proof['observed_at']=11.
    if fault=='p1_actor':proof['p1_actor']=202
    if fault=='p2_actor':proof['p2_actor']=101
    if fault=='primary':snap['player']=dict(snap['players'][0])
    if fault=='role':snap['players'][0]['control']='bot'
    if fault=='provenance':snap['players'][1]['provenance']={}
    if fault=='duplicate':snap['players'].append(dict(snap['players'][1]))
    if fault=='position':snap['players'][1]['pos']=[500.,0.,500.]
    out=plan(FollowProtect(units_per_m=100.,title='BLUS30491'),mesh,snap,proof)
    assert out['state']=='unavailable' and not out['route'] and out['protect_target'] is None


@pytest.mark.parametrize('priority',['mandatory_qte','recovery_active','healing','mine_escape','cooperation_pause','low_hp'])
def test_self_healing_qte_and_mine_departure_keep_priority(priority):
    mesh,snap,proof=world()
    if priority=='low_hp':
        snap['player']['hp']=snap['players'][1]['hp']=400
    else:snap[priority]=True
    out=plan(FollowProtect(units_per_m=100.),mesh,snap,proof)
    assert out['state']=='paused' and out['goal'] is None and not out['route']


def test_goal_hysteresis_avoids_repeated_retargeting_and_close_distance_moves_away():
    mesh,snap,proof=world();policy=FollowProtect(units_per_m=100.)
    first=plan(policy,mesh,snap,proof)
    move(snap,1,(1810.,0.,500.));proof['observed_at']=10.1
    second=plan(policy,mesh,snap,proof,10.1)
    assert second['goal']['id']==first['goal']['id'] and second['goal']['pos']==first['goal']['pos']
    move(snap,2,(1460.,0.,500.));proof['observed_at']=10.2
    assert plan(policy,mesh,snap,proof,10.2)['state']=='hold'
    move(snap,1,(1900.,0.,500.));proof['observed_at']=10.3
    assert plan(policy,mesh,snap,proof,10.3)['state']=='hold'
    move(snap,1,(2100.,0.,500.));proof['observed_at']=10.4
    assert plan(policy,mesh,snap,proof,10.4)['state']=='follow'
    move(snap,1,(1800.,0.,500.));move(snap,2,(1700.,0.,500.));proof['observed_at']=10.5
    retreat=plan(policy,mesh,snap,proof,10.5)
    assert retreat['state']=='follow' and math.dist(retreat['goal']['pos'],snap['players'][0]['pos'])>=270.
    assert all(mesh.hazard_segment_clear(a,b,[(snap['players'][0]['pos'],160.)],departing=True)
               for a,b in zip([snap['player']['pos']]+retreat['route'],retreat['route']))


def test_a_new_blocked_portal_or_current_mine_invalidates_cached_movement_immediately():
    mesh,snap,proof=world();policy=FollowProtect(units_per_m=100.)
    first=plan(policy,mesh,snap,proof);assert first['state']=='follow'
    proof['observed_at']=10.1
    out=plan(policy,mesh,snap,proof,10.1,blocked_links={(1,0)})
    assert out['state']=='blocked' and not out['route']
    policy.reset()
    blocked=plan(policy,mesh,snap,proof,10.1,hazards=[(snap['players'][0]['pos'],600.)])
    assert blocked['state']=='blocked' and blocked['goal'] is None


def test_protection_prefers_fresh_exposed_threats_near_human_without_inventing_los():
    mesh,snap,proof=world()
    snap['enemies']=[{'ptr':301,'hp':800,'pos':[1900.,0.,500.],'sightable':True},
                     {'ptr':302,'hp':800,'pos':[2200.,0.,500.]},
                     {'ptr':303,'hp':800,'pos':[500.,0.,1700.]}]
    exposures=[{'observer_actor':202,'target_actor':e['ptr'],'clear':True,'verified':True,
                'observed_at':10.,'source':'native_first_hit'} for e in snap['enemies']]
    out=plan(FollowProtect(units_per_m=100.),mesh,snap,proof,exposures=exposures)
    assert out['state']=='protect' and out['protect_target']==301
    assert out['threat_bias'][301]>out['threat_bias'][302] and 303 not in out['threat_bias']
    assert out['threats'][0]['exposure']['observer_actor']==202
    unknown=plan(FollowProtect(units_per_m=100.),mesh,snap,proof)
    assert unknown['protect_target'] is None and not unknown['threat_bias']


@pytest.mark.parametrize('fault',['observer','stale','source','blocked','unverified'])
def test_unknown_corridor_or_other_players_exposure_is_not_firing_evidence(fault):
    mesh,snap,proof=world();snap['enemies']=[{'ptr':301,'hp':800,'pos':[1900.,0.,500.]}]
    exposure={'observer_actor':202,'target_actor':301,'clear':True,'verified':True,'observed_at':10.,'source':'native_raycast'}
    if fault=='observer':exposure['observer_actor']=101
    if fault=='stale':exposure['observed_at']=9.
    if fault=='source':exposure['source']='floor_corridor'
    if fault=='blocked':exposure['clear']=False
    if fault=='unverified':exposure['verified']=False
    out=plan(FollowProtect(units_per_m=100.),mesh,snap,proof,exposures=[exposure])
    assert out['protect_target'] is None and out['threat_bias']=={}


def test_standoff_is_scaled_from_metres_for_each_titles_declared_units():
    results=[]
    for units in (100.,1000.):
        mesh,snap,proof=world(units);out=plan(FollowProtect(units_per_m=units),mesh,snap,proof)
        assert out['state']=='follow'
        results.append(tuple(v/units for v in out['goal']['pos']))
    assert results[0]==pytest.approx(results[1])
    for bad in (0.,-1.,float('nan'),float('inf'),True):
        with pytest.raises(ValueError):FollowProtect(units_per_m=bad)


def test_unlinked_floors_never_become_a_straight_line_to_the_human():
    mesh,snap,proof=world()
    mesh.links=[[],[]]
    # Rebuild to give the changed directed topology its own exact identity.
    mesh=NavMesh(mesh.points,mesh.tris,mesh.links);proof['geometry']=mesh.learning_sig
    out=plan(FollowProtect(units_per_m=100.),mesh,snap,proof)
    assert out['state']=='blocked' and out['route']==[]


def test_candidate_action_link_needs_title_owned_traversal_confirmation():
    lower=[(0.,0.,0.),(2000.,0.,0.),(2000.,0.,2000.),(0.,0.,2000.)]
    upper=[(2500.,300.,0.),(4500.,300.,0.),(4500.,300.,2000.),(2500.,300.,2000.)]
    mesh=NavMesh(lower+upper,[(0,1,2),(0,2,3),(4,5,6),(4,6,7)],
                 [[(1,2,1.),(2,1,1.)],[(0,0,1.)],[(3,2,1.)],[(2,0,1.)]])
    _,snap,proof=world();move(snap,1,(3500.,300.,500.));move(snap,2,(1500.,0.,500.));proof['geometry']=mesh.learning_sig
    denied=plan(FollowProtect(units_per_m=100.),mesh,snap,proof)
    assert denied['state']=='blocked' and not denied['route']
    calls=[]
    def confirmed(waypoint,owner):
        calls.append((waypoint,owner['p2_actor']))
        return True
    allowed=plan(FollowProtect(units_per_m=100.),mesh,snap,proof,traversal_check=confirmed)
    assert allowed['state']=='follow' and any(hasattr(p,'approach') for p in allowed['route'])
    assert calls and all(actor==202 for _,actor in calls)


def test_safety_pause_preserves_goal_but_native_actor_change_resets_it():
    mesh,snap,proof=world();policy=FollowProtect(units_per_m=100.)
    first=plan(policy,mesh,snap,proof)
    snap['healing']=True;proof['observed_at']=10.1
    assert plan(policy,mesh,snap,proof,10.1)['state']=='paused'
    snap['healing']=False;proof['observed_at']=10.2
    assert plan(policy,mesh,snap,proof,10.2)['goal']['id']==first['goal']['id']
    snap['players'][1]['actor']=snap['player']['actor']=proof['p2_actor']=909
    proof['observed_at']=10.3
    out=plan(policy,mesh,snap,proof,10.3)
    assert out['provenance']['p2_actor']==909 and out['state']=='follow'
    assert out['goal']['id']!=first['goal']['id']
