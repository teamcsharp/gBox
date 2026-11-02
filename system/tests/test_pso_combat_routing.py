from pso_owned_evidence import original_test_path
import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_pso_frontier import state,grid
from test_pso_margin_controller import controller,margin_state
from gbox import pso_coop as C
from gbox.pso_coop_geometry import Atlas
from gbox.pso_coop_frontier import FieldObjectives
from gbox.pso_coop_nav import Maps

BASE=original_test_path('combat-routing/tests/test_combat_routing.py').resolve().parents[2]
ENVELOPE=dict(horizontal=11.9,vertical=15.3,vertical_half_angle=28.,horizontal_half_angle=20.8)

def enemy(p,**kw):
    return dict(kind='enemy',hp=92,ptr='80ABCDEF',**{'class':'TObjEneBeast'},
                room=p['room'],x=p['x'],y=p['y'],z=p['z']+5)|kw

def test_missing_enemy_cell_uses_reachable_firing_stance_and_cached_route():
    nav=grid();p=state()['players'][1];target=enemy(p,z=82.5)
    nav.floor.remove(nav.cell((target['x'],target['z'])))
    f=FieldObjectives();goal=f.combat_goal(nav,p,target,ENVELOPE)
    assert goal and nav.cell(goal) in nav.floor
    assert math.dist(goal,(target['x'],target['z']))<=11.9*.9
    revision=f.revision
    assert f.combat_goal(nav,p,target,ENVELOPE)==goal and f.revision==revision
    route=f.route(nav,(p['x'],p['z']),goal)
    assert route and f.revision==revision
    assert all(nav.allowed(nav.cell(a),nav.cell(b)) for a,b in zip(route,route[1:]))

@pytest.mark.parametrize('kind',['unknown','height','disconnected','blocked'])
def test_firing_route_does_not_cross_missing_floor_or_height(kind):
    nav=grid();p=state()['players'][1];target=enemy(p,z=82.5)
    if kind=='unknown':nav.floor=None
    elif kind=='height':target['y']=40
    elif kind=='disconnected':nav.floor={c for c in nav.floor if c[1]<=5 or c[1]>=12}
    else:
        start=nav.cell((p['x'],p['z']))
        nav.blocked={(start,(start[0]+dx,start[1]+dz)) for dx,dz in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1))}
    f=FieldObjectives();assert f.combat_goal(nav,p,target,ENVELOPE) is None
    revision=f.revision
    assert f.combat_goal(nav,p,target,ENVELOPE) is None and f.revision==revision

def test_positive_cache_revalidates_exact_moving_target_and_new_blocked_edges():
    nav=grid();p=state()['players'][1];target=enemy(p,z=82.5);f=FieldObjectives()
    old=f.combat_goal(nav,p,target,ENVELOPE);revision=f.revision
    target['z']+=.1
    assert f.combat_goal(nav,p,target,ENVELOPE)==old and f.revision==revision
    target['z']+=30
    new=f.combat_goal(nav,p,target,ENVELOPE)
    assert new!=old and f.revision>revision
    revision=f.revision;nav.blocked.add(((4,4),(4,5)))
    f.combat_goal(nav,p,target,ENVELOPE);assert f.revision>revision

@pytest.mark.parametrize('kind',['attack','aim'])
def test_low_hp_does_not_suppress_in_range_defense(kind,tmp_path,monkeypatch):
    st=state();p=st['players'][1];p['hp']=1
    target=enemy(p,x=p['x']+5 if kind=='aim' else p['x'],z=p['z'] if kind=='aim' else p['z']+5)
    st['entities']=[target];c,commands=controller(st,tmp_path,monkeypatch)
    monkeypatch.setattr(c.maps,'get',lambda *_:grid())
    c.tick(st)
    actual=[row for row in commands if row[0]==1 and row[1]!=['l']]
    assert actual
    assert actual[0][1]==(['a'] if kind=='attack' else ['lleft'])

def test_early_margin_branch_clears_old_weapon_target_telemetry(tmp_path,monkeypatch):
    st=margin_state();c,commands=controller(st,tmp_path,monkeypatch)
    c.combat_status={1:dict(range='stale',target='old'),2:dict(range='stale',target='old')}
    c.tick(st)
    assert all(row['target'] is None and isinstance(row['range'],dict) for row in c.combat_status.values())
    assert all('distance' not in row for row in c.combat_status.values())

@pytest.mark.parametrize('cooling',[False,True])
def test_distant_same_room_enemy_does_not_prevent_exact_margin_recovery(cooling,tmp_path,monkeypatch):
    st=margin_state();p=st['players'][2];p['room']=11
    st['entities']=[enemy(p,z=p['z']+100)]
    c,commands=controller(st,tmp_path,monkeypatch)
    if cooling:c.cooldown[(2,'80ABCDEF')]=float('inf')
    assert c.tick(st)
    rows=[r for r in commands if r[1]!=['l']]
    assert len(rows)==1 and rows[0][0]==2 and rows[0][2]==.04
    assert c.margin_attempts[2]['attempts']==1
    assert c.field.status['players']['2']['dependency']=='margin_recovery'

def test_near_attack_precedes_margin_even_with_valid_proof(tmp_path,monkeypatch):
    st=margin_state();p=st['players'][2];p['room']=11
    st['entities']=[enemy(p)]
    c,commands=controller(st,tmp_path,monkeypatch)
    assert c.tick(st)
    assert (2,['a'],.12) in commands and 2 not in c.margin_attempts

def test_failed_stance_defers_target_and_fresh_search_does_not_starve_other_attack(tmp_path,monkeypatch):
    st=state();st['players'][2]['room']=11
    st['entities']=[enemy(st['players'][1],z=200,y=80),enemy(st['players'][2],ptr='80ABCDEE')]
    c,commands=controller(st,tmp_path,monkeypatch);nav=grid()
    monkeypatch.setattr(c.maps,'get',lambda *_:nav)
    monkeypatch.setattr(C,'time',SimpleNamespace(monotonic=lambda:1.))
    assert not c.tick(st)
    assert c.cooldown[(1,'80ABCDEF')]==9.
    assert all(keys==['l'] for _,keys,_ in commands)
    commands.clear();assert c.tick(st)
    assert any(slot==2 and keys==['a'] for slot,keys,_ in commands)

def test_actual_current_forest_all_three_claw_targets_have_own_layer_stances(tmp_path):
    raw=json.loads((BASE/'observer-v1/field-geometry-receipt-1793622503722814000.json').read_text())['result']
    captured=json.loads((BASE/'observer-v1/layer-evidence-1793634267920908700.json').read_text())['result']['native']
    st=copy.deepcopy(captured);st['players']={int(k):v for k,v in st['players'].items()}
    st['entities']=[dict(e,kind='enemy') for e in st['enemies']]
    p=st['players'][2];p['controller']=2
    atlas=Atlas(raw['triangles']);view=atlas.project(p);assert view
    st.update(geometry_verified=True,geometry_identity='exact-current',geometry_players={2:dict(view,geometry_identity='exact-current')})
    nav=Maps(tmp_path).get(st,p);f=FieldObjectives()
    targets=[e for e in st['entities'] if e.get('kind')=='enemy' and e.get('hp',0)>0]
    assert len(targets)==3
    for target in targets:
        goal=f.combat_goal(nav,p,target,ENVELOPE)
        assert goal, target
        route=f.route(nav,(p['x'],p['z']),goal)
        assert route and all(nav.allowed(nav.cell(a),nav.cell(b)) for a,b in zip(route,route[1:]))
        assert math.dist(goal,(target['x'],target['z']))<=11.9*.9
