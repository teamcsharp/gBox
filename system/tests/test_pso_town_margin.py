from pso_owned_evidence import original_test_path
import copy
import importlib.util
import math
from pathlib import Path

import pytest

from gbox import pso_coop_town as T

ROOT = original_test_path('margin-recovery/test_town_margin.py').resolve().parent
import test_pso_town_route as F
corridor = F.corridor


def observed(start=(203.788,195.838)):
    state = F.observed()
    state.update(geometry_verified=True, geometry_identity=T.GEOMETRY_ID,
                 geometry_source={'triangles_sha256': T.TRIANGLES_SHA})
    state['players'][1].update(x=T.PLATFORM[0],y=1.,z=T.PLATFORM[1])
    state['players'][2].update(x=start[0],y=0.,z=start[1])
    return state


@pytest.mark.parametrize('start', [(203.788,195.838),(204.464,207.082),(207.141,206.495)])
def test_real_margin_connectors_remain_on_base_and_end_in_safe_route(corridor,start):
    assert corridor.cell(start) in corridor.base and corridor.cell(start) not in corridor.safe
    route = corridor.recover(start)
    assert route and sum(math.dist(a,b) for a,b in zip(route,route[1:])) <= 12
    assert all(corridor._clear(a,b,corridor.base) for a,b in zip(route,route[1:]))
    assert corridor.cell(route[-1]) in corridor.safe and corridor.route(route[-1])


@pytest.mark.parametrize('bad', ['unknown_layout','different_layout','missing_source','high_player','unknown_floor','no_route'])
def test_recovery_never_borrows_unknown_geometry(corridor,bad):
    state = observed()
    if bad=='unknown_layout':state['geometry_verified']=False
    elif bad=='different_layout':state['geometry_identity']='other'
    elif bad=='missing_source':state['geometry_source']={}
    elif bad=='high_player':state['players'][2]['y']=10.
    elif bad=='unknown_floor':state['players'][2].update(x=0.,z=0.)
    else:state['players'][2].update(x=180.,z=5.)
    policy=T.TownRoute(None,corridor=corridor)
    assert not policy.plan(state,0.)


def test_margin_inputs_are_short_fresh_and_limited(corridor,monkeypatch,tmp_path):
    state=observed()
    controller,calls=F.bot(monkeypatch,tmp_path,state,corridor)
    assert controller.tick(state)
    assert calls[-1][0][0]==2 and calls[-1][0][2]==.04
    assert controller.town.status['clearance_unknown_players']==[2]
    assert not controller.town.status['dynamic_doors_verified']
    assert controller.town.rows[2]['margin_attempts']==1
    for i in range(12):controller.tick(state)
    moves=[command for call in calls for command in call if command[1] != ['l']]
    assert len(moves)==8
    assert controller.town.rows[2]['halted']
    assert not controller.town.plan(state,100000.)


def test_return_to_interior_clears_unknown_and_uses_normal_pulse(corridor):
    state=observed(); policy=T.TownRoute(None,corridor=corridor)
    assert 2 in policy.plan(state,0.)
    policy.moved(2)
    target=corridor.recover((state['players'][2]['x'],state['players'][2]['z']))[-1]
    state['players'][2].update(x=target[0],z=target[1])
    assert 2 in policy.plan(state,1.)
    assert policy.pulse_seconds(2)==.08 and policy.rows[2]['margin_attempts']==0
    assert policy.status['clearance_unknown_players']==[]


def test_recenter_reobservation_rejects_new_actor_or_unknown_mesh(corridor,monkeypatch,tmp_path):
    state=observed();controller,calls=F.bot(monkeypatch,tmp_path,state,corridor)
    fresh=copy.deepcopy(state);fresh['geometry_verified']=False
    controller.reader.snapshot=lambda:fresh
    assert not controller.tick(state)
    assert len(calls)==1 and all(keys==['l'] for _,keys,_ in calls[0])


def grid(base,safe):
    result=object.__new__(T.Corridor);result.base=base;result.safe=safe
    return result


def test_gap_corner_exclusion_and_distance_are_not_shortcuts():
    disconnected=grid({(0,0),(2,0)}, {(2,0)})
    assert disconnected.recover((1.25,1.25)) is None
    diagonal=grid({(0,0),(1,1)}, {(1,1)})
    assert diagonal.recover((1.25,1.25)) is None
    long=grid({(n,0) for n in range(10)}, {(9,0)})
    assert long.recover((1.25,1.25)) is None
    short=grid({(n,0) for n in range(4)}, {(3,0)})
    assert short.recover((1.25,1.25))
    assert short.recover((1.25,1.25), {(1,0)}) is None


def test_overlapping_upper_floor_never_creates_recovery_base():
    floor=((180.,0.,5.),(380.,0.,5.),(180.,0.,290.),0,(0.,1.,0.))
    upper=(*(tuple((x,10.,z) for x,y,z in floor[:3])),0,(0.,1.,0.))
    corridor=T.Corridor([floor,upper])
    assert not corridor.base and corridor.recover((190.,20.)) is None


def test_start_outside_base_or_already_safe_never_projects(corridor):
    assert corridor.recover((math.nan,20.)) is None
    assert corridor.recover((0.,0.)) is None
    assert corridor.recover((198.75,196.25)) is None
