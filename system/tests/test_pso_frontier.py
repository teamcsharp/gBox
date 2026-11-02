from pso_owned_evidence import original_test_path
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import pso_coop as C
from gbox.pso_coop_frontier import FieldObjectives,field_actions,same_room_threats
from gbox.pso_coop_geometry import Atlas
from gbox.pso_coop_nav import Maps,RoomMap

BASE=original_test_path('field-navigation/tests/test_frontier.py').resolve().parents[2]

@pytest.fixture(scope='module')
def actual():
    r=json.loads((BASE/'observer-v1/field-geometry-receipt-1793622503722814000.json').read_text())['result']
    assert r['exact_geometry_file_match'] and r['geometry_sha256']=='2f1c7a9652eebdf1fc62add0416c4a0f56adc9e4607194a9f48106367ec289a1'
    st=copy.deepcopy(r['state']);st['players']={int(k):v for k,v in st['players'].items()}
    st.update(geometry_verified=True,geometry_identity=r['geometry_sha256'])
    st['entities']=[dict(row['entity'],kind='gate' if row['entity']['class'].startswith(('TObjDoor','TObjLazerFence','TOBarrier')) else 'object') for row in r['interactive_objects']]
    atlas=Atlas(r['triangles']);st['geometry_players']={}
    for slot,p in st['players'].items():
        p.update(controller=slot,hp=33,hp_max=33,heading_deg=0)
        v=atlas.project(p);assert v
        st['geometry_players'][slot]=dict(v,geometry_identity=st['geometry_identity'])
    return st

def grid():
    floor=[(x,z) for x in range(50) for z in range(50)]
    return RoomMap(size=5,floor=floor,heights=[[*c,0.] for c in floor])

def state():
    players={s:dict(controller=s,ptr=str(s),x=22.5,y=0.,z=22.5,hp=33,hp_max=33,heading_deg=0,room=16) for s in (1,2)}
    return dict(verified=True,phase=14,floor=1,episode=1,geometry_verified=True,geometry_identity='known',
        geometry_players={s:dict(geometry_identity='known',geometry_layer='floor') for s in players},players=players,entities=[])

def gate(x=82.5,z=22.5,room=11):
    return dict(kind='gate',**{'class':'TOBarrierEnergy01'},entity_id=16490,ptr='80DB75B0',x=x,y=0.,z=z,room=room)

def test_real_forest_gate_is_reachable_not_a_renamed_container(actual,tmp_path):
    st=copy.deepcopy(actual);f=FieldObjectives();maps=Maps(tmp_path)
    for slot,p in st['players'].items():
        nav=maps.get(st,p);destination=f.destination(st,slot,nav,0)
        assert destination
        row=f.status['players'][str(slot)]
        assert row['exit']['class']=='TOBarrierEnergy01' and row['exit']['entity_id']==16490
        assert row['predicate']=='unknown' and not f.status['room_clear_verified']
        route=nav.route((p['x'],p['z']),destination)
        assert route and route[1][0]<p['x']
        assert all(nav.allowed(nav.cell(a),nav.cell(b)) for a,b in zip(route,route[1:]))

def test_enemy_other_room_does_not_block_frontier_but_same_room_does():
    st=state();st['entities']=[dict(kind='enemy',hp=56,room=11)]
    f=FieldObjectives();nav=grid()
    assert not same_room_threats(st,st['players'][1])
    assert f.destination(st,1,nav,0)
    st['entities'][0]['room']=16
    assert same_room_threats(st,st['players'][1])
    assert f.destination(st,1,nav,1) is None
    assert f.status['players']['1']['exit'] is None
    assert f.status['players']['1']['dependency']=='combat'

@pytest.mark.parametrize('change',[{'verified':False},{'phase':3},{'floor':0},{'geometry_verified':False}])
def test_unverified_or_town_has_no_field_authority(change):
    st=state();st.update(change)
    assert FieldObjectives().destination(st,1,grid(),0) is None

def test_layer_does_not_borrow_buddy_or_gate_height():
    st=state();st['entities']=[gate()];st['entities'][0]['y']=30
    f=FieldObjectives();f.destination(st,1,grid(),0)
    assert f.status['players']['1']['exit'] is None
    st['geometry_players'].pop(1)
    assert f.destination(st,1,grid(),1) is None

def test_failed_gate_approach_is_deferred_and_never_called_open():
    st=state();st['entities']=[gate()];f=FieldObjectives();nav=grid()
    assert f.destination(st,1,nav,0)==(82.5,22.5)
    assert f.destination(st,1,nav,7) is None
    assert f.status['players']['1']['outcome']=='blocked'
    f.destination(st,1,nav,8)
    assert f.status['players']['1']['exit'] is None

