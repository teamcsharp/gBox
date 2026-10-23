"""Actual HP-loss receipts train soft, decaying floor costs; no inferred attacker."""
import copy
import json
from types import SimpleNamespace

import pytest

from gbox.mercs import damage
from gbox.mercs.titles.re5_nav import Learning
from test_re5_nav import floor_grid, floor_pair


def test_damage_risk_persists_decays_deduplicates_and_cannot_block_a_required_goal(tmp_path):
    mesh=floor_pair()
    start,hit=(150.,0.,50.),(50.,0.,150.)
    learned=Learning(tmp_path/'nav.json')
    assert learned.note_damage(mesh,hit,'1'*32,observed_at=1000.)
    assert not learned.note_damage(mesh,hit,'1'*32,observed_at=1000.)
    assert learned.link_penalties(mesh,now=1000.)=={(0,1):250.}
    assert learned.link_penalties(mesh,now=2800.)=={(0,1):125.}
    assert mesh.route(start,hit,link_penalties=learned.link_penalties(mesh,now=1000.))[-1]==hit
    learned.save()
    restored=Learning(tmp_path/'nav.json')
    assert restored.link_penalties(mesh,now=1000.)=={(0,1):250.}
    assert not restored.note_damage(mesh,hit,'1'*32,observed_at=1000.)
    assert not restored.link_penalties(floor_pair(y=300.),now=1000.)
    assert not restored.link_penalties(floor_pair(reverse=True),now=1000.)
    assert restored.link_penalties(floor_pair(ptr=999),now=1000.)=={(0,1):250.}
    assert 'attacker' not in json.dumps(restored.stages) and 'mine' not in json.dumps(restored.stages)


def test_learned_damage_risk_changes_measured_route_choice_without_changing_geometry():
    mesh=floor_grid([(x,z) for x in range(3) for z in range(2)])
    start,goal=(25.,0.,20.),(275.,0.,20.)
    baseline=mesh.route(start,goal,pull=False)
    learned=Learning()
    for i,point in enumerate(((125.,0.,20.),(125.,0.,80.),(175.,0.,20.),(175.,0.,80.))):
        assert learned.note_damage(mesh,point,f'{i:032x}',observed_at=1000.)
    penalties=learned.link_penalties(mesh,now=1000.)
    safer=mesh.route(start,goal,pull=False,link_penalties=penalties)
    assert safer and safer[-1]==goal and safer!=baseline
    assert max(p[2] for p in safer)>100. and max(p[2] for p in baseline)<=100.
    assert all(mesh.floor_segment(a,b) for a,b in zip([start]+safer,safer))
    assert all(0<cost<=1000 for cost in penalties.values())


@pytest.mark.parametrize('position,identity,at',[
    ((100.,0.,100.),'1'*32,1000.),  # ambiguous shared boundary
    ((50.,80.,150.),'1'*32,1000.),  # airborne
    ((-10.,0.,150.),'1'*32,1000.),
    ((50.,0.,150.),'not-an-incident',1000.),
    ((50.,0.,150.),'1'*32,float('nan')),
    ((50.,0.,150.),'1'*32,-1.),
])
def test_unmeasured_floor_or_invalid_event_cannot_train(position,identity,at):
    learned=Learning()
    assert not learned.note_damage(floor_pair(),position,identity,observed_at=at)
    assert not learned.stages


def test_damage_risk_bounds_and_untrusted_file_fields(tmp_path):
    class Small(Learning):
        MAX_DAMAGE_NODES,MAX_DAMAGE_EVENTS=1,2
    learned=Small(tmp_path/'nav.json');mesh=floor_pair()
    for i in range(10):
        assert learned.note_damage(mesh,(50.,0.,150.),f'{i:032x}',observed_at=1000.)
    assert len(learned.stages[mesh.learning_sig]['damage_events'])==2
    assert learned.link_penalties(mesh,now=1000.)=={(0,1):1000.}
    learned.save(); data=json.loads(learned.path.read_text())
    data['stages'][mesh.learning_sig]['damage_risk']['0']={'weight':float('nan'),'at':1000,'pos':[1,0,1]}
    learned.path.write_text(json.dumps(data))
    restored=Small(learned.path)
    assert all(row['weight']<=4 for row in restored.stages[mesh.learning_sig]['damage_risk'].values())
    assert not restored.link_penalties(mesh,now=1000.+1800.*20)


def _observe_loss(tmp_path,emit,learn,monkeypatch):
    from gbox.mercs.titles import re5_mines
    monkeypatch.setattr(re5_mines,'ground_mines',lambda m:{})
    mesh=floor_pair();stats={}
    observer=damage.Observer(emit,'round','BLUS30491',stats,raw=lambda *a:{'state':'done'})
    brain=SimpleNamespace(nav_learning=SimpleNamespace(note_damage=learn))
    snap={'player':{'ptr':123,'pos':[50.,0.,150.],'hp':1000,'hp_max':1000},'nav':mesh}
    observer.before(snap,'playing',None,brain,now=1.);observer.after(snap,'playing',now=1.)
    snap['player']['hp']=900
    return observer,snap,brain,stats


def test_observer_durable_capture_precedes_risk_training_and_preserves_unknown_cause(tmp_path,monkeypatch):
    order=[];learned=Learning(tmp_path/'nav.json');saved=[]
    def emit(event):
        assert not learned.stages
        order.append('durable');saved.append(copy.deepcopy(event))
    def learn(mesh,position,identity,*,observed_at):
        assert order==['durable'] and saved[0]['navigation_geometry']==mesh.learning_sig
        order.append('learned')
        return learned.note_damage(mesh,position,identity,observed_at=observed_at)
    observer,snap,brain,stats=_observe_loss(tmp_path,emit,learn,monkeypatch)
    event=observer.before(snap,'playing',None,brain,now=1.1)
    assert order==['durable','learned'] and stats['player_damage_events']==1
    assert saved[0]['cause']==saved[0]['self_damage']=='unknown'
    assert learned.link_penalties(snap['nav'],now=1.1)=={(0,1):250.}
    assert event['loss']==100 and event['navigation_geometry']==snap['nav'].learning_sig
    assert stats['nav_damage_samples_learned']==1


def test_evidence_backpressure_prevents_training_and_learning_failure_cannot_lose_incident(tmp_path,monkeypatch):
    trained=[]
    def fail(event):raise damage.Backpressure('full')
    observer,snap,brain,stats=_observe_loss(tmp_path,fail,lambda *a,**k:trained.append(1),monkeypatch)
    with pytest.raises(damage.Backpressure):observer.before(snap,'playing',None,brain,now=1.1)
    assert not trained
    events=[]
    def broken(*a,**k):raise RuntimeError('training failed with sensitive details')
    observer,snap,brain,stats=_observe_loss(tmp_path,events.append,broken,monkeypatch)
    assert observer.before(snap,'playing',None,brain,now=1.1) is not None and len(events)==1
    assert stats['nav_damage_learning_error']=='RuntimeError' and stats['player_damage_events']==1


def test_health_cap_change_is_not_an_hp_loss_or_a_hazard_sample(tmp_path,monkeypatch):
    events=[];trained=[]
    observer,snap,brain,stats=_observe_loss(tmp_path,events.append,lambda *a,**k:trained.append(1),monkeypatch)
    snap['player'].update(hp=1000,hp_max=30000)
    assert observer.before(snap,'playing',None,brain,now=1.1) is None
    assert not events and not trained
