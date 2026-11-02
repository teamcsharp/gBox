from pso_owned_evidence import original_test_path
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_pso_frontier import state
from gbox import pso_coop as C
from gbox.pso_coop_nav import Maps


def margin_state():
    st=state();st['geometry_players']={}
    st['geometry_recovery_players']={2:dict(source='verified_native_collision_base',
        geometry_identity='known',geometry_layer='floor',player_ptr='2',
        start=dict(x=22.5,y=0.,z=22.5),path=[[22.5,22.5],[22.5,27.5]],
        path_heights=[0.,0.],path_length=5.,waypoint=dict(x=22.5,z=27.5))}
    return st


def controller(st,tmp_path,monkeypatch):
    commands=[]
    inputs=SimpleNamespace(hold=lambda rows:commands.extend(rows),speed=lambda:2,stopped=lambda:False,
        wall_learning_safe=lambda:True)
    reader=SimpleNamespace(ad=None,snapshot=lambda:copy.deepcopy(st))
    c=C.Controller(reader,inputs,Maps(tmp_path));monkeypatch.setattr(C.solo,'wait',lambda *_:None)
    return c,commands


def test_only_quiet_slot_recovers_short_bound_then_holds_without_learning(tmp_path,monkeypatch):
    st=margin_state();c,commands=controller(st,tmp_path,monkeypatch)
    learned=[]
    monkeypatch.setattr(C,'time',SimpleNamespace(monotonic=lambda:1))
    for nav in [c.maps.get(st,p) for p in st['players'].values()]:
        monkeypatch.setattr(nav,'observe',lambda *a,**k:learned.append(k))
    for _ in range(8):assert c.tick(st)
    assert not c.tick(st)
    moves=[row for row in commands if row[1]!=['l']]
    assert len(moves)==8 and all(slot==2 and duration==.04 for slot,_,duration in moves)
    assert not learned
    assert c.field.status['players']['2']['dependency']=='margin_recovery_limit'


@pytest.mark.parametrize('change',['actor','layout','start','long','waypoint','nan','travelling','dead','unknown'])
def test_stale_or_unbounded_margin_proof_never_moves(change,tmp_path,monkeypatch):
    st=margin_state();proof=st['geometry_recovery_players'][2]
    if change=='actor':proof['player_ptr']='other'
    elif change=='layout':proof['geometry_identity']='other'
    elif change=='start':proof['start']['x']+=1
    elif change=='long':proof['path'][-1]=[22.5,42.5];proof['path_length']=20
    elif change=='waypoint':proof['waypoint']['x']=24
    elif change=='nan':proof['path_heights'][0]=float('nan')
    elif change=='travelling':st['travelling']=True
    elif change=='dead':st['players'][2]['hp']=0
    elif change=='unknown':proof['source']='guessed'
    c,commands=controller(st,tmp_path,monkeypatch)
    assert not c.tick(st)
    assert all(row[1]==['l'] for row in commands)


@pytest.mark.parametrize('kind',['pursuit','retreat','aim','attack'])
def test_missing_projection_never_uses_generic_combat_route(kind,tmp_path,monkeypatch):
    st=margin_state();st['geometry_recovery_players']={}
    p=st['players'][1]
    x,z=(p['x'],p['z']+30) if kind=='pursuit' else (p['x'],p['z']+5)
    if kind=='aim':x,z=p['x']+5,p['z']
    if kind=='retreat':p['hp']=5
    st['entities']=[dict(kind='enemy',hp=92,ptr='80ABCDEF',**{'class':'TObjEneBeast'},x=x,y=0.,z=z,room=p['room'])]
    c,commands=controller(st,tmp_path,monkeypatch)
    c.tick(st)
    moves=[row for row in commands if row[0]==1 and row[1]!=['l']]
    if kind=='pursuit':assert not moves
    elif kind=='aim':assert moves and all(duration==.02 for _,_,duration in moves)
    else:assert moves and all(keys==['a'] for _,keys,_ in moves)


def test_model_goal_cannot_replace_known_layout_missing_projection(tmp_path,monkeypatch):
    st=margin_state();st['geometry_recovery_players']={}
    c,commands=controller(st,tmp_path,monkeypatch)
    c.accept_goals({'goals':[dict(player=2,room=16,x=30.,z=30.)]},st)
    assert not c.tick(st)
    assert all(row[1]==['l'] for row in commands)


def test_actual_native_margin_proof_passes_controller_for_p2_but_not_threatened_p1(tmp_path,monkeypatch):
    base=original_test_path('party-coordination/tests/test_margin_controller.py').resolve().parents[2]
    evidence=json.loads((base/'observer-v1/layer-evidence-1793631324322752100.json').read_text())['result']
    proofs=json.loads((base/'field-margin-recovery/real-forest-paths.json').read_text())['players']
    st=state();st['players']={int(k):v for k,v in evidence['native']['players'].items()}
    st['geometry_identity']=proofs['2']['row']['geometry_identity'];st['geometry_players']={}
    st['geometry_recovery_players']={int(k):v['row'] for k,v in proofs.items()}
    p=st['players'][1]
    st['entities']=[dict(kind='enemy',hp=92,ptr='80ABCDEF',**{'class':'TObjEneBeast'},
        x=p['x'],y=p['y'],z=p['z']+5,room=p['room'])]
    c,commands=controller(st,tmp_path,monkeypatch)
    assert c.tick(st)
    moves=[row for row in commands if row[0]==2 and row[1]!=['l']]
    assert len(moves)==1 and moves[0][2]==.04
    assert c.margin_attempts[2]['attempts']==1 and 1 not in c.margin_attempts
    assert c.field.status['players']['2']['dependency']=='margin_recovery'


def test_failed_other_player_search_reobserves_once_without_starving_combat(tmp_path,monkeypatch):
    from test_pso_frontier import grid,gate
    st=state();st['players'][1]['room']=11;st['players'][2]['room']=15
    st['players'][1]['x']=62.5
    st['entities']=[dict(kind='enemy',hp=92,ptr='80ABCDEF',**{'class':'TObjEneBeast'},
        x=62.5,y=0.,z=27.5,room=11)]
    nav=grid();nav.walls.add(nav.cell((62.5,22.5)))
    c,commands=controller(st,tmp_path,monkeypatch)
    monkeypatch.setattr(c.maps,'get',lambda *_:nav)
    assert not c.tick(st)
    assert all(keys==['l'] for _,keys,_ in commands)
    commands.clear()
    assert c.tick(st)
    assert any(slot==1 and keys==['a'] for slot,keys,_ in commands)
    assert not any(slot==2 and keys!=['l'] for slot,keys,_ in commands)
