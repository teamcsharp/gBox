import copy
import pytest
from test_pso_frontier import state,grid,gate
from gbox.pso_coop_frontier import FieldObjectives


def split():
    st=state();st['players'][1].update(x=62.5,room=11)
    st['players'][2].update(x=22.5,room=15)
    return st


def test_room_split_below_old_distance_threshold_holds_leader_and_regroups_p2():
    st=split();f=FieldObjectives();nav=grid()
    assert f.destination(st,1,nav,0) is None
    assert f.status['players']['1']['outcome']=='waiting_for_buddy'
    assert not f.active
    assert f.destination(st,2,nav,0)==(62.5,22.5)
    revision=f.revision;assert revision>0
    assert f.destination(st,2,nav,1)==(62.5,22.5)
    assert f.revision==revision


def test_p2_finishes_own_connector_even_if_leader_completed_shared_gate():
    st=state();st['entities']=[gate()];f=FieldObjectives();nav=grid()
    f.destination(st,1,nav,0);f.destination(st,2,nav,0)
    old=copy.deepcopy(f.active[2]);f.completed.add(old['key']);f.active.pop(1)
    st['players'][1].update(x=102.5,room=11)
    st['players'][2].update(x=72.5,room=15)
    assert f.destination(st,1,nav,1) is None
    assert f.destination(st,2,nav,1)==old['point']
    assert f.status['players']['2']['exit']['entity_id']==16490
    assert f.active[2]['key']==old['key']


def test_follower_commits_to_leader_goal_instead_of_nearest_alternative():
    st=state();st['entities']=[gate(x=82.5),gate(x=22.5,z=70)]
    f=FieldObjectives();nav=grid();leader=f.destination(st,1,nav,0)
    st['players'][2].update(x=22.5,z=52.5)
    assert f.destination(st,2,nav,0)==leader


@pytest.mark.parametrize('kind',['absent','dead','nan'])
def test_missing_or_dead_buddy_holds_quiet_player(kind):
    st=state()
    if kind=='absent':st['players'].pop(2)
    elif kind=='dead':st['players'][2]['hp']=0
    else:st['players'][2]['x']=float('nan')
    f=FieldObjectives();assert f.destination(st,1,grid(),0) is None
    assert f.status['players']['1']['dependency']=='buddy_unavailable'


@pytest.mark.parametrize('kind',['layer','layout','height','blocked'])
def test_regroup_never_borrows_other_layer_layout_or_unreachable_route(kind):
    st=split();nav=grid()
    if kind=='layer':st['geometry_players'][1]['geometry_layer']='bridge'
    elif kind=='layout':st['geometry_players'][1]['geometry_identity']='another-floor'
    elif kind=='height':st['players'][1]['y']=30
    else:nav.walls.add(nav.cell((62.5,22.5)))
    f=FieldObjectives();assert f.destination(st,2,nav,0) is None
    assert f.status['players']['2']['dependency']=='no_verified_regroup_route'


def test_unknown_buddy_projection_holds_leader_but_known_recovery_endpoint_can_be_rendezvous():
    st=state();st['geometry_players'].pop(2);f=FieldObjectives()
    assert f.destination(st,1,grid(),0) is None
    assert f.status['players']['1']['outcome']=='waiting_for_buddy'
    st=split();st['geometry_players'].pop(1)
    st['geometry_recovery_players']={1:dict(source='verified_native_collision_base',
        geometry_identity='known',geometry_layer='floor',player_ptr='1',
        path=[[62.5,22.5],[57.5,22.5]],path_heights=[0.,0.])}
    assert FieldObjectives().destination(st,2,grid(),0)==(57.5,22.5)
    st['geometry_recovery_players'][1]['player_ptr']='other'
    assert FieldObjectives().destination(st,2,grid(),0) is None


def test_own_room_defense_precedes_regroup_even_with_missing_own_grid():
    st=split();st['entities']=[dict(kind='enemy',hp=92,room=11)]
    st['geometry_players'].pop(1)
    f=FieldObjectives();assert f.destination(st,1,grid(),0) is None
    assert f.status['players']['1']['dependency']=='combat'
    st['entities'].append(dict(kind='enemy',hp=92,room=15))
    assert f.destination(st,2,grid(),0) is None
    assert f.status['players']['2']['dependency']=='combat'


def test_failed_regroup_does_not_repeat_forever_and_layout_change_clears_commitment():
    st=split();f=FieldObjectives();nav=grid()
    assert f.destination(st,2,nav,0)
    assert f.destination(st,2,nav,7) is None
    assert f.status['state']=='no_verified_regroup_route'
    st['geometry_identity']='new';st['geometry_players'][1]['geometry_identity']='new'
    st['geometry_players'][2]['geometry_identity']='new'
    assert f.destination(st,2,nav,8)


def test_alternating_failed_connector_and_buddy_cannot_reset_each_others_timeout():
    st=state();st['entities']=[gate()];f=FieldObjectives();nav=grid()
    f.destination(st,1,nav,0);f.destination(st,2,nav,0)
    st['players'][1].update(x=102.5,room=11);st['players'][2].update(x=72.5,room=15)
    assert f.destination(st,2,nav,1)==(82.5,22.5)
    assert f.destination(st,2,nav,8)==(102.5,22.5)
    assert f.destination(st,2,nav,9)==(102.5,22.5)
    assert f.destination(st,2,nav,16) is None
    assert f.destination(st,2,nav,17) is None


def test_route_failure_and_success_cache_force_only_first_observation_and_bind_blocked_edges(monkeypatch):
    st=state();f=FieldObjectives();f._bind(st);nav=grid();calls=[]
    original=nav.route
    monkeypatch.setattr(nav,'route',lambda a,b:calls.append((a,b)) or original(a,b))
    start=(22.5,22.5);goal=(62.5,22.5)
    assert f.route(nav,start,goal);revision=f.revision
    assert f.route(nav,start,goal);assert len(calls)==1 and f.revision==revision
    nav.walls.add(nav.cell(goal));nav.blocked.add(((4,4),(5,4)))
    assert f.route(nav,start,goal) is None;revision=f.revision
    assert f.route(nav,start,goal) is None
    assert len(calls)==2 and f.revision==revision