def test_gate_requires_real_proximity_not_broad_waypoint_arrival():
    st=state();st['entities']=[gate()];f=FieldObjectives();nav=grid();f.destination(st,1,nav,0)
    st['players'][1]['x']=75.5
    assert f.destination(st,1,nav,1)==(82.5,22.5)
    st['players'][1]['x']=81.
    f.destination(st,1,nav,2)
    assert f.status['last_outcome']['outcome']=='approach_reached'
    assert f.status['last_outcome']['passability_verified'] is False

def test_leader_waits_for_buddy_and_observed_room_change_is_not_clear():
    st=state();st['players'][2]['x']=220
    f=FieldObjectives();assert f.destination(st,1,grid(),0) is None
    assert f.status['players']['1']['outcome']=='waiting_for_buddy'
    st['players'][1]['room']=11;f.destination(st,1,grid(),1)
    assert f.status['last_transition']==dict(player=1,from_room=16,to_room=11)
    assert f.status['room_clear_verified'] is False

def test_field_start_is_removed_even_when_combined_and_menu_start_unchanged():
    selected=[(1,['start'],.1),(2,['lup','start'],.1),(2,['a'],.1)]
    assert field_actions(selected,state())==[(2,['a'],.1)]
    st=state();st['phase']=9
    assert field_actions(selected,st)==selected

def test_p2_regroups_before_choosing_different_gate_and_cannot_cross_layer():
    st=state();st['players'][1]['x']=180.;st['entities']=[gate()]
    f=FieldObjectives();nav=grid()
    assert f.destination(st,1,nav,0) is None
    assert f.destination(st,2,nav,0)==(180.,22.5)
    assert f.status['players']['2']['dependency']=='buddy_regroup'
    st['geometry_players'][1]['geometry_layer']='bridge'
    assert f.destination(st,2,nav,1) is None
    assert f.status['state']=='no_verified_regroup_route'

def test_controller_uses_real_grid_without_model_goals(actual,tmp_path,monkeypatch):
    st=copy.deepcopy(actual);st['entities']=[e for e in st['entities'] if e.get('kind')!='enemy']
    commands=[];inputs=SimpleNamespace(hold=lambda rows:commands.extend(rows),speed=lambda:2,stopped=lambda:False,wall_learning_safe=lambda:False)
    reader=SimpleNamespace(snapshot=lambda:copy.deepcopy(st),ad=None)
    controller=C.Controller(reader,inputs,Maps(tmp_path));monkeypatch.setattr(C.solo,'wait',lambda *_:None)
    assert not controller.tick(st)  # First bounded search requires reobservation.
    assert all(row[1]==['l'] for row in commands)
    assert controller.tick(st)
    movement=[row for row in commands if any(k.startswith('l') and k!='l' for k in row[1])]
    assert {row[0] for row in movement}=={1,2}
    assert all(row[2]==.08 for row in movement)
    assert not controller.goals

@pytest.mark.parametrize('change',['actor','geometry','layer','unverified_geometry'])
def test_wall_learning_rejects_identity_change_after_movement(actual,tmp_path,monkeypatch,change):
    st=copy.deepcopy(actual);st['entities']=[e for e in st['entities'] if e.get('kind')!='enemy']
    after=copy.deepcopy(st)
    if change=='actor':after['players'][1]['ptr']='80FFFFFF'
    elif change=='geometry':after['geometry_players'][1]['geometry_identity']='new-layout'
    elif change=='layer':after['geometry_players'][1]['geometry_layer']='other-height'
    else:after.pop('geometry_players');after['geometry_verified']=False
    calls=[]
    reader=SimpleNamespace(ad=None,snapshot=lambda:copy.deepcopy(st if not calls else after))
    inputs=SimpleNamespace(hold=lambda rows:calls.append(rows) if any(row[1]!=['l'] for row in rows) else None,
        speed=lambda:2,stopped=lambda:False,wall_learning_safe=lambda:True)
    controller=C.Controller(reader,inputs,Maps(tmp_path))
    for slot,p in st['players'].items():controller.field.destination(st,slot,controller.maps.get(st,p),0)
    monkeypatch.setattr(C.solo,'wait',lambda *_:None);monkeypatch.setattr(C.time,'monotonic',lambda:1.)
    reliable=[]
    monkeypatch.setattr(RoomMap,'observe',lambda *a,**kw:reliable.append(kw['reliable']) or False)
    assert controller.tick(st)
    assert reliable[0] is False
